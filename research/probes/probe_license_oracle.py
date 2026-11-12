"""license oracle：单连接连续写候选，看 142(LDAC已解锁) 是否翻回 01。

为什么这样测（真机事实 2026-11-11）：
  · 写 `00 || uuid16B` → 142 从 01 变 00
  · 写全零（官方取消激活）→ 142 = 00
  · 143 仍可置 1、144 仍返回 02(LDAC)
  → 固件**校验** license 内容；142 就是免费 oracle。
  → 一次连接里连写 N 个候选，每个只多花 ~1s，比反复重连快 5 倍。

候选分两组：
  A) 校验和假设：把 uuid 的最后一字节换成 sum8/xor8/crc16 等（真正"漏洞"形态）
  B) 派生假设：uuid 的 md5/sha1 + 常见盐
"""

import argparse
import asyncio
import binascii
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "fiil-ldac-unlock"
sys.path.insert(0, str(REPO / "src"))

import fiil_ble as B  # noqa: E402

ADDR = "B0:F1:A3:A8:7A:C8"


def checksum_variants(uuid: bytes) -> list[tuple[str, bytes]]:
    """把 uuid 的某些字节替换成校验值，看固件是不是只查校验。"""
    out = []
    body = uuid[:15]
    tail = uuid[15]

    def patch(pos: int, val: int) -> bytes:
        b = bytearray(uuid)
        b[pos] = val & 0xFF
        return bytes(b)

    s8 = sum(body) & 0xFF
    x8 = 0
    for c in body:
        x8 ^= c
    crc = binascii.crc_hqx(body, 0xFFFF)
    # 把校验值放在最后一字节（最常见）
    out.append(("cs-sum8@15", patch(15, s8)))
    out.append(("cs-xor8@15", patch(15, x8)))
    out.append(("cs-crc16lo@15", patch(15, crc & 0xFF)))
    out.append(("cs-crc16hi@15", patch(15, crc >> 8)))
    out.append(("cs-neg-sum8@15", patch(15, (-sum(body)) & 0xFF)))
    # 把校验值放在第 0 字节（license 首字节被协议占用，但试一下）
    out.append(("cs-sum8@0", patch(0, s8)))
    out.append(("cs-xor8@0", patch(0, x8)))
    # 末字节为 0（很多实现全零尾）
    out.append(("tail0", patch(15, 0)))
    # 末字节 = 0xFF
    out.append(("tailFF", patch(15, 0xFF)))
    # 全 0xFF
    out.append(("allFF", b"\xff" * 16))
    # 全 0x01
    out.append(("all01", b"\x01" * 16))
    # 只有首字节 1
    out.append(("only-first1", bytes([1]) + bytes(15)))
    # 原 uuid 但整体取反
    out.append(("uuid-not", bytes(c ^ 0xFF for c in uuid)))
    # 原 uuid 但字节倒序
    out.append(("uuid-rev", uuid[::-1]))
    # 原 uuid 但 0/1 互换
    out.append(("uuid-01swap", bytes((1 - c) if c in (0, 1) else c for c in uuid)))
    _ = tail
    return out


def derive_variants(uuid: bytes, pid: bytes) -> list[tuple[str, bytes]]:
    hexl, hexu = uuid.hex(), uuid.hex().upper()

    def md5(x):
        return hashlib.md5(x).digest()

    def sha1(x):
        return hashlib.sha1(x).digest()[:16]

    out = [
        ("md5(hexl)", md5(hexl.encode())),
        ("md5(hexu)", md5(hexu.encode())),
        ("md5(raw)", md5(uuid)),
        ("sha1(hexl)", sha1(hexl.encode())),
        ("sha1(raw)", sha1(uuid)),
        ("md5(hexl+pid)", md5(hexl.encode() + pid)),
        ("md5(raw+pid)", md5(uuid + pid)),
        ("md5(md5(hexl))", md5(md5(hexl.encode()))),
    ]
    for salt in ("fiil", "FIIL", "fengeek", "ldac", "LDAC"):
        s = salt.encode()
        out.append((f"md5(hexl+{salt})", md5(hexl.encode() + s)))
        out.append((f"md5({salt}+hexl)", md5(s + hexl.encode())))
        out.append((f"md5(raw+{salt})", md5(uuid + s)))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", default=ADDR)
    ap.add_argument("--delay", type=float, default=0.7)
    ap.add_argument("--group", default="both", choices=["cs", "derive", "both"])
    args = ap.parse_args()

    ns = argparse.Namespace(
        addr=args.addr, scan_timeout=6.0, connect_timeout=20.0,
        gap=0.5, switch_wait=1.0, reconnect_delay=0.0,
        write_response=False, evidence_dir="docs/evidence",
    )

    async with B.Session(args.addr, ns, tag="oracle_sweep") as s:
        await s.handshake()
        pid = await s.send("PID", B.CID_QUERY, B.Q_PID)
        lu = await s.send("UUID-L", B.CID_QUERY, B.Q_LEFT_UUID)
        av = await s.send("142", B.CID_QUERY, B.Q_LDAC_UNLOCK)

        pid_b = b"".join(f.payload for f in pid if f.cid == B.CID_QUERY)
        uuid = b"".join(f.payload for f in lu if f.cid == B.CID_QUERY)
        cur = b"".join(f.payload for f in av if f.cid == B.CID_QUERY)
        print(f"\n[*] PID  : {pid_b.hex()}")
        print(f"[*] UUID : {uuid.hex()}")
        print(f"[*] 142  : {cur.hex()}  (起始状态)")

        if len(uuid) != 16:
            print("[!] UUID 长度异常，退出")
            return 2

        cands: list[tuple[str, bytes]] = []
        if args.group in ("cs", "both"):
            cands += checksum_variants(uuid)
        if args.group in ("derive", "both"):
            cands += derive_variants(uuid, pid_b)

        hit = None
        for i, (name, code) in enumerate(cands, 1):
            lic = B.build_license(code, 0x00)
            await s.send(f"lic", B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, lic, wait=args.delay)
            fs = await s.send("142", B.CID_QUERY, B.Q_LDAC_UNLOCK, wait=0.6)
            got = None
            for f in fs or []:
                if f.cid == B.CID_QUERY and f.cmd == B.Q_LDAC_UNLOCK and f.payload:
                    got = f.payload[0]
            mark = "  <<<< HIT" if got == 1 else ""
            print(f"[{i:02d}/{len(cands)}] {name:20s} {code.hex()} → 142={got}{mark}")
            if got == 1:
                hit = (name, code)
                break

    print()
    if hit:
        print(f"[✓] 命中：{hit[0]} = {hit[1].hex()}")
        return 0
    print("[!] 本轮候选全部被拒。")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
