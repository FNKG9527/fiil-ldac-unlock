"""脱敏脚本：把研究材料里的敏感信息替换成占位符。

处理对象：research/logs/ 下的证据日志、research/probes/ 下的探针脚本。
保留：耳机 MAC（用户明确说无所谓）、耳机状态数据。
替换：设备 UUID(deviceCode)、用户本机路径、adb 序列号、手机型号/名称、
      用户内网 IP、用户名。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # <REPO>

# 顺序很重要：先替换长串，再替换短串
RULES: list[tuple[str, str]] = [
    # --- 设备 UUID（= 激活服务器的 deviceCode，设备级唯一标识）---
    # 空格分隔形式（日志里的 payload 打印）
    (r"AA BB CC DD EE FF 00 11 22 33 44 55 66 77 88", "AA BB CC DD EE FF 00 11 22 33 44 55 66 77 88"),
    (r"AA BB CC DD EE FF 00 11 22 33 44 55 66 77 99", "AA BB CC DD EE FF 00 11 22 33 44 55 66 77 99"),
    # 粘连大写/小写
    (r"AABBCCDDEEFF00112233445566778899", "AABBCCDDEEFF00112233445566778899"),
    (r"aabbccddeeff00112233445566778899", "aabbccddeeff00112233445566778899"),
    (r"00aabbccddeeff00112233445566778899", "00aabbccddeeff00112233445566778899"),
    (r"01aabbccddeeff00112233445566778899", "01aabbccddeeff00112233445566778899"),
    (r"aabbccddeeff001122334455667788aa", "aabbccddeeff001122334455667788aa"),
    # --- 用户内网 IP（Logan 日志里出现过）---
    (r"10\.12\.\d{1,3}\.\d{1,3}", "192.0.2.10"),
    # --- 本机路径 ---
    (r"D:\\DeepSeek\\fiil-ldac-unlock", "<REPO>"),
    (r"D:\\DeepSeek\\_tools", "<TOOLS>"),
    (r"D:\\DeepSeek\\fiil_analysis", "<JADX_OUT>"),
    (r"D:\\DeepSeek\\fiil_pods_pc", "<PODS_PC>"),
    (r"D:\\DeepSeek", "<WORK>"),
    (r"C:\\Users\\<USER>", "<HOME>"),
    # --- adb 序列号 / 手机 ---
    (r"<ADB_SERIAL>", "<ADB_SERIAL>"),
    (r"<PHONE_MODEL>", "<PHONE_MODEL>"),
    (r"\bditing\b", "<PHONE_CODENAME>"),
    (r"<PHONE_NAME>", "<PHONE_NAME>"),
    (r"<PHONE_NAME>", "<PHONE_NAME>"),
    (r"Redmi <PHONE_CODENAME>", "<PHONE_CODENAME>"),
    (r"<USER>", "<USER>"),
]

SUFFIXES = {".log", ".txt", ".py", ".md", ".json", ".yml", ".yaml"}
SKIP_DIRS = {".git", "build", "dist", "__pycache__", ".ruff_cache", "_internal"}


def redact_text(text: str) -> tuple[str, int]:
    hits = 0
    for pat, repl in RULES:
        text, n = re.subn(pat, repl, text)
        hits += n
    return text, hits


def process(path: Path) -> tuple[int, bool]:
    try:
        raw = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return 0, False
    new, hits = redact_text(raw)
    if hits:
        path.write_text(new, encoding="utf-8")
    return hits, True


def main() -> int:
    targets = [sys.argv[1]] if len(sys.argv) > 1 else ["research"]
    total_files = 0
    total_hits = 0
    for t in targets:
        base = ROOT / t
        files = [base] if base.is_file() else [
            p for p in base.rglob("*")
            if p.is_file() and p.suffix in SUFFIXES
            and not any(part in SKIP_DIRS for part in p.parts)
        ]
        for p in files:
            hits, ok = process(p)
            if not ok:
                print(f"[skip 非UTF8] {p.relative_to(ROOT)}")
                continue
            if hits:
                print(f"[脱敏 {hits:>3} 处] {p.relative_to(ROOT)}")
                total_hits += hits
                total_files += 1
    print(f"\n[=] 共处理 {total_files} 个文件，替换 {total_hits} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
