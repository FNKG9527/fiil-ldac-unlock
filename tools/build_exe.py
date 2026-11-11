#!/usr/bin/env python3
"""
把 ``src/fiil_gui.py`` 打包成 Windows 可执行文件。

用法::

    python tools/build_exe.py            # one-dir（推荐，默认）
    python tools/build_exe.py --onefile  # 单文件（在受限环境里可能起不来）

为什么默认 ``--onedir``
-----------------------
PyInstaller 的单文件模式启动时要把自身解包到 ``%TEMP%\\_MEIxxxxx``。在某些
受限令牌 / 沙箱环境里，bootloader 的 ``CreateDirectoryW`` 会被拒绝，程序弹出::

    Error
    Could not create temporary directory!

然后直接退出。同一份代码用 ``--onedir`` 就不需要解包，可以正常启动 —— 这是
在 Windows 上实测到的差异，所以默认选 one-dir。

产物::

    dist/FiilLdacUnlock/FiilLdacUnlock.exe    ← 双击这个
    dist/FiilLdacUnlock/_internal/            ← 必须和 exe 放一起

``dist/`` 已在 .gitignore 里，不会进版本库。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "src" / "fiil_gui.py"
NAME = "FiilLdacUnlock"


def main() -> int:
    ap = argparse.ArgumentParser(description="打包 FIIL LDAC 解锁器 GUI")
    ap.add_argument(
        "--onefile", action="store_true", help="打成单文件（默认是 one-dir，规避受限环境的解包失败）"
    )
    ap.add_argument("--clean", action="store_true", help="构建前清掉 build/ 与 dist/")
    args = ap.parse_args()

    if not ENTRY.is_file():
        print(f"[!] 找不到入口 {ENTRY}")
        return 2

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[!] 需要先装 PyInstaller：python -m pip install pyinstaller")
        return 2

    if args.clean:
        for p in (ROOT / "build", ROOT / "dist"):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                print(f"[*] 已清理 {p}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile" if args.onefile else "--onedir",
        "--windowed",
        "--name",
        NAME,
        "--paths",
        str(ROOT / "src"),
        "--hidden-import",
        "bleak",
        "--hidden-import",
        "bleak.backends.winrt",
        "--collect-submodules",
        "bleak",
        str(ENTRY),
    ]
    print("[*] " + " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        print(f"[!] 打包失败，退出码 {rc}")
        return rc

    exe = (ROOT / "dist" / NAME / f"{NAME}.exe") if not args.onefile else (ROOT / "dist" / f"{NAME}.exe")
    print()
    if exe.is_file():
        size = exe.stat().st_size / (1024 * 1024)
        print(f"[+] 产物 {exe}  ({size:.1f} MB)")
        if not args.onefile:
            print("    注意：_internal/ 目录必须和 exe 放在一起，不能只拷 exe。")
    else:
        print(f"[!] 没找到预期产物 {exe}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
