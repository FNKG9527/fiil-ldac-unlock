"""离线自检：不需要耳机、不需要串口，验证帧构造是否与逆向结果一致。

跑法：
    python selftest.py

全部 PASS 说明 fiil_ldac.py 组出来的字节和 App 发出去的字节一致。
"""
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

lic_left, lic_right = F.build_license_pair("11" * 16 + "," + "22" * 16)
check("左耳前缀 0x00", lic_left[0], 0x00)
check("右耳前缀 0x01", lic_right[0], 0x01)
check("左耳长度 17", len(lic_left), 17)
check("右耳长度 17", len(lic_right), 17)

lic_left, lic_right = F.build_zero_pair()
check("后门：左耳全 0", lic_left, bytes(17))
check("后门：右耳 01 开头", lic_right, bytes([1]) + bytes(16))

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
        text = open(smali, encoding="utf-8").read()
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
print(" 5. BLE 组帧 / 解帧（对照 FIILPeripheral.java 与实测回包）")
print("=" * 70)

try:
    import fiil_ble as B

    # Mate 组帧：与 com/fengeek/main/i/b.java:writeMate 一致
    check("BLE Mate 握手 setUnlock",
          B.build_mate_frame(B.CID_QUERY, B.Q_UNLOCK, bytes([0x02, 0x34]), 0),
          bytes.fromhex("00270100 04ff0202 34".replace(" ", "")))
    check("BLE Mate 查询帧 getLdacUnlock(142)",
          B.build_mate_frame(B.CID_QUERY, B.Q_LDAC_UNLOCK, b"", 2),
          bytes.fromhex("0227010002 8e00".replace(" ", "")))
    check("BLE Mate 写开关 setLdacSwitch(1)",
          B.build_mate_frame(B.CID_SET_PARAM, B.SET_LDAC_SWITCH, bytes([1]), 6),
          bytes.fromhex("06010100 030d0101".replace(" ", "")))
    check("BLE Mate 写 license 17 字节",
          B.build_mate_frame(B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, bytes(17), 0),
          bytes.fromhex("00010100 130c 11".replace(" ", "")) + bytes(17))

    # SDP 组帧：与 FIILPeripheral.java:483-505 一致
    check("BLE SDP 组帧（F048 写 license）",
          B.build_sdp_frame(1, 12, bytes(17)),
          bytes.fromhex("ff010013023400010c 11".replace(" ", "")) + bytes(17))

    # 解帧：用真机实测回包逐条验证
    real = bytes.fromhex("07270200038e01 01".replace(" ", ""))
    frames, rest = B.drain(real)
    check("解帧：真机 142 回包 → 1 帧", len(frames), 1)
    check("解帧：cid=39", frames[0].cid, 39)
    check("解帧：cmd=142", frames[0].cmd, 142)
    check("解帧：payload=01（已解锁）", frames[0].payload, b"\x01")
    check("解帧：无残留", rest, b"")

    short = bytes.fromhex("07010200030d0100".replace(" ", ""))
    frames, _ = B.drain(short)
    check("解帧：SET ACK 短帧 payload[0]=0 即成功", frames[0].ok, True)

    # 半帧必须保留而不是丢弃（真实缺陷回归测试）
    half = real[:4]
    frames, rest = B.drain(half)
    check("解帧：半帧不丢，原样保留", rest, half)

    # 帧头非法时丢 1 字节重同步
    frames, rest = B.drain(b"\x00\x00\x00" + real)
    check("解帧：非法帧头重同步后仍能解出", len(frames), 1)

    # 机型识别：earType 在 buff[1]，不是 buff[0]
    check("PID 回包 00 2E 01 → earType 索引 1 = 46",
          bytes.fromhex("002e01")[B.PID_EAR_TYPE_INDEX], 46)

    # license 形态
    check("BLE license 左耳首字节 0x00", B.build_license(bytes(16), 0x00)[0], 0x00)
    check("BLE license 右耳首字节 0x01", B.build_license(bytes(16), 0x01)[0], 0x01)
    check("BLE license 长度 17", len(B.build_license(bytes(16))), 17)

    # 机型能力表
    check("F046 可写 license", 46 in B.LICENSE_CAPABLE_EAR_TYPES, True)
    check("F048 可写 license", 48 in B.LICENSE_CAPABLE_EAR_TYPES, True)
    check("F045 不可写 license", 45 in B.LICENSE_CAPABLE_EAR_TYPES, False)
    check("F053 不可写 license", 53 in B.LICENSE_CAPABLE_EAR_TYPES, False)

except ImportError as e:
    print(f"  [SKIP] fiil_ble 导入失败：{e}")

print()
print("=" * 70)
print(f" 结果：{OK} 通过，{FAIL} 失败")
print("=" * 70)
sys.exit(1 if FAIL else 0)
