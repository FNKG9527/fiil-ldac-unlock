"""长度探针：用 ACK 码当 oracle，反推固件期望的 license payload 长度。

已知两条判据：
  - setActivationLdac(1,12) 的回包 payload[0]：ACK 码（00 vs 01）随内容变化
  - 写成后回读 142：内容是否被接受

本脚本对长度 1..24 逐一发送「首字节 0、其余全零」的 license，记录 ACK 码与 142。
目的：找出哪一档长度让固件给出「格式正确」的 ACK，从而缩小真 license 的形态。

用法: python _tools\probe_license_length.py
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
LENGTHS = list(range(1, 25))


async def main_async(args) -> None:
    rows: list[str] = []
    s = B.Session(args.addr, args, tag="lic_len")
    async with s:
        await s.handshake()
        await asyncio.sleep(0.5)
        for n in LENGTHS:
            payload = bytes([0]) + bytes(n - 1)
            s.rx.clear()
            frames = await s.send(f"activate len={n}", B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC,
                                  payload, wait=0.7)
            ack = [f.payload.hex(" ") for f in frames if f.cmd == B.SET_ACTIVATE_LDAC]
            ack_s = ack[0] if ack else "(no-ack)"

            # 回读 142
            await asyncio.sleep(0.25)
            s.rx.clear()
            q = await s.send("get 142", B.CID_QUERY, B.Q_LDAC_UNLOCK, b"\x00", wait=0.5)
            got = [f.payload.hex(" ") for f in q if f.cmd == B.Q_LDAC_UNLOCK]
            got_s = got[0] if got else "(no-reply)"

            line = f"len={n:2d}  ack={ack_s:<10} 142={got_s}"
            rows.append(line)
            print(line)
            await asyncio.sleep(args.delay)

    ts = time.strftime("%Y%m%d_%H%M%S")
    p = EVID / f"evi_lic_len_{ts}.txt"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"\n证据: {p}")

    uniq = sorted({r.split("ack=")[1].split()[0] for r in rows})
    print(f"出现过的 ACK 码: {uniq}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--addr", default=ADDR)
    p.add_argument("--delay", type=float, default=0.35)
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
