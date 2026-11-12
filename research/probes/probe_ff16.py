"""对比测试：同一条帧分别从 0xFF17 和 0xFF16 写入，看回包差异。

背景：GATT 枚举显示 ff16 属性是 read,write（不是只读）。
此前仓库结论「ff16 不支持写」来自一次无回包的握手尝试，需重新验证。
"""

from __future__ import annotations

import asyncio

from bleak import BleakClient

ADDR = "B0:F1:A3:A8:7A:C8"
SVC = "0000fdb3-0000-1000-8000-00805f9b34fb"
FF16 = "0000ff16-0000-1000-8000-00805f9b34fb"
FF17 = "0000ff17-0000-1000-8000-00805f9b34fb"
FF18 = "0000ff18-0000-1000-8000-00805f9b34fb"

HANDSHAKE = bytes.fromhex("0027010004FF020234")


def frame(cid: int, cmd: int, payload: bytes = b"", seq: int = 0) -> bytes:
    body = bytes([len(payload) + 2, cmd]) + bytes([len(payload)]) + payload if cmd else bytes([len(payload)]) + payload
    return bytes([seq & 0xFF, cid & 0xFF, 0x01, 0x00]) + body


async def probe(char_uuid: str, label: str) -> None:
    rx: list[str] = []

    def cb(_c, data: bytearray) -> None:
        rx.append(bytes(data).hex(" ").upper())

    async with BleakClient(ADDR, timeout=25.0) as c:
        try:
            await c.start_notify(FF18, cb)
        except Exception as e:
            print(f"[{label}] notify 失败: {e}")
            return

        print(f"\n===== 写入特征 {label} ({char_uuid}) =====")

        # 1) 握手
        try:
            await c.write_gatt_char(char_uuid, HANDSHAKE, response=True)
            print(f"  [TX-握手] {HANDSHAKE.hex(' ').upper()}")
        except Exception as e:
            print(f"  [TX-握手] 写入失败: {type(e).__name__}: {e}")
            return
        await asyncio.sleep(1.2)
        print(f"  [RX] {rx if rx else '(无回包)'}")

        if not rx:
            print("  → 该特征写入后耳机完全静默，判定不可用")
            return

        # 2) 握手有回应，继续读 142
        rx.clear()
        f = frame(0x27, 0x8E, b"", 1)
        await c.write_gatt_char(char_uuid, f, response=True)
        print(f"  [TX-142]  {f.hex(' ').upper()}")
        await asyncio.sleep(1.0)
        print(f"  [RX] {rx if rx else '(无回包)'}")

        # 3) 读 143
        rx.clear()
        f = frame(0x27, 0x8F, b"", 2)
        await c.write_gatt_char(char_uuid, f, response=True)
        print(f"  [TX-143]  {f.hex(' ').upper()}")
        await asyncio.sleep(1.0)
        print(f"  [RX] {rx if rx else '(无回包)'}")

        try:
            await c.stop_notify(FF18)
        except Exception:
            pass


async def main() -> None:
    await probe(FF17, "FF17")
    await asyncio.sleep(2.0)
    await probe(FF16, "FF16")


if __name__ == "__main__":
    asyncio.run(main())
