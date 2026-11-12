"""最后几个结构性候选：F046 也可能是「右耳形态 01||uuid」或「左右各写一次」。

已试并被拒（m00562）：
  · 00||uuid  → 142 从 1 掉到 0
  · 全零      → 142 = 0
  · 15 个校验和变体 + 43 个 md5/sha1 派生 → 全 0

本脚本试：
  A) 01||uuid            （右耳形态，官方后门用的就是 01 前缀）
  B) 00||uuid 后紧接 01||uuid（模仿 F048 的左右各一次）
  C) uuid||00            （uuid 在前，尾字节补 0）
  D) 不带前缀的裸 uuid   （firmware 可能自己加前缀）

每次写完立即读 142。
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "fiil-ldac-unlock"
sys.path.insert(0, str(REPO / "src"))

import fiil_ble as B  # noqa: E402

ADDR = "B0:F1:A3:A8:7A:C8"


async def read142(s):
    fs = await s.send("142", B.CID_QUERY, B.Q_LDAC_UNLOCK, wait=0.8)
    for f in fs or []:
        if f.cid == B.CID_QUERY and f.cmd == B.Q_LDAC_UNLOCK and f.payload:
            return f.payload[0]
    return None


async def write_lic(s, label, frame_payload):
    await s.send(label, B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, frame_payload, wait=0.8)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", default=ADDR)
    args = ap.parse_args()

    ns = argparse.Namespace(
        addr=args.addr, scan_timeout=6.0, connect_timeout=20.0,
        gap=0.5, switch_wait=1.0, reconnect_delay=0.0,
        write_response=False, evidence_dir="docs/evidence",
    )

    async with B.Session(args.addr, ns, tag="struct_sweep") as s:
        await s.handshake()
        lu = await s.send("UUID-L", B.CID_QUERY, B.Q_LEFT_UUID)
        uuid = b"".join(f.payload for f in lu if f.cid == B.CID_QUERY)
        if len(uuid) != 16:
            print("[!] UUID 长度异常")
            return 2
        print(f"[*] UUID = {uuid.hex()}")
        print(f"[*] 142 起始 = {await read142(s)}")

        trials = [
            ("A 右耳形态 01||uuid", [bytes([1]) + uuid]),
            ("B 左右各一次", [bytes([0]) + uuid, bytes([1]) + uuid]),
            ("C uuid||00", [uuid + bytes([0])]),
            ("D 裸 uuid 16B", [uuid]),
        ]
        for name, payloads in trials:
            print(f"\n=== {name} ===")
            for p in payloads:
                await write_lic(s, "lic", p)
                print(f"    wrote {p.hex()}")
            got = await read142(s)
            print(f"    → 142 = {got}   {'<<<< HIT' if got == 1 else ''}")
            if got == 1:
                print(f"\n[✓] 命中：{name}")
                return 0

    print("\n[!] 结构性候选也全部被拒。")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
