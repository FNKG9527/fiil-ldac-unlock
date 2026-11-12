"""用真机读到的 0x8C/0x8D 内容当 license 试写。

背景：0x8A/0x8B（UUID）返回 ...BB 78，而 0x8C/0x8D 返回 ...BB 01（只差最后 1 字节）。
0x8C/0x8D 夹在 UUID 与 LDAC 家族中间，可能是固件内部的授权/激活记录。

142 当前 00，写错无额外损失。每次写完立刻回读 142 作为唯一判据。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import fiil_ble as B

ADDR = "B0:F1:A3:A8:7A:C8"


class Args:
    connect_timeout = 25.0
    gap = 0.9
    write_response = False
    evidence_dir = str(Path(__file__).resolve().parent.parent / "docs" / "evidence")


async def read16(s, cmd):
    frames = await s.send(f"读 0x{cmd:02X}", B.CID_QUERY, cmd)
    out = b""
    for f in frames:
        if f.cid == B.CID_QUERY and (f.cmd == cmd or f.cmd is None):
            out += f.payload
    return out


async def read142(s):
    frames = await s.send("读 142", B.CID_QUERY, B.Q_LDAC_UNLOCK)
    for f in frames:
        if f.cid == B.CID_QUERY and (f.cmd == B.Q_LDAC_UNLOCK or f.cmd is None):
            return f.payload
    return b""


async def try_license(s, name, lic):
    print(f"\n--- 试：{name}")
    print(f"    license = {lic.hex(' ').upper()}  ({len(lic)} 字节)")
    if len(lic) != 17:
        print("    跳过：不是 17 字节")
        return None
    await s.send(f"写 {name}", B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, lic, wait=1.4)
    await asyncio.sleep(0.5)
    v = await read142(s)
    print(f"    >>> 142 = {v.hex().upper() if v else '(无回包)'}")
    return v


async def main():
    async with B.Session(ADDR, Args(), tag="probe_8c_license") as s:
        await s.handshake()

        print("\n=== 先读出参考值 ===")
        u8a = await read16(s, 0x8A)
        u8c = await read16(s, 0x8C)
        u8d = await read16(s, 0x8D)
        print(f"    0x8A = {u8a.hex(' ').upper()}")
        print(f"    0x8C = {u8c.hex(' ').upper()}")
        print(f"    0x8D = {u8d.hex(' ').upper()}")
        print(f"    0x8A vs 0x8C 差异: "
              f"{[(i, hex(a), hex(b)) for i, (a, b) in enumerate(zip(u8a, u8c)) if a != b]}")

        if len(u8c) != 16:
            print("[!] 0x8C 不是 16 字节，中止")
            return

        got = await read142(s)
        print(f"\n    写入前 142 = {got.hex().upper() if got else '?'}")
        if got == b"\x01":
            print("[!] 142 已经是 01，不需要再写")
            return

        # 候选 1：0x00 + 0x8C 内容（官方 F046 形态）
        r1 = await try_license(s, "0x00 + 0x8C内容", b"\x00" + u8c)
        if r1 == b"\x01":
            print("\n[✓✓✓] 成功！142 = 01")
            return

        # 候选 2：0x01 + 0x8C 内容
        r2 = await try_license(s, "0x01 + 0x8C内容", b"\x01" + u8c)
        if r2 == b"\x01":
            print("\n[✓✓✓] 成功！142 = 01")
            return

        # 候选 3：0x00 + 0x8D 内容（若与 0x8C 不同）
        if u8d != u8c:
            r3 = await try_license(s, "0x00 + 0x8D内容", b"\x00" + u8d)
            if r3 == b"\x01":
                print("\n[✓✓✓] 成功！142 = 01")
                return

        # 候选 4：裸 0x8C 内容补 1 字节 0x00 到 17
        r4 = await try_license(s, "0x8C内容 + 0x00 尾", u8c + b"\x00")
        if r4 == b"\x01":
            print("\n[✓✓✓] 成功！142 = 01")
            return

        print("\n[=] 以上候选全部被拒（142 仍为 00）")

    # 重连最终确认
    await asyncio.sleep(2.5)
    async with B.Session(ADDR, Args(), tag="probe_8c_verify") as s:
        await s.handshake()
        v = await read142(s)
        sw = await s.send("143", B.CID_QUERY, B.Q_LDAC_SWITCH)
        print(f"\n[最终] 142={v.hex().upper() if v else '?'}")
        s.save_evidence()


asyncio.run(main())
