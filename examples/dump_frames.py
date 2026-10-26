#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打印各协议的帧字节，不连接任何设备。

用途：在动手写耳机之前，先确认自己的机型走哪套协议。
把这些字节与你在 HCI Snoop Log 里抓到的对比，结构一致就说明协议对上了。

用法：
    python examples/dump_frames.py
    python examples/dump_frames.py --proto f39
    python examples/dump_frames.py --proto f43
    python examples/dump_frames.py --proto f048
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import fiil_ldac as F  # noqa: E402


def show(title, frames):
    print()
    print(f"=== {title} ===")
    for i, f in enumerate(frames):
        print(f"  [{i}] {len(f):2d} 字节  {f.hex(' ').upper()}")


def main():
    ap = argparse.ArgumentParser(description="打印 FIIL 各协议帧（不连接设备）")
    ap.add_argument("--proto", choices=["f39", "f43", "f048", "all"], default="all")
    args = ap.parse_args()

    left, right = F.build_zero_pair()

    if args.proto in ("f39", "all"):
        frames, _ = F.f39_activate_frames(left)
        show("F39 写左耳 license（全 0）", frames)
        frames, _ = F.f39_activate_frames(right)
        show("F39 写右耳 license（01 开头）", frames)
        frames, _ = F.f39_switch_frames(True)
        show("F39 开 LDAC", frames)
        frames, _ = F.f39_switch_frames(False)
        show("F39 关 LDAC", frames)
        for name, what in [
            ("查激活状态", F.F39_QUERY_ACTIVATION),
            ("查开关状态", F.F39_QUERY_OPEN),
            ("查左耳 UUID", F.F39_QUERY_LEFT_UUID),
            ("查右耳 UUID", F.F39_QUERY_RIGHT_UUID),
        ]:
            frames, _ = F.f39_query_frames(what)
            show(f"F39 {name} (0x{what:02X})", frames)

    if args.proto in ("f43", "all"):
        show("F43 写 license（左/右各一帧）", F.f43_activate_frames(left, right))
        show("F43 开 LDAC", [F.f43_switch_frame(True)])
        show("F43 关 LDAC", [F.f43_switch_frame(False)])

    if args.proto in ("f048", "all"):
        show("F048 写 license（左/右各一帧）", F.f048_activate_frames(left, right))

    print()
    print("说明：以上 license 内容全为 0，等效官方 CC Pro2 长按后门。")
    print("     真实写入时可改用 --code \"<左32hex>,<右32hex>\"。")
    print("     帧格式出处见 docs/PROTOCOL.md。")


if __name__ == "__main__":
    main()
