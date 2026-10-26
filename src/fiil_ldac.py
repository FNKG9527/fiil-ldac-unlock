#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIIL+ LDAC 离线激活 —— PC 直写工具
==================================

不依赖 FIIL 服务器，直接把 LDAC license 写进耳机。

支持三套帧格式（对应不同机型固件）：
    f39   Bluetrum 协议（CC Pro2 / F039 系列）         command=0x01 / 0x27
    f43   F43 SDP 协议（F043 / F048 等）               commandId=2308/2311
    f048  F048 SDP 协议（F048 type=3 路径）            classifyId=1, cmdId=12

用法：
    python src/fiil_ldac.py list                       列出可用串口
    python src/fiil_ldac.py frames  --proto f39        只看帧（不连接，安全）
    python src/fiil_ldac.py read    --port COM5        读激活状态 / 开关状态 / 左右耳 UUID
    python src/fiil_ldac.py backup  --port COM5        备份当前 license 到 backup/
    python src/fiil_ldac.py activate --port COM5 --code "AA..,BB.."
    python src/fiil_ldac.py activate --port COM5 --zeros          # 等效 CC Pro2 后门
    python src/fiil_ldac.py switch  --port COM5 --on

前置条件（重要）：
    1. 耳机已与 Windows 配对（设置 → 蓝牙和其他设备 → 添加设备）
    2. 配对后 Windows 会自动创建一个"传出"串口，通常在 设备管理器 → 端口(COM 和 LPT)
       名字类似 "FIIL CC Pro2 'Dev B'" / "Standard Serial over Bluetooth link (COM5)"
    3. 手机 App 和手机蓝牙都关掉，否则耳机可能只保持和手机的连接

为什么用串口而不是 BLE：
    FIIL 的私有通道走的是 SPP/RFCOMM（UUID d52b47bc-2dea-42c4-b26d-20252fceeeb3），
    不是 BLE GATT。Windows 配对后会把该 SPP 服务映射成一个虚拟 COM 口，
    pyserial 直接读写即可，无需自己实现 RFCOMM 通道发现。

风险提示：
    * 写入前请先 backup，写坏了不保证能恢复
    * 固件升级可能清空激活状态
    * license 内容固件不校验（见 README 证据），但未来固件可能加校验
