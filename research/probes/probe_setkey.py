"""深挖 cid=34 setKey / cid=39 getKey：FIIL 的键值读写接口（不需要 license 的另一条通路）。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
SRC = Path(__file__).resolve().parent.parent / ".." / "fiil_analysis" / "jadx_out" / "sources"
D = SRC / "com" / "fengeek" / "main" / "i" / "d"

print("=" * 78)
print("一、各机型族 d/*.java 里的 setKey / getKey 定义")
print("=" * 78)
for p in sorted(D.glob("*.java")):
    txt = p.read_text(encoding="utf-8", errors="ignore")
    lines = txt.splitlines()
    for i, ln in enumerate(lines, 1):
        if re.search(r"\b(setKey|getKey)\s*\(", ln) and ("void" in ln or "public" in ln or "private" in ln):
            lo, hi = max(1, i - 2), min(len(lines), i + 14)
            print(f"\n--- {p.name}:{i} ---")
            for j in range(lo, hi + 1):
                mark = ">>" if j == i else "  "
                print(f"{mark}{j:5d}: {lines[j - 1]}")
            break

print()
print("=" * 78)
print("二、全仓库 setKey / getKey 的调用点")
print("=" * 78)
call_pat = re.compile(r"\.(setKey|getKey)\s*\(")
skip_dirs = ("com\\fengeek\\main\\i\\d\\",)
count = 0
for p in SRC.rglob("*.java"):
    sp = str(p)
    if any(s in sp for s in skip_dirs):
        continue
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        continue
    for i, ln in enumerate(txt.splitlines(), 1):
        if call_pat.search(ln):
            count += 1
            print(f"  {sp.replace(str(SRC) + chr(92), '')}:{i}: {ln.strip()[:150]}")
print(f"\n调用点合计：{count}")
