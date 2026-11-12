"""全量扫描 BLE，列出所有设备的地址/名字/服务/mfr，用来找 FIIL 耳机。

用法: python _tools\scan_all2.py --timeout 15
"""
from __future__ import annotations

import argparse
import asyncio


async def main_async(timeout: float) -> None:
    from bleak import BleakScanner

    print(f"[*] 扫描 {timeout:g}s ...")
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    print(f"[+] 共 {len(found)} 台\n")
    for addr, (dev, adv) in sorted(found.items()):
        name = adv.local_name or dev.name or "(无名字)"
        svc = ",".join(u[:8] for u in adv.service_uuids) or "-"
        mfr = ",".join(f"0x{k:04x}" for k in adv.manufacturer_data) or "-"
        print(f"  {addr}  rssi={adv.rssi:>4}  name={name:<28} svc={svc:<24} mfr={mfr}")
        if 564 in adv.manufacturer_data:
            print(f"     ^^^ FIIL 厂商数据: {adv.manufacturer_data[564].hex(' ')}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--timeout", type=float, default=15.0)
    args = p.parse_args()
    asyncio.run(main_async(args.timeout))


if __name__ == "__main__":
    main()
