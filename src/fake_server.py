#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIIL+ 假服务器 / 离线激活服务
=============================

FIIL 的三个后端域名已全部 NXDOMAIN：
    newservice.fiil.com   ← LDAC 激活接口
    sapp.fengeek.com      ← 核心 API (core.fill / up.fill)
    ms.fiil.com           ← 语音服务

本脚本在本地起一个 HTTP 服务，模拟这些接口，让 FIIL+ App 以为服务器还活着，
从而走完「激活按钮 → 拿 activateCode → UnlockLDACActivity 写进耳机」的原始链路。

两种用法
--------
A) 手机直接改 hosts（需要 root / Magisk）
     把 newservice.fiil.com 指向本机 IP，然后：
         python src/fake_server.py --host 0.0.0.0 --port 80

B) 手机通过 HTTP 代理指向本机（无需 root）
     FIIL+ 用的是 OkHttp，默认会走系统代理。
         python src/fake_server.py --host 0.0.0.0 --port 8080
     手机 Wi-Fi 设置 → 代理 → 手动 → 填本机局域网 IP:8080
     （注意：App 只走 http，不走 https，所以不需要装证书）

接口对照（来自 jadx 反编译）
---------------------------
    GET  /app/headset/activation/info?deviceCode=<左hex>,<右hex>
         → {"code":"200","msg":"","data":"{\"activateCode\":\"...\",\"orderSn\":\"\"}"}
           activateCode 非空 → App 直接跳 UnlockLDACActivity(type=3) 写码
           activateCode 为空 + orderSn 空 → 跳购买页
           activateCode 为空 + orderSn 非空 → 跳订单页

    GET  /app/headset/sn/reg          设备注册（可返回成功）
    GET  /app/headset/activation/order 下单（可返回空单号）
    GET  /app/headset/activate         激活（备用）

    *  /core.fill  /up.fill  /actionLog.fill  /shop.fill
       /core.fiil  /headset/firmware/*  /app/headset/serieses
        全部返回一个通用成功壳，避免 App 卡在启动页。

默认行为
--------
    --mode zero    返回 17 字节全零 license（等效 CC Pro2 长按后门）
    --mode random  返回随机 16 字节（固件不校验内容，见 README）
    --mode echo    把请求里的 deviceCode 原样回填（最贴近真实服务器行为）
    --code "AA..,BB.."  直接指定固定的 activateCode

安全说明
--------
    只在局域网内监听，不要暴露到公网。
"""

import argparse
import json
import os
import random
import string
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# Windows 控制台默认 GBK，中文会乱码，强制 UTF-8 输出
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_CODE = None


def rand_hex(nbytes: int) -> str:
    return "".join(random.choice("0123456789ABCDEF") for _ in range(nbytes * 2))


def build_activate_code(mode: str, device_code: str, fixed: str = None) -> str:
    """返回 "左16字节hex,右16字节hex" 形式的 activateCode。"""
    if fixed:
        return fixed
    if mode == "zero":
        return ",".join(["00" * 16, "00" * 16])
    if mode == "echo":
        parts = [p for p in (device_code or "").split(",") if p]
        if len(parts) == 2 and len(parts[0]) == 32 and len(parts[1]) == 32:
            return device_code
        return ",".join(["00" * 16, "00" * 16])
    # random
    return ",".join([rand_hex(16), rand_hex(16)])


def ok_envelope(data, msg="") -> bytes:
    """App 期望的外层壳：{"code":"200","msg":"...","data":"<字符串化的 JSON>"}"""
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    body = {"code": "200", "msg": msg, "data": data}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "FIIL-FakeServer/1.0"
    protocol_version = "HTTP/1.1"

    # 静音默认日志
    def log_message(self, fmt, *args):
        if getattr(self.server, "verbose", False):
            sys.stderr.write("[%s] %s\n" % (self.address_string(), fmt % args))

    # ---- 通用 -------------------------------------------------------------
    def _send(self, body: bytes, ctype="application/json; charset=utf-8", status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, msg=""):
        self._send(ok_envelope(data, msg))

    # ---- GET --------------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        qs = parse_qs(u.query)
        mode = self.server.mode
        fixed = self.server.code

        # LDAC 激活信息 —— 核心接口
        if path == "/app/headset/activation/info":
            device_code = (qs.get("deviceCode") or [""])[0]
            code = build_activate_code(mode, device_code, fixed)
            print(f"[LDAC] deviceCode={device_code or '<空>'}")
            print(f"[LDAC] -> activateCode={code}")
            data = {"activateCode": code, "orderSn": ""}
            return self._send_json(data)

        # 设备注册
        if path == "/app/headset/sn/reg":
            return self._send_json({"result": 1})

        # 下单
        if path == "/app/headset/activation/order":
            return self._send_json({"orderSn": ""})

        # 激活（备用）
        if path == "/app/headset/activate":
            code = build_activate_code(mode, "", fixed)
            return self._send_json({"activateCode": code})

        # 固件升级：返回"已是最新"，避免 App 提示升级
        if path.startswith("/headset/firmware/upgrade"):
            return self._send_json({"version": "9.9.9", "updateFlag": 0,
                                    "downloadUrl": "", "description": "",
                                    "lastVersion": "9.9.9"})

        if path.startswith("/headset/firmware/update"):
            return self._send_json({"result": 1})

        # 型号列表
        if path == "/app/headset/serieses":
            return self._send_json([])

        # 其它 .fill / .fiil 接口：统一成功壳，避免卡启动
        if path.endswith(".fill") or path.endswith(".fiil") or path.startswith("/core") or path.startswith("/up"):
            return self._send_json({"result": 1, "list": [], "total": 0})

        # 兜底
        return self._send_json({"result": 1})

    # ---- POST -------------------------------------------------------------
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"

        if path.endswith(".fill") or path.endswith(".fiil") or path.startswith("/core") or path.startswith("/up"):
            return self._send_json({"result": 1})

        if path == "/app/headset/sn/reg":
            return self._send_json({"result": 1})

        return self._send_json({"result": 1})


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="FIIL+ 假服务器：让 App 在官方服务器下线后仍能走完 LDAC 激活流程",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    ap.add_argument("--port", type=int, default=8080, help="监听端口，默认 8080")
    ap.add_argument("--mode", choices=["zero", "random", "echo"], default="zero",
                    help="activateCode 生成方式，默认 zero")
    ap.add_argument("--code", help='固定 activateCode，"左32hex,右32hex"')
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.mode = args.mode
    srv.code = args.code
    srv.verbose = args.verbose

    print("=" * 66)
    print(" FIIL+ 假服务器已启动")
    print("=" * 66)
    print(f"  监听      : http://{args.host}:{args.port}")
    print(f"  license   : {args.mode}" + (f" (固定 {args.code})" if args.code else ""))
    print()
    print("  需要在手机端把下面这些域名指到本机：")
    for d in ("newservice.fiil.com", "sapp.fengeek.com", "ms.fiil.com", "fiil.cn"):
        print(f"      {d}")
    print()
    print("  方式 A（有 root）：改 /system/etc/hosts")
    print("  方式 B（无 root）：Wi-Fi → 代理 → 手动 → <本机IP>:%d" % args.port)
    print()
    print("  Ctrl+C 停止")
    print("=" * 66)

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] 已停止")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
