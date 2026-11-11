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


def _raises_unsafe(guard, cid):
    """probe_guard.assert_safe(cid) 是否按预期抛 UnsafeCommandError。"""
    try:
        guard.assert_safe(cid)
    except guard.UnsafeCommandError:
        return True
    return False


print("=" * 70)
print(" 1. F39 / Bluetrum 组帧（对照 com.bluetrum.devicemanager.z.b）")
print("=" * 70)

# 写左耳 license：payload = 0C 11 + 17 字节，共 19 字节
# 分片上限 15，所以拆成 15 + 4 两帧
left = bytes(17)
frames, seq = F.f39_activate_frames(left, 0)
check(
    "左耳 license 第 0 帧（5 头 + 15 payload）",
    frames[0],
    bytes([0x00, 0x01, 0x01, 0x10, 0x0F]) + bytes([0x0C, 0x11]) + bytes(13),
)
check("左耳 license 第 1 帧（5 头 + 4 payload）", frames[1], bytes([0x01, 0x01, 0x01, 0x11, 0x04]) + bytes(4))

right = bytes([0x01]) + bytes(16)
frames, seq = F.f39_activate_frames(right, 2)
check(
    "右耳 license 第 0 帧",
    frames[0],
    bytes([0x02, 0x01, 0x01, 0x10, 0x0F]) + bytes([0x0C, 0x11, 0x01]) + bytes(12),
)

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

check(
    "F43 左耳 license",
    F.sdp_frame(F.F43_CMD_CONFIG_EXTEND, 4, bytes(17)),
    bytes.fromhex("ff010013023409070411" + "00" * 17),
)
check(
    "F43 右耳 license",
    F.sdp_frame(F.F43_CMD_CONFIG_EXTEND, 4, bytes([1]) + bytes(16)),
    bytes.fromhex("ff010013023409070411" + "01" + "00" * 16),
)
check("F43 打开 LDAC", F.f43_switch_frame(True), bytes.fromhex("ff01000302340904040101"))

# F048 走的是 Mate 组帧（不是 SDP）：F048 通过 RFCOMM UUID d52b47bc-… 连上后
# 走 CommandManager → d/a.java:243 sendCommand() → writeMate()；
# b.java:264 那个 SDP 版 write(baseCommand) 在全工程里无人调用（死代码）。
check(
    "F048 写 license 是 Mate 帧（24 字节）",
    F.f048_activate_frames(bytes(17), bytes([1]) + bytes(16))[0],
    bytes.fromhex("0001010013" + "0c11") + bytes(17),
)
check("F048 右耳首字节 0x01", F.f048_activate_frames(bytes(17), bytes([1]) + bytes(16))[1][7], 0x01)
check("F048 打开 LDAC", F.f048_switch_frame(True), bytes.fromhex("00010100030d0101"))
check("F048 关闭 LDAC", F.f048_switch_frame(False), bytes.fromhex("00010100030d0100"))
check("F048 开关与 F046 逐字节相同", F.f048_switch_frame(True), F.mate_frame(1, 13, b"\x01"))
check("F048 的 setActivationLdac 与 F046 同 cid/cmdId", (F.F048_CLASSIFY_ID, F.F048_CMD_ACTIVATE), (1, 12))
check("Mate 帧 cmdId=0 时省略两字节", F.mate_frame(36, 0), bytes.fromhex("0024010000"))

