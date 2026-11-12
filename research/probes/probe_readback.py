"""验证 0x8C/0x8D 到底是不是「固件已存 license 的回读口」。

做法：写一个内容极其独特的 license，再读 0x8C/0x8D。
- 若 0x8C/0x8D 变成了刚写的内容 -> 它是 license 回读口（重大发现，等于有了真正 oracle）
- 若不变 -> 它与 license 无关

注意：写入会再次覆盖 142（当前已是 00，无进一步损失）。
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


# 独特到不可能巧合的 16 字节
MARKER = bytes.fromhex("deadbeefcafebabe0011223344556677")


async def connect_retry(tag, tries=6):
    last = None
    for i in range(tries):
        try:
            s = B.Session(ADDR, Args(), tag=tag)
            await s.__aenter__()
            return s
        except SystemExit as exc:
            last = exc
            print(f"    [{i + 1}/{tries}] 连不上，等 4 秒重试 ...")
            await asyncio.sleep(4.0)
    raise SystemExit(f"[!] 多轮重试仍连不上：{last}")


async def main():
    s = await connect_retry("probe_readback")
    try:
        await s.handshake()

        print("\n=== 写入前的读数 ===")
        before_8c = await read16(s, 0x8C)
        before_8d = await read16(s, 0x8D)
        before_8a = await read16(s, 0x8A)
        print(f"    0x8A = {before_8a.hex(' ').upper()}")
        print(f"    0x8C = {before_8c.hex(' ').upper()}")
        print(f"    0x8D = {before_8d.hex(' ').upper()}")

        print(f"\n=== 写入独特 license：00 + {MARKER.hex().upper()} ===")
        lic = b"\x00" + MARKER
        await s.send("写独特license", B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, lic, wait=1.6)
        await asyncio.sleep(1.0)

        print("\n=== 写入后的读数 ===")
        after_8c = await read16(s, 0x8C)
        after_8d = await read16(s, 0x8D)
        after_8a = await read16(s, 0x8A)
        after_142 = await read1(s, B.Q_LDAC_UNLOCK, "142")
        print(f"    0x8A = {after_8a.hex(' ').upper()}")
        print(f"    0x8C = {after_8c.hex(' ').upper()}")
        print(f"    0x8D = {after_8d.hex(' ').upper()}")
        print(f"    142  = {after_142.hex().upper() if after_142 else '?'}")

        print("\n=== 判定 ===")
        if after_8c == MARKER or after_8d == MARKER:
            print("    [✓✓✓] 0x8C/0x8D 就是 license 回读口！写入内容原样存了下来。")
        elif after_8c != before_8c or after_8d != before_8d:
            print("    [~] 0x8C/0x8D 有变化，但不是原样 —— 值得继续追：")
            print(f"        0x8C: {before_8c.hex(' ')} -> {after_8c.hex(' ')}")
            print(f"        0x8D: {before_8d.hex(' ')} -> {after_8d.hex(' ')}")
        else:
            print("    [-] 0x8C/0x8D 完全没变 —— 与 license 存储无关。")

        s.save_evidence()
    finally:
        await s.__aexit__(None, None, None)


asyncio.run(main())
