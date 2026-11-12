"""用 ACK 码当「格式 oracle」探明 17 字节 license 的字段布局。

已确认的事实：
  - payload 长度必须是 17（其他长度 ACK=01），17 字节时 ACK=00
  - 但 `00‖uuid16B` 也回 ACK=00，而 `uuid16B‖00` 回 ACK=01
  - 全零 17B 回 ACK=00

本脚本要回答的问题：
  1. 首字节（耳别前缀）取 0/1/2/…255 时，ACK 是否变化？（若变化 → 前缀是受校验的字段）
  2. ACK 是否只由「长度 + 首字节」决定，而与后 16 字节内容无关？
  3. 末字节是否也是受校验字段？

用法: python _tools\probe_ack_layout.py
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
UUID16 = bytes.fromhex("aabbccddeeff00112233445566778899")

# (标签, 17 字节 payload)
CASES: list[tuple[str, bytes]] = [
    ("prefix=00 rest=0", bytes(17)),
    ("prefix=01 rest=0", bytes([1]) + bytes(16)),
    ("prefix=02 rest=0", bytes([2]) + bytes(16)),
    ("prefix=03 rest=0", bytes([3]) + bytes(16)),
    ("prefix=FF rest=0", bytes([0xFF]) + bytes(16)),
    ("prefix=00 rest=FF", bytes([0]) + bytes([0xFF]) * 16),
    ("prefix=00 rest=uuid", bytes([0]) + UUID16),
    ("prefix=01 rest=uuid", bytes([1]) + UUID16),
    ("prefix=02 rest=uuid", bytes([2]) + UUID16),
    ("prefix=00 tail=01", bytes([0]) + UUID16[:15] + bytes([1])),
    ("prefix=00 head16=uuid tail=00", UUID16 + bytes([0])),
]


async def main_async(args) -> None:
    rows: list[str] = []
    s = B.Session(args.addr, args, tag="ack_layout")
    async with s:
        await s.handshake()
        await asyncio.sleep(0.5)
        for label, payload in CASES:
            assert len(payload) == 17, (label, len(payload))
            s.rx.clear()
            frames = await s.send(f"activate {label}", B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC,
                                  payload, wait=0.8)
            ack = [f.payload.hex(" ") for f in frames if f.cmd == B.SET_ACTIVATE_LDAC]
            ack_s = ack[0] if ack else "(no-ack)"

            await asyncio.sleep(0.2)
            s.rx.clear()
            q = await s.send("get 142", B.CID_QUERY, B.Q_LDAC_UNLOCK, b"\x00", wait=0.5)
            got = [f.payload.hex(" ") for f in q if f.cmd == B.Q_LDAC_UNLOCK]
            got_s = got[0] if got else "(no-reply)"

            line = f"{label:<28} ack={ack_s:<6} 142={got_s}"
            rows.append(line)
            print(line)
            await asyncio.sleep(args.delay)

    ts = time.strftime("%Y%m%d_%H%M%S")
    p = EVID / f"evi_ack_layout_{ts}.txt"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"\n证据: {p}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--addr", default=ADDR)
    p.add_argument("--delay", type=float, default=0.3)
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