# Gaia 组帧：与 com/fiil/sdk/command/FiilCommandUtil.java:517-534 getSendBuffer 一致
# 8 字节头 SOF|ver|flags|payloadLen|vendHi vendLo|cmdHi cmdLo，payloadLen 只算 payload
check(
    "Gaia 1968 左耳 license（17B payload）",
    F.gaia_activate_frames(bytes(17), bytes([1]) + bytes(16))[0],
    bytes.fromhex("ff010011023407b0") + bytes(17),
)
check("Gaia 1968 右耳首字节 0x01", F.gaia_activate_frames(bytes(17), bytes([1]) + bytes(16))[1][8], 0x01)
check("Gaia 1970 打开 LDAC", F.gaia_switch_frame(True), bytes.fromhex("ff010001023407b201"))
check(
    "Gaia 1971 查询开关（空 payload，8 字节）",
    F.gaia_query_frame(F.GAIA_CMD_GET_LDAC_SWITCH),
    bytes.fromhex("ff010000023407b3"),
)
check(
    "Gaia 1966 查询 UUID", F.gaia_query_frame(F.GAIA_CMD_GET_HEADSET_UUID), bytes.fromhex("ff010000023407ae")
)
check(
    "Gaia 1967 查询购买类型",
    F.gaia_query_frame(F.GAIA_CMD_GET_LDAC_BUY_TYPE),
    bytes.fromhex("ff010000023407af"),
)
check("Gaia VENDOR_FF = 564", F.GAIA_VENDOR_FF, 564)
check("Gaia 头长 8", F.GAIA_HEADER_LEN, 8)
check("Gaia ACK 首字节 0 算成功", F.gaia_ack_ok(bytes([0x00])), True)
check("Gaia ACK 首字节非 0 算失败", F.gaia_ack_ok(bytes([0x01])), False)
check("Gaia ACK 空回包算失败", F.gaia_ack_ok(b""), False)
check("Gaia 1971 回包取 [1]（不是 [0]）", F.gaia_switch_state(bytes([0x00, 0x01])), 1)
check("Gaia 1971 回包过短返回 None", F.gaia_switch_state(bytes([0x00])), None)

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
        P.PREDECOMPILED,
        "smali_classes3",
        "com",
        "fengeek",
        "main",
        "f048",
        "fragment",
        "F048HomeFragment.smali",
    )
    if os.path.isfile(smali):
        text = open(smali, encoding="utf-8").read()
        pat = r"\.method[^\n]*\bo\(\)V\n"
        m = re.search(pat, text)
        check("在 F048HomeFragment 找到 o()V", bool(m), True)
        body = text[m.end() :]
        lm = re.search(r"^\s*\.locals\s+\d+", body, re.M)
        check("o()V 有 .locals 指令", bool(lm), True)
        text2 = re.sub(r"(\.method[^\n]*\bo\(\)V\n\s*)\.locals\s+\d+", r"\g<1>.locals 100", text, count=1)
        check("能把 .locals 提到 100", ".locals 100" in text2, True)
        snip = P.SMALI_SNIPPET.format(code="00" * 16 + "," + "00" * 16, type_hex="3")
        check("注入片段含 return-void", "return-void" in snip, True)
        check(
            "注入片段引用 UnlockLDACActivity",
            "Lcom/fengeek/main/heat_info_fragment/ldac/UnlockLDACActivity;" in snip,
            True,
        )
        check(
            "注入片段用 Fragment.getContext", "Landroidx/fragment/app/Fragment;->getContext()" in snip, True
        )
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
    check(
        "BLE Mate 握手 setUnlock",
        B.build_mate_frame(B.CID_QUERY, B.Q_UNLOCK, bytes([0x02, 0x34]), 0),
        bytes.fromhex("00270100 04ff0202 34".replace(" ", "")),
    )
    check(
        "BLE Mate 查询帧 getLdacUnlock(142)",
        B.build_mate_frame(B.CID_QUERY, B.Q_LDAC_UNLOCK, b"", 2),
        bytes.fromhex("0227010002 8e00".replace(" ", "")),
    )
    check(
        "BLE Mate 写开关 setLdacSwitch(1)",
        B.build_mate_frame(B.CID_SET_PARAM, B.SET_LDAC_SWITCH, bytes([1]), 6),
        bytes.fromhex("06010100 030d0101".replace(" ", "")),
    )
    check(
        "BLE Mate 写 license 17 字节",
        B.build_mate_frame(B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, bytes(17), 0),
        bytes.fromhex("00010100 130c 11".replace(" ", "")) + bytes(17),
    )

    # SDP 组帧：与 FIILPeripheral.java:483-505 一致
    check(
        "BLE SDP 组帧（F048 写 license）",
        B.build_sdp_frame(1, 12, bytes(17)),
        bytes.fromhex("ff010013023400010c 11".replace(" ", "")) + bytes(17),
    )

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
    check("PID 回包 00 2E 01 → earType 索引 1 = 46", bytes.fromhex("002e01")[B.PID_EAR_TYPE_INDEX], 46)

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
print(" 6. 盲扫保护 / ACK 规则（对照 cid=36 事故与逐长度实测）")
print("=" * 70)

