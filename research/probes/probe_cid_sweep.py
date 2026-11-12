"""扫 cid（命令类别）空间，找固件里 App 未使用的命令族。

已知 App 用到的 cid: 1(SET_PARAM) 2/3(录音) 32(SET_EQ) 33(SET_MUSIC) 34(SET_KEY)
36(SET_RESET) 37(SET_LATENCY) 38(SET_WEAR) 39(QUERY) 41(SET_LANGUAGE) 44(SET_MAF) 50(SET_SPATIAL)
实测出现过 cid=40 的耳机主动 NOTIFY，故 cid 空间不止这些。

做法：对每个 cid 发一条「无 payload 的最小探测帧」，记录任何回包。
      无 cmdId 的帧（lenField=0）在协议里是合法最小帧，固件不认识就静默。

用法: python _tools\probe_cid_sweep.py --start 0 --end 127
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import fiil_ble as B  # noqa: E402
import probe_guard as G  # noqa: E402

ADDR = "B0:F1:A3:A8:7A:C8"
EVID = Path(__file__).resolve().parent.parent / "research"

KNOWN = {1, 2, 3, 32, 33, 34, 36, 37, 38, 39, 40, 41, 44, 50}


async def main_async(args) -> None:
    cids = [int(x) for x in args.only.split(",")] if args.only else list(range(args.start, args.end + 1))
    rows: list[str] = []
    hits: list[tuple[int, str]] = []

    s = B.Session(args.addr, args, tag="cid_sweep")
    async with s:
        await s.handshake()
        await asyncio.sleep(0.5)
        for cid in cids:
            if not G.is_safe_cid(cid):
                rows.append(f"cid={cid:3d}  SKIP  {G.describe(cid)}")
                print(f"  [跳过] cid={cid:3d}  {G.describe(cid)}")
                continue
            s.rx.clear()
            # lenField=0 的空帧：只是 5 字节 [seq][cid][type][0][0]
            frame = bytes([s._next_seq(), cid, 0x01, 0x00, 0x00])
            try:
                await s.client.write_gatt_char(B.CHAR_WRITE_UUID, frame, response=False)
            except Exception as exc:  # noqa: BLE001
                rows.append(f"cid={cid:3d}  WRITE-FAIL {exc}")
                await asyncio.sleep(args.delay)
                continue
            await asyncio.sleep(args.wait)
            got = []
            while s.rx:
                fs, _rest = B.drain(s.rx.pop(0))
                got.extend(fs)
            if got:
                for f in got:
                    line = f"cid={cid:3d}  {f.describe()}  payload={f.payload.hex(' ')}"
                    rows.append(line)
                    print(("  [命中] " if cid not in KNOWN else "  [已知] ") + line)
                hits.append((cid, "; ".join(f.describe() for f in got)))
            await asyncio.sleep(args.delay)

    ts = time.strftime("%Y%m%d_%H%M%S")
    p = EVID / f"evi_cid_sweep_{ts}.txt"
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"\n=== 扫了 {len(cids)} 个 cid，有回包 {len(hits)} 个 ===")
    for cid, d in hits:
        mark = "" if cid in KNOWN else "  <-- App 未使用"
        print(f"  cid={cid:3d}  {d}{mark}")
    print(f"证据: {p}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--addr", default=ADDR)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end", type=int, default=127)
    p.add_argument("--only", default="")
    p.add_argument("--delay", type=float, default=0.1)
    p.add_argument("--wait", type=float, default=0.25)
    p.add_argument("--scan-timeout", type=float, default=6.0)
    p.add_argument("--connect-timeout", type=float, default=20.0)
    p.add_argument("--gap", type=float, default=0.8)
    p.add_argument("--switch-wait", type=float, default=1.2)
    p.add_argument("--reconnect-delay", type=float, default=4.0)
    p.add_argument("--write-response", action="store_true")
    p.add_argument("--evidence-dir", default=str(EVID))
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
