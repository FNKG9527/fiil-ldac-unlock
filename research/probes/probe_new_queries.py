"""探查盲扫发现的未公开查询命令：0x10 / 0x83 / 0x86 / 0xfe

目的：判断这些回包是「稳定标识」（可用作 license 派生种子）还是「一次性 nonce」。
方法：同一连接内每 0.5s 读 3 次；断开重连后再读 3 次，比对。

用法: python _tools\probe_new_queries.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import fiil_ble as B  # noqa: E402

ADDR = "B0:F1:A3:A8:7A:C8"
EVID = Path(__file__).resolve().parent.parent / "research"
TARGETS = [0x10, 0x83, 0x86, 0xFE]


async def one_round(args, label: str, out: list[str]) -> dict[int, str]:
    res: dict[int, str] = {}
    s = B.Session(args.addr, args, tag=f"newq_{label}")
    async with s:
        await s.handshake()
        await asyncio.sleep(0.5)
        for rep in range(3):
            for cmd in TARGETS:
                s.rx.clear()
                frames = await s.send(f"{label} rep{rep} {cmd:#04x}", B.CID_QUERY, cmd, b"\x00", wait=0.3)
                mine = [f for f in frames if f.cmd == cmd]
                payload = mine[0].payload.hex(" ") if mine else "(no-reply)"
                out.append(f"{label} rep{rep} cmd={cmd:#04x}  {payload}")
                res.setdefault(cmd, payload)
            await asyncio.sleep(0.5)
    return res


async def main_async(args) -> None:
    out: list[str] = []
    a = await one_round(args, "conn1", out)
    await asyncio.sleep(2.0)
    b = await one_round(args, "conn2", out)

    print("\n=== 稳定性对比 ===")
    for cmd in TARGETS:
        va, vb = a.get(cmd, "-"), b.get(cmd, "-")
        same = "稳定" if va == vb else "变化(nonce?)"
        print(f"  cmd={cmd:#04x}  conn1={va:<24} conn2={vb:<24} {same}")

    ts = time.strftime("%Y%m%d_%H%M%S")
    p = EVID / f"evi_newq_{ts}.txt"
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"证据: {p}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--addr", default=ADDR)
    p.add_argument("--scan-timeout", type=float, default=6.0)
    p.add_argument("--connect-timeout", type=float, default=20.0)
    p.add_argument("--gap", type=float, default=0.8)
    p.add_argument("--switch-wait", type=float, default=1.2)
    p.add_argument("--reconnect-delay", type=float, default=4.0)
    p.add_argument("--write-response", action="store_true")
    p.add_argument("--evidence-dir", default=str(EVID))
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
