"""读 Key Max 的左右耳 UUID（cid=39 cmd=138/139）与 PID，用于离线构造 license。"""
from __future__ import annotations
import asyncio, datetime as dt, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".."))
from bleak import BleakClient, BleakScanner
from fiil_protocol import CHAR_NOTIFY_UUID, CHAR_WRITE_UUID, build_frame, drain

ADDR = "B0:F1:A3:A8:7A:C8"
rx: list[bytes] = []
seq = 0
lines: list[str] = []

def log(s: str) -> None:
    print(s); lines.append(s)

def fmt(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)

def nseq() -> int:
    global seq
    v = seq & 0x0F; seq = (seq + 1) & 0x0F; return v

def on_notify(_c, data: bytearray) -> None:
    rx.append(bytes(data))

async def send(client, label, cid, cmd, payload=b"", wait=0.8):
    f = build_frame(cid, cmd, payload, nseq())
    log(f"[TX] {label:<24} {fmt(f)}")
    await client.write_gatt_char(CHAR_WRITE_UUID, f, response=False)
    await asyncio.sleep(wait)
    out = []
    while rx:
        for fr in drain(rx.pop(0))[0]:
            log(f"     [RX] {fmt(fr.raw):<46} {fr.describe():<32} payload={fmt(fr.payload)}")
            out.append(fr)
    if not out:
        log("     [RX] (无响应)")
    return out

async def main() -> int:
    log("=" * 76)
    log(f"# Key Max UUID/PID 读取  {dt.datetime.now():%Y-%m-%dT%H:%M:%S}")
    log("=" * 76)
    dev = None
    for d in await BleakScanner.discover(timeout=8.0):
        if d.address.upper() == ADDR:
            dev = d; break
    if dev is None:
        log("[!] 未找到耳机"); return 1
    log(f"[+] {dev.address} rssi={getattr(dev, "rssi", "?")} name={dev.name!r}")
    async with BleakClient(dev, timeout=20.0) as c:
        await c.start_notify(CHAR_NOTIFY_UUID, on_notify)
        await send(c, "setUnlock(握手)", 39, 0xFF, bytes([0x02, 0x34]), 0.9)
        await send(c, "getLeftUUID(138)", 39, 138, wait=1.0)
        await send(c, "getRightUUID(139)", 39, 139, wait=1.0)
        await send(c, "getPID(132)", 39, 132)
        await send(c, "getVersion(2)", 39, 2)
        try:
            await c.stop_notify(CHAR_NOTIFY_UUID)
        except Exception:
            pass
    p = Path(__file__).resolve().parent.parent / "research" / f"evi_uuid_{dt.datetime.now():%Y%m%d_%H%M%S}.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    log(f"[+] 证据 {p}")
    return 0

raise SystemExit(asyncio.run(main()))
