#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIIL+ LDAC 激活 —— 方法三：APK 内嵌激活码（重打包）
====================================================

思路
----
FIIL+ 的 LDAC 激活流程是这样的（见 README 第 3 节）：

    点「激活」→ m() 读左右耳 UUID → o() 请求服务器
    → 服务器返回 activateCode → 跳 UnlockLDACActivity 写进耳机

而 `UnlockLDACActivity` 本身**完全不联网**，它只是：
    1. 从 Intent 里取 "activateCode" 字符串
    2. 按逗号切成左右两段 hex
    3. 左耳前面补 0x00、右耳前面补 0x01，凑成 17 字节
    4. 通过蓝牙写进耳机

所以只要让 App 拿到一个 activateCode，服务器在不在都无所谓。
最干净的办法是：**把 activateCode 硬编码进 APK**，让 App 完全跳过网络请求。

本脚本自动完成：
    apktool d  →  改 smali  →  apktool b  →  zipalign  →  apksigner

用法
----
    # 1. 先反编译（如果还没做）
    python src/patch_apk.py decompile

    # 2. 注入激活码（不指定 --code 就用全零，等效 CC Pro2 后门）
    python src/patch_apk.py inject
    python src/patch_apk.py inject --code "AAAAAAAA...,BBBBBBBB..."

    # 3. 回编译 + 签名
    python src/patch_apk.py build

    # 4. 卸载旧版、装新版
    adb uninstall com.fengeek.f002
    adb install -r build/fiil_patched.apk

前置条件
--------
    * JDK 11+（apksigner / keytool 需要）
    * apktool.jar（默认找 <仓库根>/tools/apktool.jar，可用 FIIL_APKTOOL 覆盖）
    * Android SDK build-tools（zipalign / apksigner），或设置 ANDROID_HOME
    * 原版 APK 放在 <仓库根>/fiil.apk，或用 FIIL_APK 指定路径

路径约定
--------
    所有中间产物都写进 <仓库根>/build/（可用 FIIL_BUILD 覆盖），不污染仓库根目录。
    首次运行会自动创建 build/。

风险
----
    * 重打包后签名变了，**必须先卸载原版**，且原版的登录态/绑定数据会丢失
    * 部分机型有签名校验（本 App 未发现）
    * 改包仅供自己使用
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

# Windows 控制台默认 GBK，中文会乱码，强制 UTF-8 输出
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # 仓库根目录

# 路径全部可用环境变量覆盖，默认值面向「仓库根目录放 fiil.apk + tools/apktool.jar」
APK = os.environ.get("FIIL_APK") or os.path.join(ROOT, "fiil.apk")
APKTOOL = os.environ.get("FIIL_APKTOOL") or os.path.join(ROOT, "tools", "apktool.jar")
BUILD = os.environ.get("FIIL_BUILD") or os.path.join(ROOT, "build")
WORK = os.path.join(BUILD, "apk_work")            # apktool 工作目录
# 已有反编译结果时直接复用，不用再花 3 分钟解包 94MB 的 APK
PREDECOMPILED = os.path.join(BUILD, "apktool_out")
OUT_APK = os.path.join(BUILD, "fiil_patched.apk")
KEYSTORE = os.path.join(BUILD, "fiil_debug.keystore")

# 目标 smali：com/fengeek/main/f048/fragment/F048HomeFragment.smali 的 o() 方法
# o() 原本是：拼 deviceCode -> networkingGet(...)
# 我们把它改成：直接 new Intent(UnlockLDACActivity) 并塞 activateCode
# apktool 会按 dex 拆成 smali / smali_classes2 / smali_classes3，F048 在 classes3
TARGET_SMALI = os.path.join(
    WORK, "smali_classes3", "com", "fengeek", "main", "f048", "fragment", "F048HomeFragment.smali"
)

# 兜底：如果 F048 找不到，再试其它机型的网络入口方法
#   (机型 smali 文件, 方法名, 描述符, UnlockLDACActivity 需要的 type)
#   type 决定 UnlockLDACActivity.h() 走哪条通道：
#       1 = F43 SDP (n0.setLDAC)
#       2 = F39 / Bluetrum (F39AppSettingRequest.setActivateLdac)
#       3 = F048 SDP (e.setActivationLdac)
#       其它 = Gaia 老协议 (FiilManager.setUnlockLDAC)
FALLBACKS = [
    (os.path.join(WORK, "smali_classes3", "com", "fengeek", "main", "f046", "fragment", "F046HomeFragment.smali"),
     "h", "([B)V", 0),
    (os.path.join(WORK, "smali_classes3", "com", "fengeek", "main", "f039new", "ui", "fragment", "CcPro2NewEleFragment.smali"),
     "O", "()V", 2),
]

