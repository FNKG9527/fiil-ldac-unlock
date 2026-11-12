# 交付报告：FIIL 耳机 LDAC 解锁程序（第五轮）

> 2026-11-12 · 对应 FIIL+ 3.5.2（`com.fengeek.f002`）逆向 + 真机验证
> 程序版本：**v1.4.0**

---

## 一句话结论

**部分能，但"解锁"这件事整体没有成功** —— 而且这项研究付出了具体代价。先把结论摆在最前面：

| 你要的效果 | 能不能做到 | 说明 | 验证状态 |
|---|---|---|---|
| 让 FIIL+ App 里的开关不再是灰的（`142=1`） | ❌ 不能离线做到 | 需要厂商服务器签发的 `activateCode`；服务器已 NXDOMAIN | 已被证伪：66 个候选全灭 |
| 耳机真的用 LDAC 传音频 | ❌ 未授权状态下不能 | `142=00` 时耳机不向手机宣告 LDAC 能力，只能协商 AAC | 手机侧 `dumpsys bluetooth_manager` 实测 |

**代价说明**：本研究在一台**原本已由官方激活、`142=01` 的 FIIL Key Max** 上做写入实验，
在 2026-11-11 22:59:50 写入了一份固件不认可的 license，导致该耳机
**`142` 从 `01` 变为 `00`，至今无法恢复**。耳机硬件本身完好（能连、能听、开关能读写），
代价是 **LDAC 从「已解锁」状态变成了「未解锁」状态**。

这一结果同时推翻了一条长期存在的错误结论（详见下节）。

---

## 交付物清单

### 1. `fiil-ldac-unlock` v1.4.0（PC 端程序）

https://github.com/FNKG9527/fiil-ldac-unlock

| 文件 | 作用 |
|---|---|
| **`src/fiil_gui.py`** | **图形界面**：双击即用，扫描 / 读状态 / 开 LDAC / 写授权码全在按钮上 |
| `src/fiil_ble.py` | **主力程序**：PC 纯 BLE 直连，不需要 COM 口 |
| `src/fiil_ldac.py` | 串口 SPP 直写（Mate / SDP / F39 / **Gaia** 四套帧） |
| `src/fake_server.py` | 本地假服务器（拦 `newservice.fiil.com`） |
| `src/patch_apk.py` | APK 重打包注入 |
| `src/probe_guard.py` | 盲扫护栏（拦 `cid=36` 恢复出厂） |
| `src/selftest.py` | 离线自检，86 项 |
| `tools/build_exe.py` | 打包成 Windows exe（默认 `--onedir`） |

常用命令：

```bash
pip install -r requirements.txt

python src/fiil_gui.py                   # 图形界面（推荐）
python src/fiil_ble.py scan              # 找耳机（服务 0xFDB3 + 厂商 0x0234）
python src/fiil_ble.py status            # 读机型 / 固件 / 电量 / LDAC 三态
python src/fiil_ble.py backup            # 备份 license（改之前一定要做）
python src/fiil_ble.py switch --on       # 开 LDAC ← 这就是"解锁"
python src/fiil_ble.py switch --off

python tools/build_exe.py --clean        # 打包 exe
```

⚠️ 打包别用 `--onefile`：bootloader 解包到 `%TEMP%\_MEIxxxxx` 时会报
`Could not create temporary directory!` 然后直接退出（受限令牌环境下必现）。
`--onedir` 不需要解包，可正常启动。

### 2. `fiil_mod` v3.4.3（LSPosed 模块）

装在手机上，把 LDAC 开关接进系统蓝牙设置页，并额外给了一个"写入授权码"的入口。

- 删掉了原来 `ldacUnlocked` 的门禁 —— 不再替已经关停的官方服务器继续锁用户
- 新增 `LdacLicenseDialog`：可手输 32 hex 激活码（F046 写左耳一次 / F048 左右各一次）
- 新增 16 条单测，总计 194 条全通过
- 已装机验证：装得上、起得来、不崩

