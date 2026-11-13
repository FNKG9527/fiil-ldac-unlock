"""脱敏规则与残留检查。

本仓库公开过一次真实研究，因此所有材料在入库前都做了一轮脱敏。
原始（未脱敏）的材料已不在仓库里，所以这个脚本现在的主要用途是：

1. 记录当时**替换了什么**（`RULES`），便于读者复核；
2. `--check` 模式扫描仓库，确认没有漏网的敏感模式。

用法：:

    python research/redact.py --check      # 只检查（默认）
    python research/redact.py --list       # 打印替换规则

保留（按作者判断）：耳机 MAC 地址、耳机状态数据 —— 前者是局域网内可观测标识，
后者是本研究结论的证据，脱敏后即失去验证价值。
替换：设备 UUID(= deviceCode)、本机绝对路径、adb 序列号、手机型号/名称、
      内网 IP、用户名。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (敏感模式, 替换后的占位符, 说明)
# 顺序不重要 —— 这些模式互不重叠。
RULES: list[tuple[str, str, str]] = [
    # --- 设备 UUID（= 激活服务器的 deviceCode，设备级唯一标识）---
    # 原值不再保留在这里，只留占位符本身以免误伤。
    (r"(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])", "<DEVICE_UUID_32HEX>", "32 位 hex 设备标识"),
    # --- 内网 IP ---
    (r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "192.0.2.10", "RFC1918 内网地址"),
    (r"\b192\.168\.\d{1,3}\.\d{1,3}\b", "192.0.2.10", "RFC1918 内网地址"),
    (r"\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b", "192.0.2.10", "RFC1918 内网地址"),
    # --- 本机绝对路径 ---
    (r"[A-Za-z]:\\\\?Users\\\\?[^\\\s\"']+", r"<HOME>", "Windows 用户目录"),
    (r"[A-Za-z]:\\\\?[^\\\s\"']*DeepSeek[^\\\s\"']*", r"<HOME>/work", "作者工作目录"),
    # --- adb 序列号（8 位小写 hex）---
    # 注意：BLE 的 16 位 UUID 会写成 0000fdb3 / 0000ff17 这种形态，
    # 与 adb 序列号撞形状，所以下面用 ALLOWLIST 与 NOISE 双重排除。
    (r"(?<![0-9a-f])\b[0-9a-f]{8}\b(?![0-9a-f])", "<ADB_SERIAL>", "adb 序列号形态"),
]

# 已知的正常内容，命中 RULES 也不报（避免把 UUID 当序列号）
NOISE = re.compile(
    r"""^(?:
        0000[0-9a-f]{4}          # BLE 16 位 UUID 短写：0000fdb3 / 0000ff17
      | [0-9a-f]{4}0000          # 反向短写
      | 00000000|ffffffff        # 全 0 / 全 f
    )$""",
    re.X,
)

SUFFIXES = {".log", ".txt", ".py", ".md", ".json", ".yml", ".yaml"}
SKIP_DIRS = {".git", "build", "dist", "__pycache__", ".ruff_cache", "_internal"}

# 允许出现在仓库里的内容（避免误报）
ALLOWLIST = [
    # 已经脱敏过的占位符
    "AA BB CC DD EE FF 00 11 22 33 44 55 66 77 88",
    "aabbccddeeff00112233445566778899",
    # 16 进制示例不当作设备标识
    "0123456789012345",
    "deadbeef",
]


def iter_files(base: Path):
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def check(base: Path) -> int:
    findings = 0
    for p in iter_files(base):
        try:
            text = p.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            continue
        rel = p.relative_to(ROOT)
        for pat, _repl, desc in RULES:
            for m in re.finditer(pat, text):
                frag = m.group(0)
                if NOISE.match(frag):
                    continue
                if any(a.lower() in frag.lower() for a in ALLOWLIST):
                    continue
                line = text.count("\n", 0, m.start()) + 1
                print(f"[?] {rel}:{line}  {desc}  →  {frag!r}")
                findings += 1
    print(f"\n[=] 检查完成，可疑项 {findings} 处")
    return 0 if findings == 0 else 1


def show_rules() -> int:
    print("替换规则：\n")
    print(f"{'说明':<28} 替换为")
    print("-" * 60)
    for _pat, repl, desc in RULES:
        print(f"{desc:<28} {repl}")
    print("\n保留：耳机 MAC 地址、耳机状态数据（理由见文件头）")
    return 0


def main() -> int:
    if "--list" in sys.argv:
        return show_rules()
    base = ROOT / "research"
    return check(base)


if __name__ == "__main__":
    raise SystemExit(main())