# 默认注入点（F048 系列）走 type=3 的 SDP 通道
DEFAULT_TYPE = 3


def run(cmd, **kw):
    print("$ " + " ".join(str(c) for c in cmd))
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        raise SystemExit(f"[!] 命令失败，退出码 {r.returncode}")
    return r


def find_tool(name):
    """在 PATH / ANDROID_HOME 里找 zipalign / apksigner。"""
    p = shutil.which(name)
    if p:
        return p
    home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if home:
        bt = os.path.join(home, "build-tools")
        if os.path.isdir(bt):
            for ver in sorted(os.listdir(bt), reverse=True):
                for ext in (".exe", ".bat", ""):
                    cand = os.path.join(bt, ver, name + ext)
                    if os.path.isfile(cand):
                        return cand
    return None


# ---------------------------------------------------------------------------
# 1. 反编译
# ---------------------------------------------------------------------------
def cmd_decompile(args):
    os.makedirs(BUILD, exist_ok=True)
    if os.path.isdir(WORK) and not args.force:
        print(f"[=] {WORK} 已存在，跳过。要重来加 --force")
        return 0
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    if os.path.isdir(PREDECOMPILED) and not args.force:
        print(f"[=] 发现已有反编译目录 {PREDECOMPILED}，直接复用（省 3 分钟）")
        shutil.copytree(PREDECOMPILED, WORK)
        print(f"[+] 已复制到 {WORK}")
        return 0
    if not os.path.isfile(APKTOOL):
        raise SystemExit(f"[!] 找不到 apktool.jar：{APKTOOL}")
    if not os.path.isfile(APK):
        raise SystemExit(f"[!] 找不到 APK：{APK}")
    run(["java", "-jar", APKTOOL, "d", "-f", "-o", WORK, APK])
    print(f"[+] 反编译完成：{WORK}")
    return 0


# ---------------------------------------------------------------------------
# 2. 注入
# ---------------------------------------------------------------------------
SMALI_SNIPPET = """
    # ---- [LDAC-PATCH] 跳过服务器，直接写死 activateCode ----
    # 本方法用到的临时寄存器：v90 起。注入前已把 .locals 提到 100。
    .local v99, "code":Ljava/lang/String;
    const-string v99, "{code}"

    # Intent intent = new Intent(getContext(), UnlockLDACActivity.class)
    new-instance v98, Landroid/content/Intent;
    invoke-virtual {{p0}}, Landroidx/fragment/app/Fragment;->getContext()Landroid/content/Context;
    move-result-object v97

    const-class v96, Lcom/fengeek/main/heat_info_fragment/ldac/UnlockLDACActivity;

    invoke-direct {{v98, v97, v96}}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V

    # intent.putExtra("activateCode", code)
    const-string v96, "activateCode"

    invoke-virtual {{v98, v96, v99}}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;

    # intent.putExtra("type", N)   // 通道选择，见 DEFAULT_TYPE / FALLBACKS
    const-string v96, "type"

    const/4 v95, 0x{type_hex}

    invoke-virtual {{v98, v96, v95}}, Landroid/content/Intent;->putExtra(Ljava/lang/String;I)Landroid/content/Intent;

    # startActivity(intent)
    invoke-virtual {{p0, v98}}, Landroidx/fragment/app/Fragment;->startActivity(Landroid/content/Intent;)V

    return-void
    # ---- [/LDAC-PATCH] ----
"""


