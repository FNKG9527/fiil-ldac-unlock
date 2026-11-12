"""探测 cid=39 下尚未解释的命令号，找是否存在 license 回读通道。

已知未解释：0x10 / 0x83 / 0x86 / 0x8C(防风噪) / 0x8D(未使用) / 0xFE
其中 0x8C 已证实是 getWindAdaptive（返回设备 UUID 的默认响应）。
本脚本把其余几个也读一遍，看有没有 17 字节或 license 形状的回包。
最后把 143 恢复成 01（前面实验时被关掉了）。
"""

from __future__ import annotations

import asyncio

from bleak import BleakClient

ADDR = "B0:F1:A3:A8:7A:C8"
FF16 = "0000ff16-0000-1000-8000-00805f9b34fb"
FF18 = "0000ff18-0000-1000-8000-00805f9b34fb"

HANDSHAKE = bytes.fromhex("0027010004FF020234")


def frame(cid: int, cmd: int, payload: bytes = b"", seq: int = 0) -> bytes:
    if cmd:
        body = bytes([len(payload) + 2, cmd, len(payload)]) + payload
    else:
        body = bytes([len(payload)]) + payload
    return bytes([seq & 0xFF, cid & 0xFF, 0x01, 0x00]) + body


UNKNOWN_QUERIES = [0x10, 0x83, 0x86, 0x8D, 0xFE]


async def main() -> None:
    rx: list[str] = []

    def cb(_c, data: bytearray) -> None:
        rx.append(bytes(data).hex(" ").upper())

    async with BleakClient(ADDR, timeout=25.0) as c:
        await c.start_notify(FF18, cb)
        await c.write_gatt_char(FF16, HANDSHAKE, response=True)
        await asyncio.sleep(1.0)
        print(f"[握手] {rx if rx else '(无)'}")
        rx.clear()

        seq = 1
        for q in UNKNOWN_QUERIES:
            f = frame(0x27, q, b"", seq)
            seq += 1
            await c.write_gatt_char(FF16, f, response=True)
            print(f"\n[TX] cid=39 cmd=0x{q:02X}   {f.hex(' ').upper()}")
            await asyncio.sleep(0.9)
            if rx:
                for r in rx:
                    print(f"     [RX] {r}")
                rx.clear()
            else:
                print("     [RX] (无回包)")

        # 恢复 143 = 01
        print("\n--- 恢复 143 = 01 ---")
        f = frame(0x01, 0x0D, bytes([1]), seq)
        await c.write_gatt_char(FF16, f, response=True)
        print(f"[TX] {f.hex(' ').upper()}")
        await asyncio.sleep(1.0)
        print(f"[RX] {rx if rx else '(无)'}")
        rx.clear()

        for q, lbl in ((0x8E, "142授权"), (0x8F, "143开关"), (0x90, "144编解码")):
            f = frame(0x27, q, b"", seq)
            seq += 1
            await c.write_gatt_char(FF16, f, response=True)
            await asyncio.sleep(0.8)
            print(f"[{lbl}] {rx if rx else '(无)'}")
            rx.clear()

        try:
            await c.stop_notify(FF18)
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
