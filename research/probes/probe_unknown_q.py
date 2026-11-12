"""读未知查询命令：0x8C / 0x8D 夹在 UUID 与 LDAC 家族中间，可能返回 license。

全部走 cid=39（查询族），只读，不写任何东西。
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


# 已知邻居 + 6 个未知
PROBES = [
    ("?? 0x89", 0x89),
    ("左耳UUID 0x8A", 0x8A),
    ("右耳UUID 0x8B", 0x8B),
    ("** 0x8C", 0x8C),
    ("** 0x8D", 0x8D),
    ("LDAC解锁 0x8E", 0x8E),
    ("LDAC开关 0x8F", 0x8F),
    ("编解码 0x90", 0x90),
    ("?? 0x91", 0x91),
    ("** 0x86", 0x86),
    ("** 0x83", 0x83),
    ("** 0x10", 0x10),
    ("** 0xFE", 0xFE),
]


async def main():
    async with B.Session(ADDR, Args(), tag="probe_unknown_q") as s:
        await s.handshake()
        results = {}
        for label, cmd in PROBES:
            frames = await s.send(label, B.CID_QUERY, cmd)
            payload = b""
            got = False
            for f in frames:
                if f.cid == B.CID_QUERY and (f.cmd == cmd or f.cmd is None):
                    payload += f.payload
                    got = True
            results[label] = (cmd, payload, got, len(frames))

        print("\n" + "=" * 70)
        print("  查询结果汇总")
        print("=" * 70)
        for label, (cmd, payload, got, n) in results.items():
            hexs = payload.hex(" ").upper() if payload else "(空)"
            flag = ""
            if len(payload) == 16:
                flag = "   <<<< 16 字节！可能是 license"
            elif len(payload) > 16:
                flag = f"   <<<< {len(payload)} 字节"
            status = "" if got else ("  [无回包]" if n == 0 else "  [回包不匹配]")
            print(f"  0x{cmd:02X} {label:<16} len={len(payload):<3} {hexs}{flag}{status}")

        await s.save_evidence()


asyncio.run(main())
