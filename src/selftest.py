# -*- coding: utf-8 -*-
"""离线自检：不需要耳机、不需要串口，验证帧构造是否与逆向结果一致。

跑法：
    python selftest.py

全部 PASS 说明 fiil_ldac.py 组出来的字节和 App 发出去的字节一致。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fiil_ldac as F

OK = 0
FAIL = 0


def check(name, got, want):
    global OK, FAIL
    if got == want:
        OK += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")
        print(f"         got  = {got.hex() if isinstance(got, bytes) else got}")
        print(f"         want = {want.hex() if isinstance(want, bytes) else want}")


print("=" * 70)
print(" 1. F39 / Bluetrum 组帧（对照 com.bluetrum.devicemanager.z.b）")
print("=" * 70)

# 写左耳 license：payload = 0C 11 + 17 字节，共 19 字节
# 分片上限 15，所以拆成 15 + 4 两帧
left = bytes(17)
frames, seq = F.f39_activate_frames(left, 0)
check("左耳 license 第 0 帧（5 头 + 15 payload）", frames[0],
      bytes([0x00, 0x01, 0x01, 0x10, 0x0F]) + bytes([0x0C, 0x11]) + bytes(13))
check("左耳 license 第 1 帧（5 头 + 4 payload）", frames[1],
      bytes([0x01, 0x01, 0x01, 0x11, 0x04]) + bytes(4))

right = bytes([0x01]) + bytes(16)
frames, seq = F.f39_activate_frames(right, 2)
check("右耳 license 第 0 帧", frames[0],
      bytes([0x02, 0x01, 0x01, 0x10, 0x0F]) + bytes([0x0C, 0x11, 0x01]) + bytes(12))

# 开 LDAC：payload = 0D 01 01
frames, seq = F.f39_switch_frames(True, 4)
check("打开 LDAC", frames[0], bytes.fromhex("04010100030d0101"))

# 关 LDAC
frames, seq = F.f39_switch_frames(False, 4)
check("关闭 LDAC", frames[0], bytes.fromhex("04010100030d0100"))

# 查询激活状态
frames, seq = F.f39_query_frames(F.F39_QUERY_ACTIVATION, 0)
check("查询激活状态", frames[0], bytes.fromhex("002701000 18e".replace(" ", "")))

print()
print("=" * 70)
print(" 2. SDP / F43 组帧（对照 com.fengeek.utils.l1.v0.a.getPayload）")
print("=" * 70)

check("F43 左耳 license", F.sdp_frame(F.F43_CMD_CONFIG_EXTEND, 4, bytes(17)),
      bytes.fromhex("ff010013023409070411" + "00" * 17))
check("F43 右耳 license", F.sdp_frame(F.F43_CMD_CONFIG_EXTEND, 4, bytes([1]) + bytes(16)),
      bytes.fromhex("ff010013023409070411" + "01" + "00" * 16))
check("F43 打开 LDAC", F.f43_switch_frame(True),
      bytes.fromhex("ff01000302340904040101"))

print()
print("=" * 70)
print(" 3. license 解析")
print("=" * 70)

l, r = F.build_license_pair("11" * 16 + "," + "22" * 16)
check("左耳前缀 0x00", l[0], 0x00)
check("右耳前缀 0x01", r[0], 0x01)
check("左耳长度 17", len(l), 17)
check("右耳长度 17", len(r), 17)

l, r = F.build_zero_pair()
check("后门：左耳全 0", l, bytes(17))
check("后门：右耳 01 开头", r, bytes([1]) + bytes(16))

print()
print("=" * 70)
print(" 4. patch_apk 注入逻辑（只做字符串变换，不写文件）")
print("=" * 70)

try:
    import patch_apk as P
    # 反编译产物默认在 <仓库根>/build/apktool_out，可用 FIIL_PREDECOMPILED_SMALI 直接指定文件
    smali = os.environ.get("FIIL_PREDECOMPILED_SMALI") or os.path.join(
        P.PREDECOMPILED, "smali_classes3", "com", "fengeek", "main",
        "f048", "fragment", "F048HomeFragment.smali")
    if os.path.isfile(smali):
        text = io.open(smali, encoding="utf-8").read()
        pat = r"\.method[^\n]*\bo\(\)V\n"
        m = re.search(pat, text)
        check("在 F048HomeFragment 找到 o()V", bool(m), True)
        body = text[m.end():]
        lm = re.search(r"^\s*\.locals\s+\d+", body, re.M)
        check("o()V 有 .locals 指令", bool(lm), True)
        text2 = re.sub(r"(\.method[^\n]*\bo\(\)V\n\s*)\.locals\s+\d+",
                       r"\g<1>.locals 100", text, count=1)
        check("能把 .locals 提到 100", ".locals 100" in text2, True)
        snip = P.SMALI_SNIPPET.format(code="00" * 16 + "," + "00" * 16, type_hex="3")
        check("注入片段含 return-void", "return-void" in snip, True)
        check("注入片段引用 UnlockLDACActivity",
              "Lcom/fengeek/main/heat_info_fragment/ldac/UnlockLDACActivity;" in snip, True)
        check("注入片段用 Fragment.getContext",
              "Landroidx/fragment/app/Fragment;->getContext()" in snip, True)
        check("注入片段带 type=3", "const/4 v95, 0x3" in snip, True)
    else:
        print("  [SKIP] 没找到反编译目录，跳过（不影响其它检查）")
except ImportError as e:
    print(f"  [SKIP] {e}")

print()
print("=" * 70)
print(f" 结果：{OK} 通过，{FAIL} 失败")
print("=" * 70)
sys.exit(1 if FAIL else 0)
