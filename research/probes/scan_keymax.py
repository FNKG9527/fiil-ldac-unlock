import asyncio, sys
from bleak import BleakScanner
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
async def main():
    devs = await BleakScanner.discover(timeout=8.0, return_adv=True)
    for addr, (d, adv) in devs.items():
        nm = d.name or ""
        if "FIIL" in nm.upper() or (d.address or "").upper().startswith("B0:F1:A3"):
            print("HIT", d.address, repr(nm), "rssi", adv.rssi, "svc_uuids", adv.service_uuids, "msd_keys", list((adv.manufacturer_data or {}).keys()))
    print("total", len(devs))
asyncio.run(main())
