"""宽扫：列出所有 BLE 广播，标出任何带 0xFDB3 服务、0x0234 厂商数据的设备。

出厂重置后耳机可能改了名字/地址/广播内容，所以不能只按固定 MAC 找。
"""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")

from bleak import BleakScanner

TARGET_SVC = "0000fdb3"
TARGET_MFR = 0x0234


async def main():
    print("[*] 扫描 20 秒，抓全部广播数据 ...")
    found = await BleakScanner.discover(timeout=20.0, return_adv=True)
    print(f"[=] 共 {len(found)} 台\n")

    hits = []
    rows = []
    for addr, (dev, adv) in found.items():
        name = adv.local_name or dev.name or ""
        svcs = [str(u).lower() for u in (adv.service_uuids or [])]
        mfr = adv.manufacturer_data or {}
        rssi = adv.rssi
        tags = []
        if any(TARGET_SVC in s for s in svcs):
            tags.append("SVC-FDB3")
        if TARGET_MFR in mfr:
            tags.append("MFR-0234")
        if "fiil" in name.lower() or "key" in name.lower():
            tags.append("NAME")
        rows.append((addr, rssi, name, svcs, mfr, tags))
        if tags:
            hits.append((addr, rssi, name, svcs, mfr, tags))

    rows.sort(key=lambda r: r[1] if isinstance(r[1], int) else -999, reverse=True)
    print(f"{'地址':<20} {'RSSI':>5}  {'名称':<26} 服务/厂商")
    for addr, rssi, name, svcs, mfr, tags in rows:
        mark = " <<< " + ",".join(tags) if tags else ""
        mfr_txt = " ".join(f"0x{k:04x}={v.hex()}" for k, v in mfr.items())
        svc_txt = ",".join(s[:8] for s in svcs)
        print(f"{addr:<20} {str(rssi):>5}  {(name or '-'):<26} {svc_txt} {mfr_txt}{mark}")

    print()
    if hits:
        print(f"[!] 命中 {len(hits)} 台可能是 FIIL 的设备：")
        for addr, rssi, name, svcs, mfr, tags in hits:
            print(f"    {addr}  rssi={rssi}  name={name!r}  tags={tags}")
            for k, v in mfr.items():
                print(f"      mfr 0x{k:04x} = {v.hex()}")
    else:
        print("[!] 无任何 FDB3 / 0234 / FIIL 名字的设备 —— 耳机不在广播状态。")

    # 也报一下已知的经典蓝牙地址是否出现在 BLE 侧
    known = {"B0:F1:A3:A8:7A:C8", "B0:F1:A3:A8:7A:9D"}
    for addr, rssi, name, svcs, mfr, tags in rows:
        if addr.upper() in known:
            print(f"[+] 已知地址出现：{addr} rssi={rssi} name={name!r}")


asyncio.run(main())
