"""模仿官方激活时序：读 UUID -> 立刻写 license -> 回读 142。

官方 F046HomeFragment 的流程是：
  1. getLeftHeadsetUUID(callback)          （拿到 16 字节设备 UUID）
  2. 把这个 UUID 发给服务器，换 activateCode
  3. F046UnlockLDACActivity 用 0x00 + code 组成 17 字节写入

之前我的 62 次尝试都是「直接写」，没有先读 UUID。
若固件有防重放窗口（必须先读 UUID 才能写 license），之前全部失败就能解释。

本脚本只做一件事：严格按官方时序重放一次，内容用设备自己的 UUID。
142 当前已是 00，写错也不会有额外损失。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import fiil_ble as B

ADDR = "B0:F1:A3:A8:7A:C8"


async def main():
    opts = B.Options() if hasattr(B, "Options") else None
    if opts is None:
        class O:
            addr = ADDR
            connect_timeout = 25.0
            gap = 0.8
            write_response = False
            evidence_dir = str(Path(__file__).resolve().parent.parent / "docs" / "evidence")
            switch_wait = 1.2
            reconnect_delay = 4.0
        opts = O()
    opts.addr = ADDR

    async with B.Session(opts, tag="mimic_official") as s:
        await s.handshake()

        # 1) 完全照官方：先读左耳 UUID
        print("\n=== 步骤 1：读左耳 UUID（官方流程第一步）===")
        lu = await B.query(s, B.CID_QUERY, B.Q_LEFT_UUID, label="左耳UUID(138)")
        print(f"    左耳 UUID = {lu.hex() if lu else None}")

        if not lu or len(lu) != 16:
            print("[!] 读不到 UUID，中止")
            return

        # 2) 组装 license（官方 F046UnlockLDACActivity: bArr[0]=0 + code16B）
        lic = B.build_license(lu, 0x00)
        print(f"\n=== 步骤 2：组装 license（0x00 + UUID16B）===")
        print(f"    {lic.hex(' ').upper()}")

        # 3) 立即写入（不等待，模拟官方紧接在回调里写）
        print("\n=== 步骤 3：立即写 setActivationLdac（无间隔）===")
        await s.send("setActivationLdac", B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, lic, wait=1.5)

        # 4) 立刻回读 142
        print("\n=== 步骤 4：立刻回读 142 ===")
        await asyncio.sleep(0.6)
        un = await B.query(s, B.CID_QUERY, B.Q_LDAC_UNLOCK, label="LDAC已解锁(142)")
        print(f"    142 = {un.hex() if un else None}")

        await s.save_evidence()

    # 5) 重连再确认一次（有些固件要重新建链才更新）
    print("\n=== 步骤 5：重连后再次确认 142 ===")
    await asyncio.sleep(3.0)
    async with B.Session(opts, tag="mimic_official_verify") as s:
        await s.handshake()
        await asyncio.sleep(0.4)
        un = await B.query(s, B.CID_QUERY, B.Q_LDAC_UNLOCK, label="LDAC已解锁(142)")
        sw = await B.query(s, B.CID_QUERY, B.Q_LDAC_SWITCH, label="LDAC开关(143)")
        co = await B.query(s, B.CID_QUERY, B.Q_CODEC, label="编解码(144)")
        print(f"\n    142={un.hex() if un else None}  143={sw.hex() if sw else None}  144={co.hex() if co else None}")
        await s.save_evidence()

    print("\n[=] 结论：")
    print("    142 仍为 00 -> 防重放窗口假设不成立，license 有内容校验")
    print("    142 变 01   -> 突破！官方时序是必要条件")


asyncio.run(main())
