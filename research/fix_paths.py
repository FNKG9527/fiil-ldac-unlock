"""把探针脚本里的绝对路径占位符改写成相对路径，让脚本在仓库里能直接跑。

脱敏时用 <REPO> / <TOOLS> 这类占位符替换了本机绝对路径，但它们不是合法路径。
这里统一改成基于 __file__ 的相对推导。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBES = ROOT / "research" / "probes"

REPO_EXPR = 'Path(__file__).resolve().parent.parent'

# 纯字符串替换，避免反斜杠转义麻烦
RULES: list[tuple[str, str]] = [
    # 顺序：长串优先
    ('Path(r"<REPO>\\src")', f'{REPO_EXPR} / "src"'),
    ('Path(r"<REPO>\\docs\\evidence")', f'{REPO_EXPR} / "docs" / "evidence"'),
    ('Path(r"<REPO>\\docs")', f'{REPO_EXPR} / "docs"'),
    ('Path(r"<REPO>")', REPO_EXPR),
    ('Path(r"<TOOLS>\\ldac_watch.log")', f'{REPO_EXPR} / "research" / "logs" / "ldac_watch.log"'),
    ('Path(r"<TOOLS>")', f'{REPO_EXPR} / "research"'),
    ('Path(r"<WORK>")', f'{REPO_EXPR} / ".."'),
    ('Path(r"<PODS_PC>")', f'{REPO_EXPR} / ".."'),
    ('Path(r"<JADX_OUT>\\jadx_out\\sources")', f'{REPO_EXPR} / ".." / "fiil_analysis" / "jadx_out" / "sources"'),
    ('Path(r"<JADX_OUT>")', f'{REPO_EXPR} / ".." / "fiil_analysis"'),
    # 拼接形式（不带 Path(r"...") 的裸串）
    ('r"<REPO>\\src"', f'str({REPO_EXPR} / "src")'),
    ('r"<PODS_PC>"', f'str({REPO_EXPR} / "..")'),
]


def main() -> int:
    changed = 0
    for p in sorted(PROBES.glob("*.py")):
        text = p.read_text(encoding="utf-8")
        orig = text
        for old, new in RULES:
            text = text.replace(old, new)
        if text != orig:
            p.write_text(text, encoding="utf-8")
            changed += 1

    # 复查剩余占位符
    remain = []
    for p in sorted(PROBES.glob("*.py")):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "<REPO>" in line or "<TOOLS>" in line or "<WORK>" in line \
                    or "<JADX_OUT>" in line or "<PODS_PC>" in line:
                remain.append(f"{p.name}:{i}: {line.strip()}")

    print(f"[=] 改写 {changed} 个文件")
    print(f"[=] 剩余占位符 {len(remain)} 处")
    for r in remain:
        print("   ", r)

    # 语法检查（用 compile() 代替 py_compile，避开临时文件写入限制）
    bad = 0
    for p in sorted(PROBES.glob("*.py")):
        try:
            compile(p.read_text(encoding="utf-8"), str(p), "exec")
        except SyntaxError as e:
            bad += 1
            print(f"[语法错] {p.name}:{e.lineno}: {e.msg}")
    print(f"[=] 语法检查：{bad} 个失败")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