def cmd_inject(args):
    if not os.path.isdir(WORK):
        raise SystemExit("[!] 还没反编译，先跑：python patch_apk.py decompile")

    code = args.code or (("00" * 16) + "," + ("00" * 16))
    if "," not in code or len(code.split(",")) != 2:
        raise SystemExit('[!] --code 格式："左32hex,右32hex"')
    for part in code.split(","):
        if len(part) != 32:
            raise SystemExit(f"[!] 每段必须 32 个 hex 字符，当前 {len(part)}")

    target = None
    method_name, method_sig = "o", "()V"
    type_value = DEFAULT_TYPE
    if os.path.isfile(TARGET_SMALI):
        target = TARGET_SMALI
    else:
        for cand, mname, msig, mtype in FALLBACKS:
            if os.path.isfile(cand):
                target, method_name, method_sig = cand, mname, msig
                type_value = mtype
                break
    if not target:
        raise SystemExit("[!] 没找到可注入的 smali 文件，可能 apktool 版本不同")

    print(f"[*] 目标：{target}")
    print(f"[*] 方法：{method_name}{method_sig}   type={type_value}")
    with open(target, "r", encoding="utf-8") as fh:
        text = fh.read()

    if "LDAC-PATCH" in text:
        # 已经打过补丁：替换 code
        text = re.sub(
            r'const-string v99, "[^"]*"',
            f'const-string v99, "{code}"',
            text,
        )
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("[+] 已更新为新的 activateCode")
        return 0

    # 找目标方法：.method ... o()V / h([B)V / O()V
    pat = r"\.method[^\n]*\b" + re.escape(method_name) + re.escape(method_sig) + r"\n"
    m = re.search(pat, text)
    if not m:
        raise SystemExit(f"[!] 在目标文件里找不到 {method_name}{method_sig} 方法，请手动定位")

    # 在方法体开头插入（紧跟 .locals 之后）
    body_start = m.end()
    lm = re.search(r"^\s*\.locals\s+\d+", text[body_start:], re.M)
    if not lm:
        raise SystemExit(f"[!] {method_name}{method_sig} 方法里找不到 .locals 指令")

    # 需要 100 个寄存器：把 .locals N 提到 100
    text = re.sub(
        r"(\.method[^\n]*\b" + re.escape(method_name) + re.escape(method_sig) + r"\n\s*)\.locals\s+\d+",
        r"\g<1>.locals 100",
        text,
        count=1,
    )
    # 重新计算插入点
    m = re.search(pat, text)
    body_start = m.end()
    lm = re.search(r"^\s*\.locals\s+\d+", text[body_start:], re.M)
    insert_at = body_start + lm.end()

    snippet = SMALI_SNIPPET.format(code=code, type_hex=f"{type_value:X}")
    text = text[:insert_at] + snippet + text[insert_at:]

    with open(target, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("[+] 注入完成。下一步：python patch_apk.py build")
    return 0


# ---------------------------------------------------------------------------
# 3. 回编译 + 签名
# ---------------------------------------------------------------------------
def cmd_build(args):
    if not os.path.isdir(WORK):
        raise SystemExit("[!] 还没反编译")
    os.makedirs(BUILD, exist_ok=True)

    unsigned = os.path.join(BUILD, "fiil_patched_unsigned.apk")
    aligned = os.path.join(BUILD, "fiil_patched_aligned.apk")

    run(["java", "-jar", APKTOOL, "b", WORK, "-o", unsigned])

    zipalign = find_tool("zipalign")
    if zipalign:
        run([zipalign, "-p", "-f", "4", unsigned, aligned])
    else:
        print("[!] 没找到 zipalign，跳过对齐（多数机型仍可安装）")
        shutil.copyfile(unsigned, aligned)

    if not os.path.isfile(KEYSTORE):
        print("[*] 生成调试签名")
        run([
            "keytool", "-genkeypair", "-v",
            "-keystore", KEYSTORE,
            "-alias", "fiil",
            "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
            "-storepass", "fiil123", "-keypass", "fiil123",
            "-dname", "CN=FIIL Patch, OU=Self, O=Self, L=NA, ST=NA, C=CN",
        ])

    apksigner = find_tool("apksigner")
    if apksigner:
        run([apksigner, "sign",
             "--ks", KEYSTORE, "--ks-pass", "pass:fiil123",
             "--key-pass", "pass:fiil123", "--ks-key-alias", "fiil",
             "--out", OUT_APK, aligned])
    else:
        print("[!] 没找到 apksigner，改用 jarsigner（v1 签名，Android 11+ 可能装不上）")
        run(["jarsigner", "-keystore", KEYSTORE, "-storepass", "fiil123",
             "-keypass", "fiil123", "-signedjar", OUT_APK, aligned, "fiil"])

    print(f"\n[+] 完成：{OUT_APK}")
    print("\n安装：")
    print("    adb uninstall com.fengeek.f002")
    print(f'    adb install -r "{OUT_APK}"')
    return 0


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="FIIL+ APK 内嵌 LDAC 激活码",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("decompile", help="apktool d")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_decompile)

    p = sub.add_parser("inject", help="把 activateCode 写进 smali")
    p.add_argument("--code", help='"左32hex,右32hex"，默认全零')
    p.set_defaults(func=cmd_inject)

    p = sub.add_parser("build", help="apktool b + 签名")
    p.set_defaults(func=cmd_build)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
