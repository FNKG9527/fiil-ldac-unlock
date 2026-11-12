"""清理：把 0x8C/0x8D 里被我写入的 DEADBEEF 标记值还原。

今天首次读到的 0x8C 值是 AA BB CC DD EE FF 00 11 22 33 44 55 66 77 99
（这是设备在我做标记测试前持有的内容），把它写回去，不要把垃圾留在设备里。

同时把最后几个未试过的候选一并试掉。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import fiil_ble as B

ADDR = "B0:F1:A3:A8:7A:C8"


class Args:
    connect_timeout = 30.0
    gap = 0.9
    write_response = False
    evidence_dir = str(Path(__file__).resolve().parent.parent / "docs" / "evidence")


ORIGINAL_8C = bytes.fromhex("aabbccddeeff001122334455667788aa")
UUID16 = bytes.fromhex("aabbccddeeff00112233445566778899")


async def read16(s, cmd):
    frames = await s.send(f"读 0x{cmd:02X}", B.CID_QUERY, cmd)
    out = b""
    for f in frames:
        if f.cid == B.CID_QUERY and (f.cmd == cmd or f.cmd is None):
            out += f.payload
    return out


async def read1(s, cmd, label):
    frames = await s.send(label, B.CID_QUERY, cmd)
    for f in frames:
        if f.cid == B.CID_QUERY and (f.cmd == cmd or f.cmd is None):
            return f.payload
    return b""


async def write_lic(s, name, lic, note=""):
    print(f"\n--- {name} {note}")
    print(f"    {lic.hex(' ').upper()}")
    await s.send(f"写 {name}", B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, lic, wait=1.6)
    await asyncio.sleep(0.7)
    v142 = await read1(s, B.Q_LDAC_UNLOCK, "142")
    v8c = await read16(s, 0x8C)
    print(f"    142 = {v142.hex().upper() if v142 else '?'}   0x8C = {v8c.hex(' ').upper()}")
    return v142


async def main():
    async with B.Session(ADDR, Args(), tag="cleanup_8c") as s:
        await s.handshake()

        cur = await read16(s, 0x8C)
        print(f"[当前] 0x8C = {cur.hex(' ').upper()}")
        cur142 = await read1(s, B.Q_LDAC_UNLOCK, "142")
        print(f"[当前] 142  = {cur142.hex().upper() if cur142 else '?'}")

        # 最后一轮候选：都是「官方形态但内容取不同来源」
        tried = []

        v = await write_lic(s, "还原原始内容 00+原值", b"\x00" + ORIGINAL_8C, "（把垃圾值清掉）")
        tried.append(("00 + 原始0x8C内容", v))

        if v != b"\x01":
            v = await write_lic(s, "右耳形态 01+原值", b"\x01" + ORIGINAL_8C)
            tried.append(("01 + 原始0x8C内容", v))

        if v != b"\x01":
            # 两次写（左右都写一遍，官方 F048 的形态）
            print("\n--- 左右各写一次（F048 形态）")
            await s.send("写左", B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, b"\x00" + ORIGINAL_8C, wait=0.8)
            await s.send("写右", B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, b"\x01" + ORIGINAL_8C, wait=1.6)
            await asyncio.sleep(0.8)
            v = await read1(s, B.Q_LDAC_UNLOCK, "142")
            print(f"    142 = {v.hex().upper() if v else '?'}")
            tried.append(("左右各写一次", v))

        if v != b"\x01":
            # 用 UUID 原值（22:59:50 那次的形态）再确认一次
            v = await write_lic(s, "UUID原值 00+uuid78", b"\x00" + UUID16)
            tried.append(("00 + UUID(78)", v))

        print("\n" + "=" * 60)
        print("  候选结果")
        print("=" * 60)
        for name, val in tried:
            mark = "  <<<< 成功" if val == b"\x01" else ""
            print(f"  {name:<26} 142={val.hex().upper() if val else '?':<4}{mark}")

        # 最终状态
        await asyncio.sleep(1.0)
        final_8c = await read16(s, 0x8C)
        f142 = await read1(s, B.Q_LDAC_UNLOCK, "142")
        f143 = await read1(s, B.Q_LDAC_SWITCH, "143")
        f144 = await read1(s, B.Q_CODEC, "144")
        print("\n[最终状态]")
        print(f"  0x8C       = {final_8c.hex(' ').upper()}")
        print(f"  142 授权   = {f142.hex().upper() if f142 else '?'}")
        print(f"  143 开关   = {f143.hex().upper() if f143 else '?'}")
        print(f"  144 编解码 = {f144.hex().upper() if f144 else '?'}")

        s.save_evidence()


asyncio.run(main())
