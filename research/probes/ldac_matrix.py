"""A2DP 编解码协商 × 耳机侧 LDAC 开关（143）对照实验。

目的：确认手机侧 A2DP 实际协商出的 codec 是否受耳机侧 142/143 影响。
做法：脚本只负责来回切 143，编解码结果由外部 adb 在同一时刻抓取。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import fiil_ble as B  # noqa: E402

ADDR = "B0:F1:A3:A8:7A:C8"


def make_args() -> object:
    class A:
        addr = ADDR
        scan_timeout = 20.0
        connect_timeout = 20.0
        gap = 0.8
        switch_wait = 1.2
        reconnect_delay = 4.0
        write_response = False
        evidence_dir = str(REPO / "docs" / "evidence")

    return A()


async def read_state() -> dict:
    args = make_args()
    async with B.Session(ADDR, args, tag="matrix") as s:
        await s.handshake()
        return await B.query_all(s)


def _byte(payload: bytes) -> str:
    return f"{payload[0]:02X}" if payload else "--"


async def set_switch(on: bool) -> None:
    """复刻官方顺序：先关低延迟，再切 LDAC。"""
    args = make_args()
    try:
        async with B.Session(ADDR, args, tag="matrix_switch") as s:
            await s.handshake()
            await s.send("setLowDelay(0)", B.CID_SET_LATENCY, 0, bytes([0]), wait=0.6)
            await s.send("setLdacSwitch", B.CID_SET_PARAM, B.SET_LDAC_SWITCH,
                         bytes([1 if on else 0]), wait=1.0)
    except Exception as e:  # 切 LDAC 会断 A2DP，属预期
        print(f"    (链路重建: {type(e).__name__})")


def show(tag: str, st: dict) -> None:
    print(
        f"[*] {tag}  142={_byte(st.get('LDAC已解锁', b''))}"
        f"  143={_byte(st.get('LDAC开关', b''))}"
        f"  144={_byte(st.get('当前编解码', b''))}"
    )


def main() -> int:
    want = (sys.argv[1] if len(sys.argv) > 1 else "on").lower()
    on = want == "on"

    print(f"[*] 目标：把耳机侧 143 切到 {'开' if on else '关'}")
    show("切换前", asyncio.run(read_state()))

    asyncio.run(set_switch(on))
    time.sleep(6.0)

    show("切换后", asyncio.run(read_state()))
    print()
    print("[!] 现在立刻去手机侧抓 A2DP 协商结果（脚本不会替你判断）：")
    print("    adb shell dumpsys bluetooth_manager | grep -A2 'mCodecConfig'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
