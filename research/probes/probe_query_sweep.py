"""盲扫 cid=39 (QUERY) 的命令空间，找固件里未公开的查询命令。

背景: FIIL+ 只用了 getLeftUUID(138)/getLdacUnlock(142)/getLdacSwitch(143)/getCodec(144) 等十来个，
但固件可能实现了更多（例如回读已写入的 license）。本脚本逐条发 query，记录所有有实质回包的命令。

用法:
  python _tools\probe_query_sweep.py --start 0 --end 130
  python _tools\probe_query_sweep.py --only 128,129,130,131
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


async def sweep(args) -> None:
    cmds = [int(x, 0) for x in args.only.split(",")] if args.only else [
        c for c in range(args.start, args.end + 1) if c != 255
    ]
    lines: list[str] = []
    found: list[tuple[int, str]] = []

    s = B.Session(args.addr, args, tag="query_sweep")
    async with s:
        await s.handshake()
        await asyncio.sleep(0.5)
        for cmd in cmds:
            s.rx.clear()
            try:
                frames = await s.send(f"query {cmd:#04x}", B.CID_QUERY, cmd, b"\x00", wait=args.wait)
            except Exception as exc:  # noqa: BLE001
                lines.append(f"cmd={cmd:3d} ({cmd:#04x})  WRITE-FAIL {exc}")
                await asyncio.sleep(args.delay)
                continue
            mine = [f for f in frames if f.cmd == cmd]
            if not mine:
                lines.append(f"cmd={cmd:3d} ({cmd:#04x})  no-reply")
            else:
                for f in mine:
                    payload = f.payload.hex(" ")
                    lines.append(f"cmd={cmd:3d} ({cmd:#04x})  RX len={len(f.payload):2d} payload={payload}")
                    found.append((cmd, payload))
            await asyncio.sleep(args.delay)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out = EVID / f"evi_query_sweep_{ts}.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n=== 扫描 {len(cmds)} 条命令，有回包 {len(found)} 条 ===")
    for cmd, payload in found:
        print(f"  {cmd:3d} ({cmd:#04x})  {payload}")
    print(f"证据: {out}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--addr", default=ADDR)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end", type=int, default=130)
    p.add_argument("--only", default="")
    p.add_argument("--delay", type=float, default=0.12)
    p.add_argument("--wait", type=float, default=0.28)
    p.add_argument("--scan-timeout", type=float, default=6.0)
    p.add_argument("--connect-timeout", type=float, default=20.0)
    p.add_argument("--gap", type=float, default=0.8)
    p.add_argument("--switch-wait", type=float, default=1.2)
    p.add_argument("--reconnect-delay", type=float, default=4.0)
    p.add_argument("--write-response", action="store_true")
    p.add_argument("--evidence-dir", default=str(EVID))
    args = p.parse_args()
    asyncio.run(sweep(args))


if __name__ == "__main__":
    main()
