#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探测：读出耳机的激活状态、开关状态和左右耳 UUID。

**这个脚本不写任何东西。** 它只发送查询命令（F39 的 LDAC_UUID 0x27），
用来在动手之前确认：
  1. 串口链路是否通
  2. 你的机型走的是不是 F39 协议
  3. 当前是否已经激活
  4. 左右耳 UUID（也就是未来 license 的后 16 字节）

用法：
    python examples/probe_headset.py --port COM5
    python examples/probe_headset.py --addr AA:BB:CC:DD:EE:FF

输出示例：
    激活状态  : 00                          (未激活)
    开关状态  : 01                          (LDAC 已开)
    左耳 UUID : 00112233445566778899AABBCCDDEEFF
    右耳 UUID : FFEEDDCCBBAA99887766554433221100

注意：探测结果只是参考。真机是否响应取决于固件是否实现了这些查询命令。
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import fiil_ldac as F  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="FIIL 耳机只读探测（不写入任何数据）")
    ap.add_argument("--port", help="串口名，如 COM5")
    ap.add_argument("--addr", help="蓝牙地址，如 AA:BB:CC:DD:EE:FF（Linux 下直连 RFCOMM）")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--timeout", type=float, default=1.0)
    args = ap.parse_args()

    if not args.port and not args.addr:
        ap.error("至少指定 --port 或 --addr 之一")

    print("[*] 只读模式：只会发送查询命令，不会写入任何 license")
    t = F.Transport(port=args.port, addr=args.addr, baud=args.baud, timeout=args.timeout)
    t.open()

    try:
        queries = [
            ("激活状态", F.F39_QUERY_ACTIVATION, {0x00: "未激活", 0x01: "已激活"}),
            ("开关状态", F.F39_QUERY_OPEN, {0x00: "LDAC 已关", 0x01: "LDAC 已开"}),
            ("左耳 UUID", F.F39_QUERY_LEFT_UUID, None),
            ("右耳 UUID", F.F39_QUERY_RIGHT_UUID, None),
        ]

        seq = 0
        for name, what, meanings in queries:
            frames, seq = F.f39_query_frames(what, seq)
            for f in frames:
                t.write(f)
            time.sleep(0.25)
            resp = F.collect_responses(t, timeout=1.5, idle=0.4)
            got = [r for r in resp if r[1] == F.F39_COMMAND_LDAC_UUID]

            if not got:
                print(f"  {name:9s} : <无响应>")
                continue

            payload = b"".join(r[5] for r in got)
            text = payload.hex().upper()
            if meanings and len(payload) >= 1:
                hint = meanings.get(payload[0], f"未知({payload[0]:#04x})")
                print(f"  {name:9s} : {text}   ({hint})")
            else:
                print(f"  {name:9s} : {text}")

        print()
        print("提示：把上面的「左耳 UUID,右耳 UUID」拼起来，就是 activateCode 的格式。")
        print("     例如：python src/fiil_ldac.py activate --port COM5 --code \"<左>,<右>\"")
    finally:
        t.close()

    return 0


if __name__ == "__main__":
    main()