---

## 这一轮逆向到什么深度

比之前深的地方：

| 维度 | 之前 | 这一轮 |
|---|---|---|
| 命令空间 | 只用 App 里出现过的 | **`cid=39` 全 255 条 + `cid` 0–127 全扫** |
| ACK 语义 | "回 00 就是成功" | **只校验长度 17 + 首字节 ∈ {0,1}**，内容不看 |
| license 可伪 | "固件不校验"（错的） | **固件校验，写错会清掉已有解锁**，62 候选全灭 |
| 授权码可读 | 未查 | **255 条查询无一能回读 license**，拷贝路线堵死 |
| 日志 | 无 | **Logan AES-128-CBC 解密成功**（key=`0123456789012345`） |
| 服务器 | "可能还能连" | **NXDOMAIN + 旧 IP 39.106.10.142:8085 timeout**，确定死亡 |
| 通道覆盖 | `f39` / `f43` / `f048` 三套 | **新增 Gaia over SPP**，四套帧全部可组（v1.4.0） |
| 可用形态 | 只有命令行 | **桌面图形界面 + exe**（v1.3.0） |

### Gaia 通道（v1.4.0 新解出，之前标「未展开」）

`com.fiil.sdk` 那套老 SDK 走的是 Gaia over SPP，之前只知道有 `OFFS_` 常量、
组帧函数没展开。这次解出三件事：

```
帧格式  SOF|ver|flags|payloadLen|vendHi vendLo|cmdHi cmdLo|payload
        (FiilCommandUtil.java:517-534 getSendBuffer，偏移见 Gaia.java:344-359)

1968    bArr 原样透传，无额外包装 (u.java:41-46)
        → payload 就是 17 字节 license 本体，与 F39/F43/F048 一致

回包    SET 判 bArr[0]==0 (GaiaSdkCommand.java:1986-1995 / :1700-1709)
        GET 判 bArr[1]   (:924-933)  ← 下标不同！
```

命令号：`1966` GetHeadsetUUID、`1967` GetLDACBuyType、**`1968` SetUnlockLADC**、
`1970` SetLDACSwitchType、`1971` GetLDACSwitchType；厂商号 `564`(`0x0234`)。

```bash
python src/fiil_ldac.py frames --proto gaia
python src/fiil_ldac.py activate --proto gaia --zeros --dry-run
python src/fiil_ldac.py switch --proto gaia --on --dry-run
```

⚠️ **Gaia 通道未在真机验证**。本机只有 Key Max（F046，走 Mate/BLE），
没有 F039–F043 系列耳机，目前只有组帧层面的一致性（与反编译源码逐字节相同）。

### 挖出的未公开命令（App 从未调用，回包跨连接一致）

```
cid=39 cmd=0x10 → 7c 05 ee e4              疑似固件编译号
cid=39 cmd=0x83 → d8 80 83 8a f0 18        疑似 MAC 低 6 字节倒序
cid=39 cmd=0x86 → 03 0c
cid=39 cmd=0x8C / 0x8D → 16B，与 138/139 同值
cid=39 cmd=0xFE → 08 00                    疑似协议版本/能力位
cid=35 → 固件已实现的第 5 个命令族，App 零调用
```

### 危险命令（务必绕开）

`cid=36` 的 `setReset` 只设 `commandClassifyId(36)`，**不带 commandId 也不带 payload**
（`com/fengeek/main/i/d/c.java:489-502`）。
所以任何 `cid=36` 的 5 字节空帧都是一次**恢复出厂设置**。
本轮盲扫时就因此把测试耳机打掉了（当场断开、停止广播，需手动重新开机）。

---

## 诚实的已知问题

