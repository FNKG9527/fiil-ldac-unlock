"""盲扫保护：过滤掉会改变耳机状态的危险命令。

背景（真机踩过的坑）：
  ``com/fengeek/main/i/d/c.java:489-502`` 的 ``setReset`` 只设置 ``commandClassifyId(36)``，
  **既不带 commandId 也不带 payload**。也就是说任何 ``cid=36`` 的 5 字节空帧
  就是一次「恢复出厂设置」—— 耳机当场断开并重启。

盲扫 cid / cmdId 空间时，这类命令一定要跳过，否则会把测试机打掉。

用法::

    from probe_guard import is_safe_cid, is_safe_query, assert_safe

    if not is_safe_cid(cid):
        continue          # 跳过危险命令
"""

from __future__ import annotations

#: 会对耳机产生不可逆影响、或会断开连接的命令类别（cid）
DANGEROUS_CIDS: dict[int, str] = {
    36: "setReset / 恢复出厂设置（c.java:489-502 无 cmdId 裸帧即触发，会重启耳机）",
}

#: 会改写持久状态、盲扫时也应跳过的命令类别
STATEFUL_CIDS: dict[int, str] = {
    1: "SET_PARAM 主族（含 setActivationLdac 写授权、setLdacSwitch 等）",
    2: "录音/存储族（删除文件、下载录音等）",
    3: "录音查询族（可能触发录音动作）",
    32: "SET_EQ（改写 EQ 配置）",
    33: "SET_MUSIC（媒体控制，会在耳机上真的有反应）",
    34: "SET_KEY（改写按键映射）",
    37: "SET_LATENCY（改低延迟模式）",
    38: "SET_WEAR（改佩戴检测）",
    41: "SET_LANGUAGE（改语音提示语言）",
    44: "SET_MAF（改智能感应）",
    50: "SET_SPATIAL（改空间音频）",
}

#: 查询族里已知安全的命令（cid=39）。未列出的查询命令默认可扫。
KNOWN_SAFE_QUERIES = {
    1, 2, 3, 4, 5, 6, 7, 8, 12, 13, 16, 17, 18, 19, 20, 22, 24,
    128, 129, 130, 131, 132, 134, 138, 139, 140, 141, 142, 143, 144, 254,
}

#: cid=39 但**不要**盲扫的命令（万一某个 cmdId 触发状态变更）
DANGEROUS_QUERIES: dict[int, str] = {}

#: 未知命令族：允许发「5 字节空探测帧」试探有没有回包，
#: 但**不允许**继续往下扫它的 cmdId —— 没人知道它到底是干什么的。
CAUTION_CIDS: dict[int, str] = {
    35: "未知命令族（固件已实现、FIIL+ 从未调用）；只允许空帧探测，禁止展开子命令",
}


def is_safe_cid(cid: int) -> bool:
    """该 cid 是否适合盲扫（安全 + 无状态副作用）。

    注意：``CAUTION_CIDS`` 里的未知命令族返回 True —— 只表示「可以发一个空帧看看有没有回包」，
    不代表可以扫它的子命令。要继续往下扫请用 :func:`is_safe_default`。
    """
    return cid not in DANGEROUS_CIDS and cid not in STATEFUL_CIDS


def is_caution_cid(cid: int) -> bool:
    """该 cid 是否属于「能探测但不能展开」的未知命令族。"""
    return cid in CAUTION_CIDS


def is_safe_query(cmd: int) -> bool:
    """cid=39 下的该 cmdId 是否适合盲扫。"""
    return cmd not in DANGEROUS_QUERIES


def is_safe_default(cid: int, cmd: int) -> bool:
    """组合判定：cid 与 cmdId 都安全才允许发送。

    未知命令族（:data:`CAUTION_CIDS`）在这里一律返回 False —— 也就是说
    「空帧探一次有没有回包」可以，但**带着 cmdId 去展开它的子命令不行**。
    """
    if cid in CAUTION_CIDS:
        return False
    return is_safe_cid(cid) and is_safe_query(cmd)


class UnsafeCommandError(ValueError):
    """试图发送会改状态 / 会重启耳机的命令。"""


def assert_safe(cid: int, cmd: int | None = None) -> None:
    """不安全的命令直接抛异常，阻止误发。"""
    if cid in DANGEROUS_CIDS:
        raise UnsafeCommandError(f"cid={cid} 危险：{DANGEROUS_CIDS[cid]}")
    if cid in STATEFUL_CIDS and cid != 39:
        raise UnsafeCommandError(f"cid={cid} 会改状态：{STATEFUL_CIDS[cid]}")
    if cid == 39 and cmd is not None and cmd in DANGEROUS_QUERIES:
        raise UnsafeCommandError(f"cid=39 cmd={cmd} 危险：{DANGEROUS_QUERIES[cmd]}")


def describe(cid: int) -> str:
    """给 cid 一句人话说明，用于日志。"""
    if cid in DANGEROUS_CIDS:
        return f"⛔ {DANGEROUS_CIDS[cid]}"
    if cid in STATEFUL_CIDS:
        return f"⚠️  {STATEFUL_CIDS[cid]}"
    if cid in CAUTION_CIDS:
        return f"❓ {CAUTION_CIDS[cid]}"
    return "✅ 只读查询 / 无已知副作用"
