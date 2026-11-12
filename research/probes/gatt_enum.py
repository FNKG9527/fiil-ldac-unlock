"""完整枚举耳机的 GATT 服务树，找有没有第二个可写特征 / debug 通道。"""

from __future__ import annotations

import asyncio

from bleak import BleakClient

ADDR = "B0:F1:A3:A8:7A:C8"


async def main() -> None:
    async with BleakClient(ADDR, timeout=25.0) as c:
        print(f"[+] connected mtu={getattr(c, 'mtu_size', '?')}")
        for svc in c.services:
            print(f"\n=== SERVICE {svc.uuid}  [{svc.description}] ===")
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                print(f"    CHAR {ch.uuid}  [{ch.description}]")
                print(f"         properties: {props}")
                for d in ch.descriptors:
                    print(f"         DESC {d.uuid} [{d.description}]")
                # 只读那些可读且看起来安全的
                if "read" in ch.properties and len(ch.uuid) == 36:
                    if ch.uuid.startswith("00002") or ch.uuid.startswith("0000fdb3"):
                        continue
                    try:
                        v = await c.read_gatt_char(ch.uuid)
                        print(f"         value: {v.hex(' ')}   ({len(v)}B)")
                    except Exception as e:
                        print(f"         read fail: {type(e).__name__}")


if __name__ == "__main__":
    asyncio.run(main())
