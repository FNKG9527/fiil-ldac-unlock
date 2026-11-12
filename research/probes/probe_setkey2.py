"""只看 FIIL 自己的 setKey（cid=34）/ getKey（cid=39 cmd=5）定义与调用，排除 Map.Entry 噪声。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
SRC = Path(__file__).resolve().parent.parent / ".." / "fiil_analysis" / "jadx_out" / "sources"
D = SRC / "com" / "fengeek" / "main" / "i" / "d"

print("=" * 78)
print("一、各机型族 d/*.java 的 setKey 定义（cid=34）")
print("=" * 78)
sig = re.compile(r"public void setKey\s*\(")
for p in sorted(D.glob("*.java")):
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    for i, ln in enumerate(lines, 1):
        if sig.search(ln):
            print(f"\n--- {p.name}:{i} ---")
            for j in range(max(1, i - 1), min(len(lines), i + 18) + 1):
                mark = ">>" if j == i else "  "
                print(f"{mark}{j:5d}: {lines[j - 1]}")
            break

print()
print("=" * 78)
print("二、FIIL 包内对 setKey/getKey 的调用（排除 java/util/Map 的 entry.getKey）")
print("=" * 78)
call_pat = re.compile(r"(?:[A-Za-z0-9_]+\.)*(?:setKey|getKey)\s*\(")
only_fiil = ("com\\fengeek", "com\\fiil")
count = 0
for p in SRC.rglob("*.java"):
    sp = str(p)
    rel = sp.replace(str(SRC) + "\\", "")
    if "\\.java" not in sp:
        continue
    if not rel.startswith(only_fiil):
        continue
    if rel.startswith("com\\fengeek\\main\\i\\d\\"):
        continue
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:  # noqa: BLE001
        continue
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if "getKey()" in s or ".getKey(" in s and "Entry" in s:
            continue
        if call_pat.search(s):
            count += 1
            print(f"  {rel}:{i}: {s[:160]}")
print(f"\n调用点合计：{count}")
