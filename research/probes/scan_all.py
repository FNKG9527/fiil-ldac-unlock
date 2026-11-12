import asyncio,sys
sys.stdout.reconfigure(encoding="utf-8",errors="replace")
from bleak import BleakScanner
async def main():
    devs = await BleakScanner.discover(timeout=10.0)
    print(f"共 {len(devs)} 台")
    for d in sorted(devs,key=lambda x:-(getattr(x,'rssi',-999) or -999)):
        nm=(d.name or "").upper()
        mark="  <== FIIL" if "FIIL" in nm else ""
        print(f"  {d.address}  rssi={getattr(d,'rssi','?'):>4}  {d.name!r}{mark}")
asyncio.run(main())