"""

import argparse
import os
import sys
import time
from datetime import datetime

# Windows 控制台默认 GBK，中文和 ─ 之类的符号会乱码，强制 UTF-8 输出
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ----------------------------------------------------------------------------
# 协议常量（全部来自 jadx 反编译结果）
# ----------------------------------------------------------------------------

# F39 / Bluetrum
F39_COMMAND_APP_SETTING = 0x01   # com.bluetrum.devicemanager.f39.request.F39AppSettingRequest -> super((byte)1)
F39_COMMAND_LDAC_UUID = 0x27     # F39LdacUuidRequest -> super((byte)39)
F39_TYPE_REQUEST = 0x01          # Request.f16329c = 1
F39_TYPE_RESPONSE = 0x02         # Command.COMMAND_TYPE_RESPONSE
F39_TYPE_NOTIFICATION = 0x03
F39_MAX_PAYLOAD = 15             # com.bluetrum.devicemanager.z: this(new a0(15))

F39_SETTING_ACTIVATE_LDAC = 12   # F39AppSettingRequest.SETTING_TYPE_ACTIVATE_LDAC
F39_SETTING_LDAC = 13            # F39AppSettingRequest.SETTING_TYPE_LDAC

F39_QUERY_ACTIVATION = 0x8E      # LDAC_ACTIVATION_STATE = -114
F39_QUERY_OPEN = 0x8F            # LDAC_OPEN_STATE       = -113
F39_QUERY_LEFT_UUID = 0x8A       # LDAC_LEFT_UUID        = -118
F39_QUERY_RIGHT_UUID = 0x8B      # LDAC_RIGHT_UUID       = -117

# F43 / F048 (SDP over same SPP UUID)
SDP_HEAD = bytes([0xFF, 0x01, 0x00])   # SOF, version, flags
SDP_MAGIC = bytes([0x02, 0x34])        # 0x02 = ?, 0x34 = 52

F43_CMD_CONFIG_EXTEND = 2311     # com.fengeek.utils.l1.v0.i.f33100i
F43_CMD_EXECUTE_EXTEND = 2308    # com.fengeek.utils.l1.v0.i.f33097f
F43_PROTO_LEFT_LDAC = 4          # d.setLeftLDAC -> new d(4, 40)
F43_PROTO_RIGHT_LDAC = 4         # d.setRightLDAC -> new d(4, 46)
F43_PROTO_LDAC_SWITCH = 4        # f.setLdac -> new f(4, 30)

F048_CLASSIFY_ID = 1             # com.fengeek.main.i.d.e.setActivationLdac
F048_CMD_ACTIVATE = 12

LICENSE_LEN = 17                 # 17 字节 = 1 字节耳别 + 16 字节 UUID

# ----------------------------------------------------------------------------
# 帧构造
# ----------------------------------------------------------------------------


def f39_frames(command: int, payload: bytes, seq: int = 0, max_payload: int = F39_MAX_PAYLOAD):
    """按 com.bluetrum.devicemanager.z.b() 组帧。

    帧头 5 字节：
        [0] seq            0-15 循环
        [1] command        命令字
        [2] commandType    1=request 2=response 3=notification
        [3] (total-1)<<4 | index
        [4] 本包 payload 长度
    """
    if not payload:
        return [bytes([seq & 0x0F, command, F39_TYPE_REQUEST, 0x00, 0x00])], (seq + 1) & 0x0F

    total = (len(payload) + max_payload - 1) // max_payload
    out = []
    s = seq & 0x0F
    for idx in range(total):
        chunk = payload[idx * max_payload:(idx + 1) * max_payload]
        head = bytes([s, command, F39_TYPE_REQUEST, (((total - 1) << 4) & 0xFF) | (idx & 0x0F), len(chunk)])
        out.append(head + chunk)
        s = (s + 1) & 0x0F
    return out, s


def f39_activate_frames(license_bytes: bytes, seq: int = 0):
    """写 license：payload = [0x0C, 0x11] + 17 字节"""
    assert len(license_bytes) == LICENSE_LEN, f"license 必须是 {LICENSE_LEN} 字节"
    payload = bytes([F39_SETTING_ACTIVATE_LDAC, LICENSE_LEN]) + license_bytes
    return f39_frames(F39_COMMAND_APP_SETTING, payload, seq)


def f39_switch_frames(on: bool, seq: int = 0):
    payload = bytes([F39_SETTING_LDAC, 0x01, 0x01 if on else 0x00])
    return f39_frames(F39_COMMAND_APP_SETTING, payload, seq)


def f39_query_frames(what: int, seq: int = 0):
    return f39_frames(F39_COMMAND_LDAC_UUID, bytes([what & 0xFF]), seq)


def sdp_frame(command_id: int, sub_id: int, values: bytes) -> bytes:
    """SDP 帧（com.fengeek.utils.l1.v0.a.getPayload 与 com.fengeek.main.i.b.write 同构）：

        FF 01 00 | (len(values)+2) | 02 34 | cmdHi cmdLo | subId | len(values) | values
    """
    n = len(values)
    return (SDP_HEAD
            + bytes([(n + 2) & 0xFF])
            + SDP_MAGIC
            + bytes([(command_id >> 8) & 0xFF, command_id & 0xFF])
            + bytes([sub_id & 0xFF, n & 0xFF])
            + values)


def f43_activate_frames(left: bytes, right: bytes):
    """F43：左耳 commandId=2311 subId=4；右耳 commandId=2311 subId=4（靠 values[0] 区分）"""
    return [sdp_frame(F43_CMD_CONFIG_EXTEND, F43_PROTO_LEFT_LDAC, left),
            sdp_frame(F43_CMD_CONFIG_EXTEND, F43_PROTO_RIGHT_LDAC, right)]


def f43_switch_frame(on: bool):
    return sdp_frame(F43_CMD_EXECUTE_EXTEND, F43_PROTO_LDAC_SWITCH, bytes([1 if on else 0]))


def f048_activate_frames(left: bytes, right: bytes):
    """F048 type=3：classifyId=1, cmdId=12，左右各发一次"""
    return [sdp_frame(F048_CLASSIFY_ID, F048_CMD_ACTIVATE, left),
            sdp_frame(F048_CLASSIFY_ID, F048_CMD_ACTIVATE, right)]


# ----------------------------------------------------------------------------
# license 构造
# ----------------------------------------------------------------------------


def build_license_pair(code: str):
    """activateCode 形如 "16字节hex,16字节hex"，左耳前缀 0x00，右耳前缀 0x01。"""
    parts = [p.strip() for p in code.replace(" ", "").split(",") if p.strip()]
    if len(parts) != 2:
        raise ValueError("activateCode 必须是用英文逗号分隔的两段 hex（左耳,右耳）")
    left16 = bytes.fromhex(parts[0])
    right16 = bytes.fromhex(parts[1])
    if len(left16) != 16 or len(right16) != 16:
        raise ValueError(f"每段必须是 16 字节（32 个 hex 字符），当前 {len(left16)} / {len(right16)}")
    return bytes([0x00]) + left16, bytes([0x01]) + right16


def build_zero_pair():
    """CC Pro2 后门等效：左耳全 0，右耳首字节 01 其余全 0。"""
    return bytes(LICENSE_LEN), bytes([0x01]) + bytes(16)


# ----------------------------------------------------------------------------
# 传输层
# ----------------------------------------------------------------------------


class Transport:
    """统一串口 / 直连 RFCOMM 两种后端。"""

    def __init__(self, port=None, addr=None, baud=115200, timeout=1.0):
        self.port = port
        self.addr = addr
        self.baud = baud
        self.timeout = timeout
        self._ser = None
        self._sock = None

    def open(self):
        if self.port:
            import serial  # pyserial
            self._ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            time.sleep(0.3)
            self._ser.reset_input_buffer()
        else:
            import socket
            self._sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            self._sock.settimeout(self.timeout)
            # Windows 的 RFCOMM connect 需要 (bdaddr, channel)，channel 由 SDP 决定；
            # 这里从 1 开始试，FIIL 常见落在 1-30。
            last = None
            for ch in range(1, 31):
                try:
                    self._sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                    self._sock.settimeout(1.5)
                    self._sock.connect((self.addr, ch))
                    print(f"[+] RFCOMM 已连接 {self.addr} channel={ch}")
                    return self
                except Exception as e:  # noqa: BLE001
                    last = e
                    try:
                        self._sock.close()
                    except Exception:  # noqa: BLE001
                        pass
            raise RuntimeError(f"RFCOMM 连接失败（1-30 全部失败），最后错误：{last}")
        return self

    def write(self, data: bytes):
        if self._ser:
            self._ser.write(data)
            self._ser.flush()
        else:
            self._sock.sendall(data)

    def read(self, n=4096, timeout=None):
        if self._ser:
            self._ser.timeout = timeout if timeout is not None else self.timeout
            return self._ser.read(n)
        if timeout is not None:
            self._sock.settimeout(timeout)
        try:
            return self._sock.recv(n)
        except Exception:  # noqa: BLE001
            return b""

    def close(self):
        try:
            if self._ser:
                self._ser.close()
            if self._sock:
                self._sock.close()
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------------------
# F39 响应解析
# ----------------------------------------------------------------------------


class F39Reader:
    """按 com.bluetrum.devicemanager.c0 的逻辑重组响应帧。"""

    def __init__(self):
        self.buf = b""

    def feed(self, data: bytes):
        self.buf += data

    def parse(self):
        """返回 [(command, command_type, payload), ...]"""
        out = []
        while len(self.buf) >= 5:
            seq = self.buf[0]
            cmd = self.buf[1]
            ctype = self.buf[2]
            total = ((self.buf[3] >> 4) & 0x0F) + 1
            index = self.buf[3] & 0x0F
            ln = self.buf[4]
            if len(self.buf) < 5 + ln:
                break
            payload = self.buf[5:5 + ln]
            self.buf = self.buf[5 + ln:]
            out.append((seq, cmd, ctype, total, index, payload))
        return out


def _hex(b: bytes) -> str:
    return b.hex(" ").upper()


def collect_responses(t: Transport, expect_cmd=None, timeout=2.5, idle=0.6):
    """收一段时间的数据，返回解析出的响应列表。"""
    reader = F39Reader()
    frames = []
    deadline = time.time() + timeout
    last_data = time.time()
    while time.time() < deadline:
        chunk = t.read(4096, timeout=0.3)
        if chunk:
            reader.feed(chunk)
            last_data = time.time()
            frames.extend(reader.parse())
        elif time.time() - last_data > idle:
            break
    return [f for f in frames if f[2] in (F39_TYPE_RESPONSE, F39_TYPE_NOTIFICATION)]


# ----------------------------------------------------------------------------
# 命令实现
# ----------------------------------------------------------------------------


def cmd_list(_args):
    try:
        from serial.tools import list_ports
    except ImportError:
        print("未安装 pyserial：pip install pyserial")
        return 1
    ports = list(list_ports.comports())
    if not ports:
        print("没有找到任何串口。请先配对耳机，Windows 会自动创建传出 COM 口。")
        return 1
    for p in ports:
        print(f"{p.device:10s}  {p.description}")
        if "Bluetooth" in (p.description or "") or "FIIL" in (p.description or ""):
            print("            ^^^ 很可能是耳机")
    return 0


def _print_frames(title, frames):
    print(f"\n=== {title} ===")
    for i, f in enumerate(frames):
        print(f"  [{i}] {len(f):2d} 字节  {_hex(f)}")


def cmd_frames(args):
    if args.proto == "f39":
        left, right = build_zero_pair()
        a, _ = f39_activate_frames(left, 0)
        _print_frames("F39 写左耳 license（全 0）", a)
        b, _ = f39_activate_frames(right, len(a) & 0x0F)
        _print_frames("F39 写右耳 license（01 开头）", b)
        s, _ = f39_switch_frames(True, (len(a) + len(b)) & 0x0F)
        _print_frames("F39 打开 LDAC", s)
        q, _ = f39_query_frames(F39_QUERY_ACTIVATION)
        _print_frames("F39 查询激活状态", q)
    elif args.proto == "f43":
        left, right = build_zero_pair()
        _print_frames("F43 写左右耳 license", f43_activate_frames(left, right))
        _print_frames("F43 打开 LDAC", [f43_switch_frame(True)])
    else:
        left, right = build_zero_pair()
        _print_frames("F048 写左右耳 license", f048_activate_frames(left, right))
    return 0


def _open(args):
    t = Transport(port=args.port, addr=args.addr, baud=args.baud, timeout=args.timeout)
    t.open()
    return t


def cmd_read(args):
    t = _open(args)
    try:
        if args.proto != "f39":
            print("read 目前只实现了 F39（Bluetrum）通道的查询命令。")
            return 2
        queries = [
            ("激活状态", F39_QUERY_ACTIVATION),
            ("开关状态", F39_QUERY_OPEN),
            ("左耳 UUID", F39_QUERY_LEFT_UUID),
            ("右耳 UUID", F39_QUERY_RIGHT_UUID),
        ]
        seq = 0
        for name, q in queries:
            frames, seq = f39_query_frames(q, seq)
            for f in frames:
                t.write(f)
            time.sleep(0.25)
            resp = collect_responses(t, timeout=1.5, idle=0.4)
            got = [r for r in resp if r[1] == F39_COMMAND_LDAC_UUID]
            if not got:
                print(f"  {name:8s} : <无响应>")
            else:
                payload = b"".join(r[5] for r in got)
                print(f"  {name:8s} : {_hex(payload)}   ({payload.hex()})")
        return 0
    finally:
        t.close()


def cmd_backup(args):
    t = _open(args)
    os.makedirs("backup", exist_ok=True)
    try:
        seq = 0
        got = {}
        for name, q in (("left", F39_QUERY_LEFT_UUID), ("right", F39_QUERY_RIGHT_UUID)):
            frames, seq = f39_query_frames(q, seq)
            for f in frames:
                t.write(f)
            time.sleep(0.25)
            resp = collect_responses(t, timeout=1.5, idle=0.4)
            payload = b"".join(r[5] for r in resp if r[1] == F39_COMMAND_LDAC_UUID)
            got[name] = payload
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join("backup", f"license_{stamp}.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# FIIL LDAC license 备份 {stamp}\n")
            for k, v in got.items():
                fh.write(f"{k}={v.hex()}\n")
        print(f"[+] 已备份到 {path}")
        for k, v in got.items():
            print(f"    {k:5s} = {v.hex()}  ({len(v)} 字节)")
        return 0
    finally:
        t.close()


def cmd_activate(args):
    if args.zeros:
        left, right = build_zero_pair()
        src = "全零 license（等效 CC Pro2 长按后门）"
    else:
        if not args.code:
            print("必须给 --code 或 --zeros")
            return 2
        left, right = build_license_pair(args.code)
        src = "自定义 activateCode"

    print(f"[*] 协议      : {args.proto}")
    print(f"[*] 来源      : {src}")
    print(f"[*] 左耳      : {_hex(left)}")
    print(f"[*] 右耳      : {_hex(right)}")

    if args.proto == "f39":
        lf, seq = f39_activate_frames(left, 0)
        rf, seq = f39_activate_frames(right, seq)
        sw, seq = f39_switch_frames(True, seq)
        plan = [("左耳 license", lf), ("右耳 license", rf), ("打开 LDAC", sw)]
    elif args.proto == "f43":
        plan = [("左右耳 license", f43_activate_frames(left, right)),
                ("打开 LDAC", [f43_switch_frame(True)])]
    else:
        plan = [("左右耳 license", f048_activate_frames(left, right))]

    for title, frames in plan:
        _print_frames(title, frames)

    if args.dry_run:
        print("\n[=] --dry-run，未发送。")
        return 0
    if not args.yes:
        print("\n[!] 这会真的写进耳机。确认无误请加 --yes 重新执行。")
        return 1

    t = _open(args)
    try:
        for title, frames in plan:
            for f in frames:
                t.write(f)
                time.sleep(args.gap)
            print(f"[+] 已发送：{title}")
        time.sleep(0.5)
        resp = collect_responses(t, timeout=2.0)
        if resp:
            print("\n[响应]")
            for seq, cmd, ctype, total, index, payload in resp:
                print(f"  cmd=0x{cmd:02X} type={ctype} [{index+1}/{total}] {_hex(payload)}")
        else:
            print("\n[!] 没收到响应（耳机可能不回 ACK，也可能是没写进去）")
            print("    建议立刻跑一次 read 确认激活状态。")
        return 0
    finally:
        t.close()


def cmd_switch(args):
    t = _open(args)
    try:
        if args.proto == "f39":
            frames, _ = f39_switch_frames(args.on, 0)
        elif args.proto == "f43":
            frames = [f43_switch_frame(args.on)]
        else:
            print("F048 通道的 LDAC 开关命令号未在源码中定位，请用 f39/f43。")
            return 2
        for f in frames:
            t.write(f)
        print(f"[+] 已发送 LDAC {'开' if args.on else '关'}")
        return 0
    finally:
        t.close()


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


_GLOBAL_FLAGS = ("--proto", "--port", "--addr", "--baud", "--timeout", "--gap")
_SUBCOMMANDS = ("list", "frames", "read", "backup", "activate", "switch")


def _normalize_argv(argv):
    """允许把全局参数写在子命令后面（python src/fiil_ldac.py frames --proto f39）。

    argparse 的全局参数默认只能出现在子命令之前，这里把它们挪到前面去。
    """
    out, tail = [], []
    i = 0
    while i < len(argv):
        a = argv[i]
        hit = next((g for g in _GLOBAL_FLAGS if a == g or a.startswith(g + "=")), None)
        if hit:
            tail.append(a)
            if a == hit and i + 1 < len(argv):
                tail.append(argv[i + 1])
                i += 2
                continue
        else:
            out.append(a)
        i += 1
    return tail + out


def main(argv=None):
    argv = _normalize_argv(list(sys.argv[1:] if argv is None else argv))
    ap = argparse.ArgumentParser(
        description="FIIL+ LDAC 离线激活工具（协议直写，不依赖服务器）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--proto", choices=["f39", "f43", "f048"], default="f39",
                    help="帧格式，默认 f39（CC Pro2 / F039 系列）")
    ap.add_argument("--port", help="串口，如 COM5（Windows 配对后自动生成）")
    ap.add_argument("--addr", help="蓝牙地址，如 AA:BB:CC:DD:EE:FF（直连 RFCOMM，不推荐）")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--timeout", type=float, default=1.0)
    ap.add_argument("--gap", type=float, default=0.15, help="帧间间隔秒，默认 0.15")

    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出串口").set_defaults(func=cmd_list)
    sub.add_parser("frames", help="只打印帧，不连接").set_defaults(func=cmd_frames)
    sub.add_parser("read", help="读状态和 UUID").set_defaults(func=cmd_read)
    sub.add_parser("backup", help="备份 license").set_defaults(func=cmd_backup)

    p = sub.add_parser("activate", help="写入 license")
    p.add_argument("--code", help='activateCode，"左16字节hex,右16字节hex"')
    p.add_argument("--zeros", action="store_true", help="写全零 license（等效 CC Pro2 后门）")
    p.add_argument("--dry-run", action="store_true", help="只打印帧")
    p.add_argument("--yes", action="store_true", help="确认真的写入")
    p.set_defaults(func=cmd_activate)

    p = sub.add_parser("switch", help="开/关 LDAC")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--on", action="store_true")
    g.add_argument("--off", action="store_true")
    p.set_defaults(func=cmd_switch)

    args = ap.parse_args(argv)
    if hasattr(args, "off") and args.off:
        args.on = False
    if not args.port and not args.addr and args.cmd in ("read", "backup", "activate", "switch"):
        print("必须给 --port COMx 或 --addr AA:BB:...")
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
