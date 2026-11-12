"""探测 FIIL 各候选域名的 DNS 解析情况（离线伪造 activateCode 的最后一条线索）。"""
import socket
import sys

sys.stdout.reconfigure(encoding="utf-8")
socket.setdefaulttimeout(3)

CANDS = [
    "newservice.fiil.com", "fiil.com", "ms.fiil.com", "store.fiil.com", "www.fiil.com",
    "fiil.cn", "www.fiil.cn", "api.fiil.com", "service.fiil.com", "newservice.fiil.cn",
    "fiil.com.cn", "www.fiil.com.cn", "api.fiil.cn", "ota.fiil.com", "cdn.fiil.com",
    "app.fiil.com", "m.fiil.com", "fiil.hk", "fiiltech.com", "www.fiiltech.com",
]

for d in CANDS:
    try:
        ips = sorted({r[4][0] for r in socket.getaddrinfo(d, None)})
        print(f"  OK   {d:26s} -> {','.join(ips)}")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL {d:26s} -> {type(exc).__name__}")