try:
    import probe_guard as G

    # cid=36 裸帧 = 恢复出厂设置，必须被拦住
    check("probe_guard：cid=36 不安全", G.is_safe_cid(36), False)
    check("probe_guard：cid=36 有说明", bool(G.describe(36)), True)
    check("probe_guard：cid=36 抛 UnsafeCommandError", _raises_unsafe(G, 36), True)

    # 会改状态的 cid 全部不安全
    for _cid in (1, 2, 3, 32, 33, 34, 37, 38, 41, 44, 50):
        check(f"probe_guard：cid={_cid} 不安全", G.is_safe_cid(_cid), False)

    # cid=39 是纯查询族，安全
    check("probe_guard：cid=39 安全", G.is_safe_cid(39), True)
    check("probe_guard：cid=35 可发空帧探测", G.is_safe_cid(35), True)
    check("probe_guard：cid=35 被标记为未知族", G.is_caution_cid(35), True)
    check("probe_guard：cid=35 禁止展开子命令", G.is_safe_default(35, 1), False)

    # ACK 语义：只有「长度 17 + 首字节 0/1」才回 00
    check("ACK 规则：17 字节首字节 0x00 合法", B.license_ack_ok(bytes(17)), True)
    _r = bytearray(17)
    _r[0] = 0x01
    check("ACK 规则：17 字节首字节 0x01 合法", B.license_ack_ok(bytes(_r)), True)
    _bad = bytearray(17)
    _bad[0] = 0x02
    check("ACK 规则：17 字节首字节 0x02 不合法", B.license_ack_ok(bytes(_bad)), False)
    check("ACK 规则：16 字节不合法", B.license_ack_ok(bytes(16)), False)
    check("ACK 规则：18 字节不合法", B.license_ack_ok(bytes(18)), False)

except ImportError as e:
    print(f"  [SKIP] probe_guard 导入失败：{e}")

print()
print("=" * 70)
print(" 7. 激活码解析 / GUI 复用（对照 UnlockLDACActivity.java:207 split）")
print("=" * 70)

try:
    import fiil_ble as B

    _one = "0123456789abcdef0123456789abcdef"
    check("解析：单段 32 hex", len(B.parse_activate_codes(_one)), 1)
    check("解析：单段内容正确", B.parse_activate_codes(_one)[0], bytes.fromhex(_one))
    check("解析：两段逗号分隔", len(B.parse_activate_codes(f"{_one},{_one}")), 2)
    check("解析：大写也认", B.parse_activate_codes(_one.upper())[0], bytes.fromhex(_one))
    check("解析：允许前后空白", len(B.parse_activate_codes(f"  {_one}  ")), 1)

    for _bad, _why in (
        ("", "空串"),
        ("  ", "全空白"),
        (_one[:-2], "31 字符"),
        (_one + "00", "34 字符"),
        (f"{_one},{_one},{_one}", "三段"),
        ("z" * 32, "非 hex"),
    ):
        try:
            B.parse_activate_codes(_bad)
            _got = "没抛错"
        except ValueError:
            _got = "抛 ValueError"
        check(f"解析：{_why} 被拒", _got, "抛 ValueError")

    # 解析 → build_license 的端到端拼装
    _lic = B.build_license(B.parse_activate_codes(_one)[0], 0x01)
    check("解析→license：长度 17", len(_lic), 17)
    check("解析→license：首字节耳别 0x01", _lic[0], 0x01)
    check("解析→license：后 16 字节等于激活码", _lic[1:], bytes.fromhex(_one))

except ImportError as e:
    print(f"  [SKIP] fiil_ble 导入失败：{e}")

print()
print("=" * 70)
print(f" 结果：{OK} 通过，{FAIL} 失败")
print("=" * 70)
sys.exit(1 if FAIL else 0)