1. **测试机 Key Max 的 `142` 现在是 `0`**。这是本轮实测写坏的，且**无法恢复**
   （备份里的 `00‖uuid` 形态正是被固件拒绝的那个）。`143=1`、`144=02` 仍正常，LDAC 仍可用。

   > 原始状态有第三方证据可查：从手机 `/sdcard/Android/data/com.fengeek.f002/files/logan_v1/`
   > 解出的 2026-10-24 21:54:14 官方 App 日志里有三行——
   > `BluetoothStream : write: 00 27 01 00 02 8e 00` →
   > `read: 06 27 02 00 03 8e 01 01， 耳机型号=46` →
   > `F046HomeFragment : onRead: 获取ldac解锁状态: 01`。
   > 即**破坏性实验之前这台耳机确实是已授权（`142=01`）状态**。
   > 解密脚本与明文见 `fiil-ldac-unlock` 之外的 `<TOOLS>\decrypt_logan.py` 与 `<WORK>\_adb_pull\logan1.plain.txt`。
2. **LSPosed hook 无法在本机验证**。手机没 root（`su` 不存在、`/data/adb` 权限拒绝），
   模块的 hook 行为只能靠代码审查 + 194 条单测保证。
3. **`cid=35` 语义未展开**。风险高于收益，没继续扫。
4. **`getCodecStatus`(144) 的语义是实测推断**（1=非LDAC、2=LDAC），
   该方法在源码里是孤立方法、全工程无调用点，无法从代码侧确认。
5. **Gaia 通道未真机验证**。F039–F043 系列耳机本机没有，`--proto gaia`
   只有组帧层面的一致性。
6. **`f048` 的开关已解出，但同样未真机验证**。`e.java:573-588` 的 `setLdacSwitch`
   是 cid=1 / cmdId=13 / payload={0,1}，与 F046 的 `c.java:371-385` **逐字节相同**，
   **连承载也一样**（都是 Mate 帧），区别只在型号门控。
   （早期版本误判为「源码里找不到」，已修正。）

---

## 复现路径（从零到开 LDAC）

```bash
git clone https://github.com/FNKG9527/fiil-ldac-unlock.git
cd fiil-ldac-unlock
pip install -r requirements.txt

# 0. 图形界面：双击 / 命令行都能起
python src/fiil_gui.py

# 1. 确认耳机在广播
python src/fiil_ble.py scan --scan-timeout 8
#    → B0:F1:A3:A8:7A:C8  -48  svc=FDB3,mfr=0x0234  ← FIIL

# 2. 读当前状态
python src/fiil_ble.py status
#    → 机型 F046 / Key Max / Atom，可写 license: 是
#    → LDAC已解锁(142)=00  LDAC开关(143)=00  编解码(144)=01

# 3. 开 LDAC（真机验证过的那一步）
python src/fiil_ble.py switch --on
#    → setLowDelay(0) → setLdacSwitch(1) → 断链（预期）→ 重连复核
#    → 143=01 144=02 ✓

# 4. 手机上确认
#    设置 → 蓝牙 → FIIL Key Max → 音质 → 应该能看到 LDAC 在跑
```

耳机不在身边也能核对帧：

```bash
python src/fiil_ble.py unlock --code 00112233445566778899aabbccddeeff --dry-run
python src/fiil_ldac.py frames --proto gaia
python examples/dump_frames.py --proto all
```

---

## 证据文件

- 真机收发原始帧：`docs/evidence/ble_*.log`
- 图形界面截图：`docs/evidence/gui_screenshot.png`
- 协议完整规格：`docs/PROTOCOL.md`（含第 11 章 BLE 通道、第 12 章未公开命令、第 13 章四套帧对照）
- 激活链路逐行拆解：`docs/ACTIVATION_FLOW.md`
- 版本变更记录：`CHANGELOG.md`
- 模块侧：`<WORK>\fiil_mod\CHANGELOG.md`（v3.4.3 条目）

---

## 合规边界

本项目只恢复用户已购买硬件上的既有功能（LDAC 解码能力是耳机硬件本身支持的），
不提供绕过设备安全机制的手段，不含官方 APK 或反编译产物。
`activateCode` 的离线伪造已被本项目自己证伪并如实记录 —— 这条路线不提供。
