import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8")
from bleak import BleakScanner

async def main():
    devs = await BleakScanner.discover(timeout=12.0, return_adv=True)
    for addr,(d,adv) in sorted(devs.items()):
        name = d.name or adv.local_name or "?"
        print(f"{addr}  rssi={adv.rssi}  name={name}  svc={[str(u) for u in (adv.service_uuids or [])]}")
        if adv.manufacturer_data:
            for k,v in adv.manufacturer_data.items():
                print(f"    mfr 0x{k:04x} {v.hex()}")

asyncio.run(main())
