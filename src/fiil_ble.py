#!/usr/bin/env python3
"""
FIIL+ LDAC 离线工具 —— BLE (GATT) 直连版
========================================

与 ``src/fiil_ldac.py``（串口 / RFCOMM 版）互补。本文件**不需要** Windows 配对出
虚拟 COM 口，直接走 BLE GATT 连耳机，因此笔记本、手机（Termux）、树莓派、Linux
都能跑。

逆向依据（全部来自 jadx 反编译产物，路径相对 ``fiil_analysis/jadx_out/sources``）::

    com/fengeek/main/j/a.java:12                      SERVICE = 0000fdb3-0000-1000-8000-00805f9b34fb
    com/fengeek/main/j/a.java:16                      MFR_ID  = 564 (0x0234)   广播里的厂商识别码
    com/fengeek/main/ble/FIILPeripheral.java:27       CCCD    = 00002902-0000-1000-8000-00805f9b34fb
    com/fengeek/main/ble/FIILPeripheral.java:441      writeCharacteristic()   ← 默认带响应写
    com/fengeek/main/ble/FIILPeripheral.java:483-505  SDP 组帧：FF 01 00 [len+2] 02 34 [cidHI][cidLO][cmd][len][payload]
    com/fengeek/main/i/b.java:writeMate               Mate 组帧：[seq][cid] 01 00 [len+2][cmd][len][payload]

写特征 ``0000ff17``、通知特征 ``0000ff18`` 在 App 源码里**没有硬编码**（由调用方
传字符串进 FIILPeripheral），是本项目在 FIIL Key Max 上实测确认的。

子命令::

    python src/fiil_ble.py scan                      # 扫描附近的 FIIL 耳机
    python src/fiil_ble.py models                    # 机型 / 协议 / 是否支持写 license
    python src/fiil_ble.py status   --addr XX:..     # 读全部状态（安全，只读）
    python src/fiil_ble.py switch   --addr XX:.. --on   # 开 LDAC
    python src/fiil_ble.py backup   --addr XX:..     # 备份 UUID 派生 license
    python src/fiil_ble.py unlock   --addr XX:.. --from-device-uuid --yes
    python src/fiil_ble.py unlock   --addr XX:.. --zeros --yes     # 官方"取消激活"原语
    python src/fiil_ble.py raw      --addr XX:.. --cid 39 --cmd 142

风险提示：
    * ``unlock`` 会真的写进耳机；先跑 ``backup``
    * 只有 F046 / F048 两族的 Mate 协议实现了 setActivationLdac（见 ``models``）
    * 切 LDAC 时耳机会断链重建 A2DP，属正常现象，程序会自动重连复核
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import sys
from datetime import datetime
from pathlib import Path

# Windows 控制台默认 GBK，中文会乱码，强制 UTF-8 输出
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

# ----------------------------------------------------------------------------
# 常量（全部来自 jadx）
# ----------------------------------------------------------------------------

SERVICE_UUID = "0000fdb3-0000-1000-8000-00805f9b34fb"      # j/a.java:12
CHAR_WRITE_UUID = "0000ff17-0000-1000-8000-00805f9b34fb"   # 实测确认
CHAR_NOTIFY_UUID = "0000ff18-0000-1000-8000-00805f9b34fb"  # 实测确认
CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"         # FIILPeripheral.java:27
MFR_ID = 564                                               # j/a.java:16

TYPE_REQUEST = 0x01
TYPE_RESPONSE = 0x02
TYPE_NOTIFY = 0x03

# commandClassifyId（com/fengeek/main/i/d/c.java 里 setCommandClassifyId 的字面量）
CID_SET_PARAM = 1        # SET 主族：激活、LDAC 开关、通透、EQ 自适应…
CID_SET_MUSIC = 33       # 媒体控制
CID_SET_LATENCY = 37     # 低延迟
CID_QUERY = 39           # 全部查询

# commandId（cid=39 查询族，见 c.java 各方法）
Q_BATTERY = 1
Q_VERSION = 2
Q_DEVICE_NAME = 3
Q_PID = 132
Q_LEFT_UUID = 138
Q_RIGHT_UUID = 139
Q_LDAC_UNLOCK = 142
Q_LDAC_SWITCH = 143
Q_CODEC = 144
Q_UNLOCK = 255           # 握手

# 固件已实现、但 FIIL+ 从未调用的查询命令（2026-11-12 盲扫 cid=39 全 255 条发现）。
# 回包在多次连接间完全一致（非 nonce），可用作设备指纹或派生种子。
# 详见 docs/PROTOCOL.md「12. 未公开查询命令」。
Q_UNKNOWN_10 = 0x10      # 实测回 `7c 05 ee e4`（4 字节，疑似固件编译号/内部版本）
Q_UNKNOWN_83 = 0x83      # 实测回 `d8 80 83 8a f0 18`（6 字节，疑似 MAC 低 6 字节倒序）
Q_UNKNOWN_86 = 0x86      # 实测回 `03 0c`（2 字节）
Q_UNKNOWN_8C = 0x8C      # 回 16 字节，与 138/139 同值（App 只用了 138/139）
Q_UNKNOWN_8D = 0x8D      # 回 16 字节，与 138/139 同值（App 只用了 138/139）
Q_UNKNOWN_FE = 0xFE      # 实测回 `08 00`（疑似协议版本/能力位）

# 固件已实现、但 FIIL+ 从未使用的命令类别（2026-11-12 盲扫 cid 0..127 发现）。
# cid=35 对本工具的 5 字节空探测帧回了 ACK（payload=01），App 源码里没有任何 cid=35 的用法。
CID_UNKNOWN_35 = 35      # 未知命令族，详情见 docs/PROTOCOL.md「12. 未公开查询命令」

# 已知的 SET 命令类别（含危险命令，probe 时会跳过）
CID_SET_RESET = 36       # ⚠️ 无 cmdId 的裸帧 = 恢复出厂设置（c.java:489-502）；会重启耳机

# commandId（cid=1 写入族）
SET_ACTIVATE_LDAC = 12   # c.java:287-302 / e.java:442-457
SET_LDAC_SWITCH = 13     # c.java:371-385

LICENSE_LEN = 17         # 1 字节耳别 + 16 字节激活码

# 机型表：PID 回包**第 2 字节**（buff[1]）就是 earType。
# 依据：七个机型族的 MainFragment 全部写成 `if (buff[1] != <机型号>) return;`
#   F045MainFragment.java:222  != 45
#   F046MainFragment.java:216  != 46
#   F047MainFragment.java:223  != 47
#   F048MainFragment.java:264  != 48
#   F049MainFragment.java:223  != 49
#   F051MainFragment.java:220  != 51
#   F053MainFragment.java:220  != 53
# 实测 Key Max 回 `00 2E 01` → buff[1]=0x2E=46 ✓（buff[0] 恒为 0x00，buff[2] 含义未定）
PID_EAR_TYPE_INDEX = 1

MODELS = {
    39: "F039 / CC Pro2 （Bluetrum 私有协议）",
    42: "F042 （Airoha，走 fastble）",
    45: "F045",
    46: "F046 / Key Max / Atom",
    47: "F047",
    48: "F048",
    49: "F049",
    51: "F051",
    53: "F053",
}

# 只有 F046（c.java）与 F048（e.java）两族的 Mate 协议实现了 setActivationLdac；
# b/d/f/g/h 五个类（F045/F047/F049/F051/F053）里根本没有这个方法。
LICENSE_CAPABLE_EAR_TYPES = {46, 48}

# 有「授权/解锁」这一概念的机型：既实现了 setActivationLdac，也实现了
# getLdacUnlockStatus（cid=39 cmdId=142）。F049/F051/F053 虽然能开关 LDAC、
# 也能读开关状态，但**没有 getLdacUnlockStatus**，App 里也没有任何激活入口
# —— 这三族根本不存在授权概念，不存在「解锁」这个动作。
#
# 2026-11-12 全机型核对（com/fengeek/main/i/d/{b,c,d,e,f,g,h}.java）：
#   机型族   setLdacSwitch  getLdacSwitchStatus  getLdacUnlockStatus  setActivationLdac
#   F045(b)  ✗              ✗                    ✗                    ✗
#   F046(c)  ✓              ✓                    ✓                    ✓
#   F047(d)  ✗              ✗                    ✗                    ✗
#   F048(e)  ✓              ✓                    ✓                    ✓
#   F049(f)  ✓              ✓                    ✗                    ✗
#   F051(g)  ✓              ✓                    ✗                    ✗
#   F053(h)  ✓              ✓                    ✗                    ✗
UNLOCK_CONCEPT_EAR_TYPES = {46, 48}

# 能开关 LDAC（不管有没有授权概念）的机型族。
LDAC_SWITCH_CAPABLE_EAR_TYPES = {46, 48, 49, 51, 53}

# 单电池机型（电量只回 1 个有效字节）
SINGLE_CELL_EAR_TYPES = {42, 46}


def license_ack_ok(license_buf: bytes) -> bool:
    """预测固件对这份 license payload 会不会回 ACK ``00``（格式合法）。

    ⚠️ 这**不是**「激活码对不对」的判据。2026-11-12 逐长度/逐内容实测确认，
    ``setActivationLdac`` 的 ACK 只校验两件事：

    1. payload 长度必须 **恰好 17 字节**
    2. 首字节必须 ∈ ``{0x00, 0x01}``（左耳 / 右耳）

    后 16 字节内容**完全不参与校验**。所以本函数返回 True 只代表「发出去会拿到 ACK 00」，
    唯一可信的成功判据仍然是**回读 ``142``（``getLdacUnlockStatus``）是否为 ``01``**。
    详见 docs/PROTOCOL.md 12.4。
    """
    return len(license_buf) == LICENSE_LEN and license_buf[0] in (0x00, 0x01)


# ----------------------------------------------------------------------------
# 帧编解码
# ----------------------------------------------------------------------------


def build_mate_frame(cid: int, cmd: int, payload: bytes = b"", seq: int = 0) -> bytes:
    """Mate 组帧，与 com/fengeek/main/i/b.java:writeMate 逐字节一致。

    布局::

        [seq][cid] 01 00 [len+2][cmd][len][payload...]

    ``cmd == 0`` 时省略 [len+2][cmd] 两字节（纯查询短帧）。
    """
    s = seq & 0x0F
    plen = len(payload)
    head = [s, cid & 0xFF, TYPE_REQUEST, 0x00]
    if cmd != 0:
        head.append((plen + 2) & 0xFF)
        head.append(cmd & 0xFF)
    head.append(plen & 0xFF)
    return bytes(head) + payload


def build_sdp_frame(cid: int, cmd: int, payload: bytes = b"") -> bytes:
    """SDP 组帧，与 FIILPeripheral.java:483-505 一致。

    布局::

        FF 01 00 [len+2] 02 34 [cidHI][cidLO][cmd][len][payload...]
    """
    plen = len(payload)
    return bytes([0xFF, 0x01, 0x00, (plen + 2) & 0xFF, 0x02, 0x34,
                  (cid >> 8) & 0xFF, cid & 0xFF, cmd & 0xFF, plen & 0xFF]) + payload


@dataclasses.dataclass
class Frame:
    raw: bytes
    seq: int
    cid: int
    ftype: int
    cmd: int | None
    payload: bytes

    @property
    def is_response(self) -> bool:
        return self.ftype == TYPE_RESPONSE

    @property
    def ok(self) -> bool | None:
        """SET 回包：payload[0]==0 成功。查询回包不适用。"""
        if not self.is_response or not self.payload:
            return None
        return self.payload[0] == 0

    def describe(self) -> str:
        t = {1: "REQ", 2: "RESP", 3: "NOTIFY"}.get(self.ftype, f"0x{self.ftype:02X}")
        return f"{t} cid={self.cid} cmd={self.cmd} len={len(self.payload)}"


def parse_frame(buf: bytes) -> Frame | None:
    """解析单帧。完整布局（lenField >= 2）::

        [0]seq [1]cid [2]type [3]reserved [4]lenField [5]cmdId [6]payloadLen [7..]payload
                                          └── = plen + 2 ──┘

    ``lenField == 0`` → 5 字节空帧（耳机表示"不认识这条命令"）
    ``lenField == 1`` → 6 字节无 cmdId 短帧（SET 应答），首字节即 payload[0]
    """
    if len(buf) < 5:
        return None
    if buf[2] not in (TYPE_REQUEST, TYPE_RESPONSE, TYPE_NOTIFY):
        return None
    if buf[3] != 0x00:
        return None
    seq, cid, ftype = buf[0], buf[1], buf[2]
    len_field = buf[4]
    if len_field == 0:
        return Frame(raw=buf[:5], seq=seq, cid=cid, ftype=ftype, cmd=None, payload=b"")
    if len_field == 1:
        if len(buf) < 6:
            return None
        return Frame(raw=buf[:6], seq=seq, cid=cid, ftype=ftype, cmd=None, payload=buf[5:6])
    total = 5 + len_field
    if len(buf) < total:
        return None
    plen = len_field - 2
    return Frame(raw=buf[:total], seq=seq, cid=cid, ftype=ftype, cmd=buf[5],
                 payload=buf[7:7 + plen])


def drain(buf: bytes) -> tuple[list[Frame], bytes]:
    """连续解出所有完整帧，返回 (帧列表, 剩余字节)。

    ⚠️ 必须区分「数据不足」与「帧头非法」：不足就保留等下一包，非法才丢 1 字节重同步。
    早期实现一律前进 1 字节会把半帧吞掉 —— 这是实测抓到的真实缺陷。
    """
    frames: list[Frame] = []
    pos = 0
    n = len(buf)
    while pos < n:
        avail = n - pos
        if avail < 5:
            break
        head = buf[pos:pos + 5]
        if head[2] not in (TYPE_REQUEST, TYPE_RESPONSE, TYPE_NOTIFY) or head[3] != 0x00:
            pos += 1
            continue
        len_field = head[4]
        need = 5 if len_field == 0 else (6 if len_field == 1 else 5 + len_field)
        if avail < need:
            break
        f = parse_frame(buf[pos:pos + need])
        if f is None:
            pos += 1
            continue
        frames.append(f)
        pos += len(f.raw)
    return frames, buf[pos:]


def _hex(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def build_license(code: bytes, ear_byte: int = 0x00) -> bytes:
    """构造 17 字节 license。

    --- 左耳形 = ``0x00`` + 16 字节激活码（F046UnlockLDACActivity.java:113 ``bArr[0]=0``）
    --- 右耳形 = ``0x01`` + 16 字节激活码（UnlockLDACActivity.java:217 ``f31486m[0]=1``）
    """
    if len(code) != 16:
        raise ValueError(f"激活码必须是 16 字节，收到 {len(code)} 字节")
    return bytes([ear_byte & 0xFF]) + code


def parse_activate_codes(text: str) -> list[bytes]:
    """把用户输入的激活码文本拆成 16 字节块。

    支持两种写法（与官方 ``UnlockLDACActivity.java:207`` 的 ``split(",")`` 一致）::

        "0123456789abcdef0123456789abcdef"                    → [16 字节]
        "0123..., fedcba..."                                  → [16 字节, 16 字节]

    返回的每一块都是 16 字节**不含耳别前缀**的内容；加前缀交给 ``build_license``。
    """
    parts = [p for p in text.replace(" ", "").replace("\t", "").split(",") if p]
    if not parts:
        raise ValueError("没有解析到任何激活码")
    if len(parts) > 2:
        raise ValueError(f"最多两段（左/右各一段），收到 {len(parts)} 段")
    out: list[bytes] = []
    for i, p in enumerate(parts, 1):
        if len(p) != 32:
            raise ValueError(
                f"第 {i} 段是 {len(p)} 个字符，必须恰好 32 个十六进制字符（16 字节）")
        try:
            out.append(bytes.fromhex(p))
        except ValueError:
            raise ValueError(f"第 {i} 段含非十六进制字符") from None
    return out


def describe_codec(v: bytes) -> str:
    if not v:
        return "<空>"
    return {1: "非 LDAC（SBC/AAC）", 2: "LDAC"}.get(v[0], f"未知(0x{v[0]:02X})")


def describe_bool(v: bytes) -> str:
    if not v:
        return "<空>"
    return {0: "否 / 关", 1: "是 / 开"}.get(v[0], f"0x{v[0]:02X}")


# ----------------------------------------------------------------------------
# 目标发现
# ----------------------------------------------------------------------------


def _load_cached_addr() -> str | None:
    env = os.environ.get("FIIL_ADDR")
    if env:
        return env.strip()
    for p in (Path("fiil_addr.txt"), Path.home() / ".fiil_addr"):
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8").strip() or None
        except OSError:
            continue
    return None


async def resolve_target(args) -> str:
    """按 --addr → 环境变量 → 缓存文件 → 扫描 的顺序找目标。"""
    if getattr(args, "addr", None):
        return args.addr
    cached = _load_cached_addr()
    if cached:
        print(f"[*] 使用缓存地址 {cached}（--addr 可覆盖）")
        return cached

    from bleak import BleakScanner

    print(f"[*] 扫描 BLE {args.scan_timeout:g}s ...")
    found = await BleakScanner.discover(timeout=args.scan_timeout, return_adv=True)
    best, best_score = None, 0
    for addr, (dev, adv) in sorted(found.items()):
        score = 0
        if SERVICE_UUID in [u.lower() for u in adv.service_uuids]:
            score += 10
        if MFR_ID in adv.manufacturer_data:
            score += 10
        name = (adv.local_name or dev.name or "").upper()
        if "FIIL" in name:
            score += 5
        if score > best_score:
            best, best_score = addr, score
    if best is None:
        raise SystemExit("[!] 没扫到 FIIL 耳机。请确认耳机已开机、未与手机保持连接，"
                         "或用 --addr 手工指定地址。")
    print(f"[+] 选中 {best}（评分 {best_score}）")
    return best


# ----------------------------------------------------------------------------
# 会话
# ----------------------------------------------------------------------------


class Session:
    """一次 BLE 连接 + 通知收帧 + 证据记录。"""

    def __init__(self, address: str, args, tag: str = "session"):
        self.address = address
        self.args = args
        self.tag = tag
        self.client = None
        self.rx: list[bytes] = []
        self.lines: list[str] = []
        self.seq = 0

    # --- 日志 ---
    def log(self, s: str = "") -> None:
        print(s)
        self.lines.append(s)

    def _next_seq(self) -> int:
        v = self.seq & 0x0F
        self.seq = (self.seq + 1) & 0x0F
        return v

    def _on_notify(self, _ch, data: bytearray) -> None:
        self.rx.append(bytes(data))

    # --- 生命周期 ---
    async def __aenter__(self) -> Session:
        from bleak import BleakClient
        from bleak.exc import BleakError

        last = None
        for attempt in range(1, 3):
            try:
                self.client = BleakClient(self.address, timeout=self.args.connect_timeout)
                await self.client.connect()
                break
            except (BleakError, OSError) as exc:  # noqa: PERF203
                last = exc
                self.log(f"[!] 第 {attempt} 次连接失败：{type(exc).__name__}: {exc}")
                self.client = None
                await asyncio.sleep(1.0)
        if self.client is None:
            raise SystemExit(f"[!] 连不上 {self.address}：{last}")

        self.log(f"[+] 已连接 {self.address}  mtu={getattr(self.client, 'mtu_size', '?')}")
        await self.client.start_notify(CHAR_NOTIFY_UUID, self._on_notify)
        self.log(f"[+] 已订阅通知 {CHAR_NOTIFY_UUID}")
        return self

    async def __aexit__(self, *exc) -> None:
        try:
            if self.client is not None:
                await self.client.stop_notify(CHAR_NOTIFY_UUID)
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.client is not None:
                await self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        self.save_evidence()

    # --- 收发 ---
    async def send(self, label: str, cid: int, cmd: int, payload: bytes = b"",
                   wait: float | None = None) -> list[Frame]:
        from bleak.exc import BleakError

        frame = build_mate_frame(cid, cmd, payload, self._next_seq())
        self.log(f"[TX] {label:<26} {_hex(frame)}")
        try:
            await self.client.write_gatt_char(
                CHAR_WRITE_UUID, frame, response=getattr(self.args, "write_response", False))
        except BleakError as exc:
            self.log(f"[!] 写入失败：{type(exc).__name__}: {exc}")
            raise
        await asyncio.sleep(self.args.gap if wait is None else wait)

        frames: list[Frame] = []
        while self.rx:
            for f in drain(self.rx.pop(0))[0]:
                self.log(f"     [RX] {_hex(f.raw):<44} {f.describe()}  payload={_hex(f.payload)}")
                frames.append(f)
        if not frames:
            self.log("     [RX] (无响应)")
        return frames

    async def handshake(self) -> None:
        """setUnlock 握手。不发这一帧，耳机对后续所有查询静默。"""
        await self.send("setUnlock(握手)", CID_QUERY, Q_UNLOCK, bytes([0x02, 0x34]), wait=0.9)

    # --- 证据 ---
    def save_evidence(self) -> Path | None:
        if not self.lines:
            return None
        out_dir = Path(self.args.evidence_dir)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"ble_{self.tag}_{ts}.log"
        head = [
            "=" * 78,
            f"# FIIL BLE 会话  tag={self.tag}  addr={self.address}  {datetime.now():%Y-%m-%dT%H:%M:%S}",
            "=" * 78,
        ]
        path.write_text("\n".join(head + self.lines) + "\n", encoding="utf-8")
        print(f"[+] 证据已存 {path}")
        return path


# ----------------------------------------------------------------------------
# 查询聚合
# ----------------------------------------------------------------------------


async def query_all(s: Session) -> dict:
    """读一遍所有能读的状态，返回 {名字: payload}。"""
    plan = [
        ("设备名", Q_DEVICE_NAME),
        ("固件版本", Q_VERSION),
        ("机型PID", Q_PID),
        ("电量", Q_BATTERY),
        ("左耳UUID", Q_LEFT_UUID),
        ("右耳UUID", Q_RIGHT_UUID),
        ("LDAC已解锁", Q_LDAC_UNLOCK),
        ("LDAC开关", Q_LDAC_SWITCH),
        ("当前编解码", Q_CODEC),
    ]
    out: dict = {}
    for name, q in plan:
        frames = await s.send(f"{name}({q})", CID_QUERY, q)
        payload = b""
        for f in frames:
            if f.cid == CID_QUERY and (f.cmd == q or f.cmd is None):
                payload += f.payload
        out[name] = payload
    return out


def print_status(state: dict) -> int:
    pid = state.get("机型PID") or b""
    ear_type = pid[PID_EAR_TYPE_INDEX] if len(pid) > PID_EAR_TYPE_INDEX else None

    print("\n" + "=" * 60)
    print("  耳机状态")
    print("=" * 60)
    for name, payload in state.items():
        print(f"  {name:<10}: {_hex(payload):<50} ({payload.hex()})")
    print("-" * 60)
    if state.get("设备名"):
        print(f"  名称解析   : {state['设备名'].decode('utf-8', 'replace')}")
    if ear_type is not None:
        model = MODELS.get(ear_type, f"未知机型（earType={ear_type}）")
        print(f"  机型解析   : {model}")
        print(f"  可写 license: {'是' if ear_type in LICENSE_CAPABLE_EAR_TYPES else '否（该机型族无 setActivationLdac）'}")
    print(f"  LDAC 解锁  : {describe_bool(state.get('LDAC已解锁', b''))}")
    print(f"  LDAC 开关  : {describe_bool(state.get('LDAC开关', b''))}")
    print(f"  当前编解码 : {describe_codec(state.get('当前编解码', b''))}")
    print("-" * 60)
    print("  提示：142（已解锁）只决定 FIIL+ App UI 是否放行开关，")
    print("        与 143/144 是两条独立路径 —— 142=00 时 LDAC 仍可正常开启。")
    print("=" * 60)
    return 0


# ----------------------------------------------------------------------------
# 子命令
# ----------------------------------------------------------------------------


async def cmd_scan(args) -> int:
    from bleak import BleakScanner

    print(f"[*] 扫描 BLE {args.scan_timeout:g}s ...")
    found = await BleakScanner.discover(timeout=args.scan_timeout, return_adv=True)
    by_addr = sorted(found.items())
    hits = []
    for addr, (dev, adv) in by_addr:
        score = 0
        if SERVICE_UUID in [u.lower() for u in adv.service_uuids]:
            score += 10
        if MFR_ID in adv.manufacturer_data:
            score += 10
        if "FIIL" in (adv.local_name or dev.name or "").upper():
            score += 5
        hits.append((score, addr, adv))

    print(f"{'地址':<20} {'RSSI':>5}  名称 / 特征")
    print("-" * 78)
    for score, addr, adv in sorted(hits, key=lambda x: (-x[0], x[1])):
        name = adv.local_name or "-"
        tags = []
        if SERVICE_UUID in [u.lower() for u in adv.service_uuids]:
            tags.append("svc=FDB3")
        if MFR_ID in adv.manufacturer_data:
            tags.append("mfr=0x0234")
        mark = "  ← FIIL" if score >= 10 else ""
        print(f"{addr:<20} {adv.rssi:>5}  {name:<12} {','.join(tags)}{mark}")
    print(f"\n共 {len(hits)} 台设备。用 --addr <地址> 指定目标。")
    return 0


async def cmd_models(_args) -> int:
    print(f"机型表（earType 取 PID 查询回包中下标 {PID_EAR_TYPE_INDEX} 的字节，不是首字节）")
    print("=" * 78)
    for et, name in sorted(MODELS.items()):
        ok = "可写 license" if et in LICENSE_CAPABLE_EAR_TYPES else "-"
        print(f"  {et:>3}  0x{et:02X}  {name:<34} {ok}")
    print("=" * 78)
    print("license 形态：")
    print("  F046（earType 46）：单次写 17 字节，首字节固定 0x00")
    print("                      —— F046UnlockLDACActivity.java:113  bArr[0] = 0")
    print("  F048（earType 48）：左右各写一次，左 0x00 前缀 / 右 0x01 前缀")
    print("                      —— UnlockLDACActivity.java:215 / :217")
    print("  17 字节全零 = 官方「取消激活」原语")
    print("                      —— F046HomeFragment.java:93-96")
    return 0


async def cmd_status(args) -> int:
    target = await resolve_target(args)
    async with Session(target, args, tag="status") as s:
        await s.handshake()
        state = await query_all(s)
    return print_status(state)


async def cmd_backup(args) -> int:
    target = await resolve_target(args)
    async with Session(target, args, tag="backup") as s:
        await s.handshake()
        left = await s.send("左耳UUID(138)", CID_QUERY, Q_LEFT_UUID)
        right = await s.send("右耳UUID(139)", CID_QUERY, Q_RIGHT_UUID)
        pid = await s.send("机型PID(132)", CID_QUERY, Q_PID)

    def _payload(frames):
        return b"".join(f.payload for f in frames if f.cid == CID_QUERY)

    lu, ru, pu = _payload(left), _payload(right), _payload(pid)
    ear_type = pu[PID_EAR_TYPE_INDEX] if len(pu) > PID_EAR_TYPE_INDEX else None

    out_dir = Path("backup")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"ble_license_{ts}.txt"
    lines = [
        f"# FIIL BLE license 备份 {ts}",
        f"# addr = {target}",
        f"# earType = {ear_type}",
        f"left_uuid  = {lu.hex()}",
        f"right_uuid = {ru.hex()}",
    ]
    if len(lu) == 16:
        lines.append(f"license_left  = {build_license(lu, 0x00).hex()}")
    if len(ru) == 16:
        lines.append(f"license_right = {build_license(ru, 0x01).hex()}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[+] 已备份到 {path}")
    print(f"    左耳 UUID = {lu.hex()}  ({len(lu)} 字节)")
    print(f"    右耳 UUID = {ru.hex()}  ({len(ru)} 字节)")
    if ear_type is not None:
        print(f"    机型      = {MODELS.get(ear_type, ear_type)}")
    return 0


async def cmd_switch(args) -> int:
    want = bool(args.on)
    target = await resolve_target(args)
    lost_link = False

    async with Session(target, args, tag=f"switch_{'on' if want else 'off'}") as s:
        await s.handshake()
        if want:
            # 官方顺序（F046HomeFragment.java:395-405）：开 LDAC 前先关低延迟
            await s.send("setLowDelay(0)", CID_SET_LATENCY, 0, bytes([0]), wait=0.6)
        try:
            frames = await s.send("setLdacSwitch", CID_SET_PARAM, SET_LDAC_SWITCH,
                                  bytes([1 if want else 0]), wait=args.switch_wait)
            ack = [f.ok for f in frames if f.cmd == SET_LDAC_SWITCH]
            if ack and ack[0] is not None:
                print(f"[+] 耳机 ACK：{'成功' if ack[0] else '失败'}")
        except Exception as exc:  # noqa: BLE001
            # 切 LDAC 会重建 A2DP 链路，耳机主动断链属预期
            lost_link = True
            print(f"[*] 写入后链路断开（预期行为）：{type(exc).__name__}: {exc}")

    if args.no_verify:
        return 0
    if lost_link:
        await asyncio.sleep(args.reconnect_delay)

    print("\n[*] 重连复核 ...")
    async with Session(target, args, tag=f"switch_{'on' if want else 'off'}_verify") as s:
        await s.handshake()
        sw = await s.send("LDAC开关(143)", CID_QUERY, Q_LDAC_SWITCH)
        cd = await s.send("编解码(144)", CID_QUERY, Q_CODEC)

    def _p(frames):
        return b"".join(f.payload for f in frames if f.cid == CID_QUERY)

    swv, cdv = _p(sw), _p(cd)
    print(f"  LDAC 开关  : {describe_bool(swv)}")
    print(f"  当前编解码 : {describe_codec(cdv)}")
    ok = (swv[:1] == b"\x01") if want else (swv[:1] == b"\x00")
    if ok:
        print(f"\n[✓] LDAC 已{'打开' if want else '关闭'}")
        return 0
    print(f"\n[!] 复核未达预期（期望开关={'开' if want else '关'}）")
    return 1


def _unlock_offline(args) -> int:
    """``unlock --code <激活码> --dry-run`` 的离线路径：只组装帧并打印，不连耳机。

    用来在耳机不在身边时核对 license 形态、或者给文档写示例。
    """
    try:
        blocks = parse_activate_codes(args.code)
    except ValueError as exc:
        print(f"[!] --code 不合法：{exc}")
        return 2
    code = blocks[0]
    code_right = blocks[1] if len(blocks) > 1 else blocks[0]

    lic_left = build_license(code, 0x00)
    lic_right = build_license(code_right, 0x01)

    print("[=] 离线模式（--dry-run），不连接耳机。")
    print(f"[*] 来源      : 自定义 activateCode"
          f"{'（左右各一段）' if len(blocks) > 1 else '（单段，左右同码）'}")
    print(f"[*] license 左: {_hex(lic_left)}")
    print(f"[*] license 右: {_hex(lic_right)}")
    print()
    print("[*] F046 只会写左耳一次（首字节 0x00），实际发送帧：")
    print(f"    {_hex(build_mate_frame(CID_SET_PARAM, SET_ACTIVATE_LDAC, lic_left, 0))}")
    print("[*] F048 左右各写一次，第二帧为：")
    print(f"    {_hex(build_mate_frame(CID_SET_PARAM, SET_ACTIVATE_LDAC, lic_right, 1))}")
    print()
    print("[!] 提醒：ACK 00 只代表「长度 17 + 首字节 0/1」格式合法，")
    print("    不代表激活码被接受。真正判据是回读 142（--from-device-uuid --yes 会做）。")
    return 0


async def cmd_unlock(args) -> int:
    # --code + --dry-run：纯离线组帧，不需要耳机在旁边（便于核对 / 离线测）
    if args.code and args.dry_run:
        return _unlock_offline(args)

    target = await resolve_target(args)

    # --- 第 1 步：读机型 + UUID ---
    async with Session(target, args, tag="unlock_probe") as s:
        await s.handshake()
        pid = await s.send("机型PID(132)", CID_QUERY, Q_PID)
        lu = await s.send("左耳UUID(138)", CID_QUERY, Q_LEFT_UUID)
        ru = await s.send("右耳UUID(139)", CID_QUERY, Q_RIGHT_UUID)
        before = await s.send("LDAC已解锁(142)", CID_QUERY, Q_LDAC_UNLOCK)

    def _p(frames):
        return b"".join(f.payload for f in frames if f.cid == CID_QUERY)

    pu, lu, ru, bv = _p(pid), _p(lu), _p(ru), _p(before)
    ear_type = pu[PID_EAR_TYPE_INDEX] if len(pu) > PID_EAR_TYPE_INDEX else None
    was_unlocked = bv[:1] == b"\x01"

    print(f"[*] 机型      : {MODELS.get(ear_type, ear_type)}")
    print(f"[*] 左耳 UUID : {lu.hex()}")
    print(f"[*] 右耳 UUID : {ru.hex()}")
    print(f"[*] 当前已解锁: {'是' if was_unlocked else '否'}")

    if ear_type is not None and ear_type not in LICENSE_CAPABLE_EAR_TYPES:
        print(f"\n[!] 该机型族（earType={ear_type}）的 Mate 协议没有 setActivationLdac 实现，"
              "只能走串口 SDP（--proto f43/f048）路径。")
        return 2

    # --- 第 2 步：构造 license ---
    if args.zeros:
        code = bytes(16)
        code_right = bytes(16)
        source = "全零（官方「取消激活」原语）"
    elif args.code:
        try:
            blocks = parse_activate_codes(args.code)
        except ValueError as exc:
            print(f"[!] --code 不合法：{exc}")
            return 2
        code = blocks[0]
        # F048 需要左右各一份；只给一段时左右用同一段（与官方「两段相同」的常见情形一致）
        code_right = blocks[1] if len(blocks) > 1 else blocks[0]
        source = "自定义 activateCode" + ("（左右各一段）" if len(blocks) > 1 else "")
    elif args.from_device_uuid:
        if len(lu) != 16:
            print(f"[!] 左耳 UUID 只有 {len(lu)} 字节，无法派生 license")
            return 2
        code = lu
        code_right = ru if len(ru) == 16 else lu
        source = "本机 UUID 自派生（离线推导：服务端 activateCode 即 deviceCode）"
    else:
        print("必须给 --code / --zeros / --from-device-uuid 之一")
        return 2

    lic_left = build_license(code, 0x00)
    lic_right = build_license(code_right, 0x01)
    print(f"\n[*] 来源      : {source}")
    print(f"[*] license 左: {_hex(lic_left)}")
    print(f"[*] license 右: {_hex(lic_right)}")

    plan = [("左耳 license", lic_left)]
    if ear_type == 48:
        plan.append(("右耳 license", lic_right))

    if args.dry_run:
        print("\n[=] --dry-run，未发送。")
        return 0
    if not args.yes:
        print("\n[!] 这会真的写进耳机。确认无误请加 --yes 重新执行。")
        return 1

    # --- 第 3 步：写入 ---
    async with Session(target, args, tag="unlock_write") as s:
        await s.handshake()
        acks = []
        for label, lic in plan:
            frames = await s.send(f"setActivationLdac({label})", CID_SET_PARAM,
                                  SET_ACTIVATE_LDAC, lic, wait=1.2)
            if frames:
                acks.extend(f.ok for f in frames if f.cmd == SET_ACTIVATE_LDAC)
        await s.send("setLdacSwitch(1)", CID_SET_PARAM, SET_LDAC_SWITCH, bytes([1]), wait=1.2)

    if acks and acks[0] is not None:
        print(f"[+] 耳机 ACK：{'成功' if acks[0] else '失败'}")

    # --- 第 4 步：复核 ---
    await asyncio.sleep(args.reconnect_delay)
    print("\n[*] 重连复核 ...")
    async with Session(target, args, tag="unlock_verify") as s:
        await s.handshake()
        av = await s.send("LDAC已解锁(142)", CID_QUERY, Q_LDAC_UNLOCK)
        sw = await s.send("LDAC开关(143)", CID_QUERY, Q_LDAC_SWITCH)
        cd = await s.send("编解码(144)", CID_QUERY, Q_CODEC)

    av, sw, cd = _p(av), _p(sw), _p(cd)
    print(f"  LDAC 已解锁: {describe_bool(av)}")
    print(f"  LDAC 开关  : {describe_bool(sw)}")
    print(f"  当前编解码 : {describe_codec(cd)}")

    if args.zeros:
        print("\n[✓] 已写入「取消激活」。要恢复请跑 unlock --from-device-uuid --yes")
        return 0
    if av[:1] == b"\x01":
        print("\n[✓] 解锁成功（142=01）")
        return 0
    print("\n[!] 142 仍为 0 —— license 未被接受。")
    if was_unlocked:
        print("    警告：写入前本来是已解锁的，这次写入把状态改掉了。")
        print("    建议依次尝试：unlock --zeros --yes → unlock --code <原激活码> --yes")
    return 1


async def cmd_raw(args) -> int:
    target = await resolve_target(args)
    payload = bytes.fromhex(args.payload.replace(" ", "")) if args.payload else b""
    async with Session(target, args, tag="raw") as s:
        if args.no_handshake is False:
            await s.handshake()
        frames = await s.send(args.label, args.cid, args.cmd, payload)
    if not frames:
        print("[!] 无响应")
        return 1
    return 0


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="FIIL+ LDAC 离线工具（BLE GATT 直连，不依赖 FIIL 服务器）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--addr", help="耳机 BLE 地址，如 B0:F1:A3:A8:7A:C8")
    ap.add_argument("--scan-timeout", type=float, default=8.0, help="扫描秒数，默认 8")
    ap.add_argument("--connect-timeout", type=float, default=20.0)
    ap.add_argument("--gap", type=float, default=0.8, help="每帧后等待秒数，默认 0.8")
    ap.add_argument("--switch-wait", type=float, default=1.2)
    ap.add_argument("--reconnect-delay", type=float, default=4.0,
                    help="切 LDAC 断链后等多久重连，默认 4s")
    ap.add_argument("--write-response", action="store_true",
                    help="用带响应写（App 默认行为）；不加则用不带响应写（实测更稳）")
    ap.add_argument("--evidence-dir", default="docs/evidence",
                    help="证据输出目录，默认 docs/evidence")

    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan", help="扫描附近的 FIIL 耳机").set_defaults(func=cmd_scan)
    sub.add_parser("models", help="打印机型 / license 能力表").set_defaults(func=cmd_models)
    sub.add_parser("status", help="读全部状态（只读，安全）").set_defaults(func=cmd_status)
    sub.add_parser("backup", help="备份 UUID 派生 license").set_defaults(func=cmd_backup)

    p = sub.add_parser("switch", help="开 / 关 LDAC")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--on", action="store_true", help="打开 LDAC")
    g.add_argument("--off", action="store_true", help="关闭 LDAC")
    p.add_argument("--no-verify", action="store_true", help="写完不重连复核")
    p.set_defaults(func=cmd_switch)

    p = sub.add_parser("unlock", help="写入 license 解锁 LDAC")
    p.add_argument("--code", help="32 个 hex 字符的 activateCode")
    p.add_argument("--zeros", action="store_true", help="写全零（官方取消激活原语）")
    p.add_argument("--from-device-uuid", action="store_true",
                   help="用耳机自己的 UUID 派生 license（离线解锁假设）")
    p.add_argument("--dry-run", action="store_true", help="只打印，不写入")
    p.add_argument("--yes", action="store_true", help="确认真的写入")
    p.set_defaults(func=cmd_unlock)

    p = sub.add_parser("raw", help="发任意一帧（研究用）")
    p.add_argument("--cid", type=int, required=True)
    p.add_argument("--cmd", type=int, required=True)
    p.add_argument("--payload", default="", help='十六进制，如 "0234"')
    p.add_argument("--label", default="raw")
    p.add_argument("--no-handshake", action="store_true", help="跳过 setUnlock 握手")
    p.set_defaults(func=cmd_raw)

    return ap


_GLOBAL_FLAGS = (
    "--addr", "--scan-timeout", "--connect-timeout", "--gap", "--switch-wait",
    "--reconnect-delay", "--write-response", "--evidence-dir",
)


def _normalize_argv(argv: list[str]) -> list[str]:
    """允许全局参数写在子命令后面（python src/fiil_ble.py scan --scan-timeout 6）。

    argparse 的全局参数默认只能出现在子命令之前，这里把它们挪到前面。
    """
    out, tail = [], []
    i = 0
    while i < len(argv):
        a = argv[i]
        hit = next((g for g in _GLOBAL_FLAGS if a == g or a.startswith(g + "=")), None)
        if hit:
            tail.append(a)
            if a == hit and i + 1 < len(argv):
                tail.append(argv[i + 1])
                i += 2
                continue
        else:
            out.append(a)
        i += 1
    return tail + out


def main(argv=None) -> int:
    ap = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    args = ap.parse_args(_normalize_argv(raw))
    if hasattr(args, "off") and args.off:
        args.on = False
    try:
        return asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("\n[!] 已中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
