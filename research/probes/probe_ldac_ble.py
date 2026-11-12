"""FIIL Key Max —— LDAC 激活链路 BLE 实机探测（只读阶段优先）

目的（对应本次目标）：验证 Mate 协议里 cid=1 cmdId=12（setActivationLdac）
在 FIIL Key Max（earType 46）上是否可用，以及 17 字节全零 license 是否被接受。

逆向依据：
  com/fengeek/main/i/d/c.java:287-302   setActivationLdac -> cid=1, cmdId=12, buffer=license
  com/fengeek/main/f046/fragment/F046HomeFragment.java:93-96
       取消激活 = setActivationLdac(new byte[17])
  com/fengeek/main/i/d/c.java:381-385  setLdacSwitch   -> cid=1, cmdId=13, buffer={0/1}
  com/fengeek/main/i/d/c.java:117-120  getLdacUnlockStatus -> cid=39, cmdId=142
  com/fengeek/main/i/d/c.java:101-104  getLdacSwitchStatus -> cid=39, cmdId=143
  com/fengeek/main/i/d/c.java:53-56    getCodecStatus      -> cid=39, cmdId=144

用法：
  python probe_ldac_ble.py status            # 只读：握手 + 读 142/143/144
  python probe_ldac_ble.py cancel            # 写 17 字节全零（= 官方“取消激活”原语）
  python probe_ldac_ble.py activate HEX      # 写 17 字节自定义 license（首字节 0 = 左耳）
  python probe_ldac_ble.py switch on|off     # 切 LDAC 开关
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".."))

from bleak import BleakClient, BleakScanner  # noqa: E402

from fiil_protocol import (  # noqa: E402
    CHAR_NOTIFY_UUID,
    CHAR_WRITE_UUID,
    build_frame,
    drain,
)

ADDR = "B0:F1:A3:A8:7A:C8"
OUT = Path(__file__).parent


def fmt(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


class Session:
    def __init__(self) -> None:
        self.rx: list[bytes] = []
        self.lines: list[str] = []
        self.seq = 0

    def log(self, s: str) -> None:
        print(s)
        self.lines.append(s)

    def nseq(self) -> int:
        v = self.seq & 0x0F
        self.seq = (self.seq + 1) & 0x0F
        return v

    def on_notify(self, _ch, data: bytearray) -> None:
        self.rx.append(bytes(data))

    async def send(self, client, label: str, cid: int, cmd: int, payload: bytes = b"",
                   wait: float = 0.85) -> list:
        frame = build_frame(cid, cmd, payload, self.nseq())
        self.log(f"[TX] {label:<26} {fmt(frame)}")
        await client.write_gatt_char(CHAR_WRITE_UUID, frame, response=False)
        await asyncio.sleep(wait)
        frames = []
        while self.rx:
            for f in drain(self.rx.pop(0))[0]:
                self.log(f"     [RX] {fmt(f.raw):<44} {f.describe()}  payload={fmt(f.payload)}")
                frames.append(f)
        if not frames:
            self.log("     [RX] (无响应)")
        return frames

    def save(self, tag: str) -> Path:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        p = OUT / f"evi_ldac_{tag}_{ts}.txt"
        p.write_text("\n".join(self.lines), encoding="utf-8")
        return p


async def resolve_target():
    devs = await BleakScanner.discover(timeout=10.0)
    for d in devs:
        if d.address.upper() == ADDR:
            return d
    for d in devs:
        if "FIIL" in (d.name or "").upper():
            return d
    return None


async def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    s = Session()
    s.log("=" * 78)
    s.log(f"# FIIL LDAC BLE 探测  action={action}  {dt.datetime.now():%Y-%m-%dT%H:%M:%S}")
    s.log("=" * 78)

    target = await resolve_target()
    if target is None:
        s.log("[!] 未扫到耳机（可能被经典蓝牙占用，先断开音频再试）")
        s.save("nofind")
        return 1
    s.log(f"[+] 目标 {target.address} name={target.name!r}")

    async with BleakClient(target, timeout=20.0) as client:
        s.log(f"[+] 已连接 mtu={getattr(client, 'mtu_size', '?')}")
        try:
            await client.start_notify(CHAR_NOTIFY_UUID, s.on_notify)
        except Exception as exc:  # noqa: BLE001
            s.log(f"[!] start_notify 失败 {type(exc).__name__}: {exc}")
            s.save("notifyfail")
            return 1

        # 1) 握手：不发这一帧耳机对所有查询静默
        await s.send(client, "setUnlock(握手)", 39, 0xFF, bytes([0x02, 0x34]), wait=0.9)

        # 2) 基线状态
        s.log("--- 基线状态 ---")
        await s.send(client, "getDeviceName(3)", 39, 3)
        await s.send(client, "getLdacUnlock(142)", 39, 142)
        await s.send(client, "getLdacSwitch(143)", 39, 143)
        await s.send(client, "getCodec(144)", 39, 144)

        if action == "status":
            pass
        elif action == "cancel":
            s.log("--- 写 setActivationLdac(17B 全零 = 官方取消激活原语) ---")
            await s.send(client, "setActivationLdac(0*17)", 1, 12, bytes(17), wait=1.2)
            s.log("--- 写后复读 ---")
            await s.send(client, "getLdacUnlock(142)", 39, 142)
            await s.send(client, "getLdacSwitch(143)", 39, 143)
            await s.send(client, "getCodec(144)", 39, 144)
        elif action == "activate":
            hexstr = sys.argv[2].replace(" ", "")
            payload = bytes.fromhex(hexstr)
            s.log(f"--- 写 setActivationLdac({len(payload)}B) {hexstr.upper()} ---")
            await s.send(client, "setActivationLdac(custom)", 1, 12, payload, wait=1.2)
            await s.send(client, "getLdacUnlock(142)", 39, 142)
            await s.send(client, "getLdacSwitch(143)", 39, 143)
            await s.send(client, "getCodec(144)", 39, 144)
        elif action == "switch":
            want = sys.argv[2].lower() in ("on", "1", "true")
            if want:
                s.log("--- 先关低延迟（官方顺序：低延迟与 LDAC 互斥）---")
                await s.send(client, "setLowDelay(0)", 37, 0, bytes([0]), wait=0.6)
            s.log(f"--- setLdacSwitch({1 if want else 0}) ---")
            await s.send(client, "setLdacSwitch", 1, 13, bytes([1 if want else 0]), wait=1.2)
            await s.send(client, "getLdacSwitch(143)", 39, 143)
            await s.send(client, "getCodec(144)", 39, 144)

        try:
            await client.stop_notify(CHAR_NOTIFY_UUID)
        except Exception:  # noqa: BLE001
            pass
        s.log("[+] 完成")

    p = s.save(action)
    s.log(f"[+] 证据已存 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
