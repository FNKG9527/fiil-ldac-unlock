"""边连边看：手机连接耳机时，持续轮询耳机的 143/144。

目的：判定 142=00 时，手机 A2DP 到底能不能协商成 LDAC。
- 若手机连上后 144 变 02 且手机侧也是 LDAC -> 开关确实独立于授权
- 若 144 始终 01 -> 没有 142=01 就拿不到真正的 LDAC（我之前的结论是错的）

用法：先启动本脚本，再去手机上连耳机。
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import fiil_ble as B

ADDR = "B0:F1:A3:A8:7A:C8"
OUT = Path(__file__).resolve().parent.parent / "research" / "logs" / "ldac_watch.log"


class Args:
    connect_timeout = 20.0
    gap = 0.5
    write_response = False
    evidence_dir = str(Path(__file__).resolve().parent.parent / "docs" / "evidence")


async def read1(s, cmd, label):
    frames = await s.send(label, B.CID_QUERY, cmd, wait=0.5)
    for f in frames:
        if f.cid == B.CID_QUERY and (f.cmd == cmd or f.cmd is None):
            return f.payload
    return None


def stamp():
    return datetime.now().strftime("%H:%M:%S")


async def main():
    lines = []

    def emit(t):
        print(t, flush=True)
        lines.append(t)

    emit(f"# LDAC 监控开始 {datetime.now():%Y-%m-%d %H:%M:%S}")
    emit("# 时间      142授权 143开关 144编解码")
    OUT.write_text("\n".join(lines), encoding="utf-8")

    prev = None
    for i in range(90):  # ~90 次，约 3 分钟
        try:
            async with B.Session(ADDR, Args(), tag="watch") as s:
                await s.handshake()
                for _ in range(20):  # 单次连接内多读几轮，避免频繁重连
                    u = await read1(s, B.Q_LDAC_UNLOCK, "142")
                    w = await read1(s, B.Q_LDAC_SWITCH, "143")
                    c = await read1(s, B.Q_CODEC, "144")
                    cur = (
                        u.hex().upper() if u else "?",
                        w.hex().upper() if w else "?",
                        c.hex().upper() if c else "?",
                    )
                    if cur != prev:
                        emit(f"{stamp()}  {cur[0]:<7} {cur[1]:<7} {cur[2]}")
                        OUT.write_text("\n".join(lines), encoding="utf-8")
                        prev = cur
                    await asyncio.sleep(2.0)
                s.save_evidence()
        except SystemExit:
            await asyncio.sleep(3.0)
        except Exception as exc:  # noqa: BLE001
            emit(f"{stamp()}  (连接中断: {type(exc).__name__})")
            await asyncio.sleep(3.0)

    emit(f"# 监控结束 {stamp()}")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[=] 日志已写入 {OUT}")


asyncio.run(main())
