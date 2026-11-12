# 更新日志

本文件格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [1.4.2] - 2026-11-12

**机型矩阵版。** 把「哪些机型有授权这件事」查清楚了，顺带回答了 issue #1 的两个问题。

### 新发现

- **只有 F046 / F048 存在「授权/解锁」概念。** 七个机型族逐类核对
  （`com/fengeek/main/i/d/{b,c,d,e,f,g,h}.java` → F045/F046/F047/F048/F049/F051/F053）：
  - F046 (`c.java`)、F048 (`e.java`)：同时有 `setLdacSwitch`、`getLdacSwitchStatus`、
    `getLdacUnlockStatus`(142)、`setActivationLdac`(1/12)，App 里也有激活入口
  - **F049 (`f.java`) / F051 (`g.java`) / F053 (`h.java`)：能开关 LDAC，但没有
    `getLdacUnlockStatus`、没有 `setActivationLdac`，三个包下搜不到任何「激活」字样或
    `UnlockLDACActivity` / `LDACProductRegistActivity` 引用 —— 这三款的 LDAC 直接可用，不存在解锁动作**
  - F045 (`b.java`) / F047 (`d.java`)：连 LDAC 命令都没有
- **`setLdacSwitch` 五处实现逐字节相同，且都没有授权检查。** 只检查「回调非空」与
  「`com.fengeek.main.i.a.f31837c`（耳机已连接）」，然后 `cid=1` / `cmdId=13` / payload `{0/1}`。
  → 授权不拦截这条命令本身，但**命令能下发 ≠ 功能能生效**：`142=00` 时耳机不向手机宣告
  LDAC 能力，`143` 写成 1 也传不出 LDAC（1.4.3 修正，见下）。
- **F048 在 `142=0` 时是把控件整个隐藏，不是禁用。** `F048HomeFragment.java:729`
  `f24504r.setVisibility(bArr[0] == 0 ? 8 : 0)` —— `View.GONE`。用户看不到开关，会误以为
  「必须解锁才能用」，但底层 `setLdacSwitch`（`e.java:573-588`）根本没有授权分支。

### 新增

- `src/fiil_ble.py` 增加两张机型能力表：
  - `UNLOCK_CONCEPT_EAR_TYPES = {46, 48}` —— 有「授权/解锁」概念的机型
  - `LDAC_SWITCH_CAPABLE_EAR_TYPES = {46, 48, 49, 51, 53}` —— 能开关 LDAC 的机型
  （原有的 `LICENSE_CAPABLE_EAR_TYPES` 保持不变，语义是「能写 license」）
- `docs/PROTOCOL.md` 新增 **§7.3 哪些机型存在「授权」这件事**，含七族四方法的完整矩阵、
  `setLdacSwitch` 逐字节相同的证据、以及「F048 是把控件隐藏而不是禁用」的说明。

### 回答 issue #1 的两个提问

issue #1（F048 / GS Links / fw 1.3.3.0）里问了两个问题，现在都能从源码直接给答案：

1. **「是否存在『生效/commit』的第二条命令？」——不存在。**
   全仓库 `setActivationLdac` 只有 6 个调用点，全部是「写 license」本身：
   `F046HomeFragment.java:95`（取消激活，全零）、`F046UnlockLDACActivity.java:116`（单次写左耳、
   首字节固定 0）、`UnlockLDACActivity.java:238/244`（type=3 左右各一次）、
   定义处 `c.java:287` / `e.java:442`。没有任何跟随的 commit/apply 命令。
   所以「提示成功但 142 仍为 0」只说明 **license 内容没通过固件校验**，不是漏了第二步。
2. **「F048 的 license 是 MAC/签名校验吗？算法或密钥有来源吗？」——是内容校验，但算法不可离线还原。**
   F046 上累计 62 个候选（含自洽的 `00‖设备UUID`、全零、15 种校验和、43 种派生）全部被拒，
   且写错会**清掉**已有解锁状态。客户端零生成逻辑（139 处 `activateCode` 全部来自服务器 JSON）、
   原生层无相关算法（29 个 `.so` 里 `libBluetoothData.so` 只做数组切分）、
   服务器 `newservice.fiil.com` 已 NXDOMAIN。**只能拿到真实 activateCode 才能写成功。**

### 测试

- `python src/selftest.py` → 93 通过，0 失败
- `python -m ruff check src examples tools` → All checks passed!

---

## [1.4.1] - 2026-11-12

**修正版。** 1.4.0 里关于 F048 的两条结论都是错的，这次连帧带文档一起改掉。

### 修正

**F048 走的是 Mate 帧，不是 SDP。**

1.4.0（以及更早的 1.0.0）一直把 F048 归到 SDP 那一套，`sdp_frame(...)` 组
`FF 01 00 13 02 34 00 01 0C 11 …`。**错的。**

判据链：

1. `com/fengeek/main/i/d/e.java` 的每个方法末尾都是
   `a.getInstance().addCommand(aVar)`（`a` = `com.fengeek.main.i.d.a`，CommandManager）
2. CommandManager 的 `sendCommand()`（`com/fengeek/main/i/d/a.java:235-243`）
   **只有一句发送**：`com.fengeek.main.i.b.getInstance().writeMate(aVar, this.f31875h);`
3. `writeMate`（`com/fengeek/main/i/b.java:237-262`）生成的是 Mate 帧
4. 同文件 `:264` 那个 SDP 版 `write(baseCommand, handle)` **全工程无人调用**

所以 F048 的线格式与 F046 **完全一致**：

```
00 01 01 00 13 0C 11 00 00×16     ← 写左耳 license（24 字节）
00 01 01 00 03 0D 01 01           ← 开 LDAC（8 字节）
```

**F048 的 `setLdacSwitch` 一直是存在的。**

`e.java:573-588` 就是完整的实现，cid=1 / cmdId=13 / payload={0,1}，
与 F046 的 `c.java:371-385` 逐字节相同——**连承载也一样**，两者区别只在型号门控。
1.4.0 初版写「F048 的开关命令号未在源码中定位」，是只搜了 `c.java` 导致的
（七个机型族分散在 `b.java`=F045 … `h.java`=F053，方法名同构但不在同一文件）。

### 新增

- `mate_frame(classify_id, command_id, payload, seq)` —— Mate 组帧，与
  `b.java:237-262` 逐字节对齐；`commandId == 0` 时正确省略 `(len+2, cmdId)` 两字节
- `f048_switch_frame(on)` —— F048 的 LDAC 开关
- `switch --proto f048` 现在可用（之前直接报错返回 2）

### 测试

`src/selftest.py` 第 2 节 F048 部分重写，新增 7 项（Mate 帧长度、右耳首字节下标、
开/关帧、与 F046 逐字节等价、cid/cmdId、`cmdId=0` 省略）→ **93 通过，0 失败**。

### 文档

- `docs/PROTOCOL.md` §5 由「F048 SDP 通道」改为「F048 通道」，5.1 整节重写为
  「帧格式：**Mate**，不是 SDP」并给出四步判据链；5.4 补「SDP 与 Mate 是两条互不相干的链路」对照
- `docs/PROTOCOL.md` §13 对照表：F048 从 SDP 列挪到 Mate 列；SDP 列注明承载是
  `DeviceCommManager.sendRequest`
- README / en README 的 `--proto` 表、类型表、CHANGELOG 1.4.0 补记、
  DELIVERY_REPORT、ACTIVATION_FLOW 注释同步修正

> **教训**：`b.java` 同时存在 `writeMate`（活）和 `write(baseCommand)`（死）两个组帧函数，
> 只看后者会得出完全相反的结论。判断某条命令走哪套帧，要**追到 `sendCommand()` 这一层**，
> 看它实际调用的是谁，而不是看哪个函数名更像。

---

## [1.4.0] - 2026-11-12

**Gaia 通道版。** 之前 `--proto` 只有 `f39`/`f43`/`f048` 三套，走 `com.fiil.sdk`
的老机型（F039/F040/F041/F042/F043）一直是空白。这次把 Gaia over SPP 的组帧、
命令号和回包判据全部解出来并实现，`--proto gaia` 可用。

### 新增

- `src/fiil_ldac.py` 新增 `gaia_frame(vendor_id, command_id, payload, new_protocol)`
  - 组帧依据 `com/fiil/sdk/command/FiilCommandUtil.java:517-534 getSendBuffer`，逐字段一致：
    `SOF | ver | flags | payloadLen | vendHi vendLo | cmdHi cmdLo | payload`
  - 偏移常量来自 `com/fiil/sdk/gaia/father/Gaia.java:345-355`（`OFFS_SOF=0`、`OFFS_VERSION=1`、
    `OFFS_FLAGS=2`、`OFFS_PAYLOAD_LENGTH=3`、`OFFS_VENDOR_ID_H=4`、`OFFS_COMMAND_ID_H=6`、
    `OFFS_PAYLOAD=8`）
  - ⚠️ `payloadLen` **只算 payload**，不含 8 字节头 —— 与 SDP（长度含命令段）和 Mate
    （长度含 cmdId）的含义都不同，三种帧混用时最容易在这里错
- 新增 `gaia_activate_frames` / `gaia_switch_frame` / `gaia_query_frame` /
  `gaia_ack_ok` / `gaia_switch_state`
- 新增 Gaia 命令号常量（`Gaia.java:229-333` 逐条核对）：
  `GAIA_CMD_GET_HEADSET_UUID=1966`、`GAIA_CMD_GET_LDAC_BUY_TYPE=1967`、
  **`GAIA_CMD_SET_UNLOCK_LDAC=1968`**、`GAIA_CMD_SET_LDAC_SWITCH=1970`、
  `GAIA_CMD_GET_LDAC_SWITCH=1971`；`GAIA_VENDOR_FF=564`、`GAIA_SOF=0xFF`、
  `GAIA_PROTOCOL_VERSION=1`、`GAIA_NEW_PROTOCOL_VERSION=0xF1(=241)`
- `--proto` 增加 `gaia` 取值，`activate` / `switch` / `frames` 三个子命令均已接入

### 逆向补充（本轮新解出的三处，之前是未知项）

1. **Gaia 1968 的 payload 布局**（CHANGELOG 1.0.0 曾标「未展开」）：
   `u.java:41-46` 的 `setUnlockLDAC(byte[] bArr, …)` 是
   `getSendBuffer(VENDOR_FF, 1968, false, bArr)` —— **bArr 原样透传，没有任何额外包装**。
   调用方 `FiilManager.java:1526-1531` 也只是转调。所以 payload 就是 17 字节 license 本体。
2. **Gaia SET 回包判据**：`GaiaSdkCommand.java:1986-1995 analysisSetUnlockLADC` 与
   `:1700-1709 analysisSetLDACSwitchType` 都是 `onResult(bArr[0] == 0)` —— **首字节为 0 才算成功**。
   但 `:924-933 analysisGetLDACSwitchType` 取的是 **`bArr[1]`**，两个下标不同，容易踩。
3. **命令号→解析函数的映射**由反射查表：`ReflectUtils.java:8-23 getCommandMethod` 反射读
   `com.fiil.sdk.config.Config.sMap`（`Config.java:312-326` 逐条 `put`），
   `getGaiaIntValue`/`getGaiaByteValue`（`ReflectUtils.java:25-53`）反射读 `Gaia` 的静态字段。
   所以这些数值在源码里是可静态确定的，不必抓包。

### 修正

- `activate --dry-run` / `switch --dry-run` 之前仍强制要求 `--port` 或 `--addr`，
  耳机不在身边时没法核对帧。现在 `--dry-run` 不再要求设备。
- `switch` 新增 `--dry-run`（之前只有 `activate` 有）。四个协议都能离线看帧。

### 测试

- `src/selftest.py` 新增第 2 节末尾 13 项 Gaia 检查：1968 左右耳组帧逐字节、
  1970/1971/1966/1967 帧、`VENDOR_FF=564`、头长 8、ACK 首字节 0/非 0/空包三种判据、
  1971 回包取 `[1]` 与长度不足返回 `None`。
- 自检总数：**86 通过，0 失败**（1.3.0 是 73）。

### 已知问题

- Gaia 通道**未在真机验证**。本机只有 Key Max（F046，走 Mate/BLE），
  没有 F039/F040/F041/F042/F043 系列耳机，`--proto gaia` 目前只有组帧层面的正确性
  （与反编译源码逐字节一致）。
- `fiil_ldac.py` 的 `read` 子命令仍只实现 F39。Gaia 侧已备好 1966/1967/1971 三个查询帧，
  但没有做回包解析与状态打印。

### 补记（同日）：F048 的开关其实一直都在

1.4.0 的初版里我写过「`f048` 的 LDAC 开关命令号未在源码中定位」——**这是错的**。
`e.java:573-588` 就有完整的 `setLdacSwitch`：

```java
aVar.setCommandClassifyId(1);
aVar.setCommandId(13);
aVar.setBuffer(new byte[]{ z ? (byte) 1 : (byte) 0 });
```

即 **cid=1 / cmdId=13 / payload={0,1}，与 F046 的 `c.java:371-385` 逐字节相同**，
而且**连承载也一样**（都是 Mate 帧）——两者的区别只在型号门控。

```
FF 01 00 03 02 34 00 01 0D 01 01     ← 开（11 字节）
FF 01 00 03 02 34 00 01 0D 01 00     ← 关
```

之所以漏掉：只搜了 `c.java`（F046 类）。七个机型族分散在
`b.java`=F045 / `c.java`=F046 / `d.java`=F047 / `e.java`=F048 / `f.java`=F049 /
`g.java`=F051 / `h.java`=F053，方法名高度同构但**不在同一个文件里**。

`switch --proto f048` 现已可用（`f048_switch_frame()`），自检加 3 项 → **89 通过**。
> 教训：按方法名搜单一文件会漏；要么 `grep -r` 全目录，要么按「机型族 → 文件」映射逐个查。

---

## [1.3.0] - 2026-11-12

**图形界面版。** 之前交付的都是命令行，这次补上真正的「程序」：一个能双击打开的
Windows 桌面界面，把「扫描 → 读状态 → 开 LDAC」变成点按钮。

### 新增

**程序**

- `src/fiil_gui.py` — **图形界面（tkinter，零额外依赖）**
  - 设备区：扫描 / 读状态 / 备份 UUID 三个按钮 + 扫描结果下拉列表
  - 状态区：设备名、固件、机型、电量、`142`（已解锁）、`143`（开关）、`144`（编解码）
  - 操作区：开 LDAC / 关 LDAC / 写后重连复核 / 写入授权码 / 取消激活
  - 收发日志框逐行显示每一帧 TX/RX，同时照常写入 `docs/evidence/`
  - BLE 全部跑在后台线程的独立 asyncio 循环里，界面不阻塞
  - 破坏性操作（写授权码、取消激活）先弹确认框，文案写明「写错会清掉解锁且无法恢复」
  - 运行：`python src/fiil_gui.py`
- `tools/build_exe.py` — 打包脚本，默认 `--onedir`
  - 产物 `dist/FiilLdacUnlock/FiilLdacUnlock.exe`（2.8 MB，加 `_internal/` 共 29.4 MB）
  - ⚠️ **单文件模式（`--onefile`）在受限令牌 / 沙箱环境里会失败**：
    bootloader 解包到 `%TEMP%\_MEIxxxxx` 时报 `Could not create temporary directory!`
    然后直接退出。同一份代码用 `--onedir` 不需要解包，可正常启动。
    所以默认 one-dir；`--onefile` 保留给普通环境。

**工具**

- `src/fiil_ble.py` 新增 `parse_activate_codes(text)`：把 `"<32hex>"` 或
  `"<32hex>,<32hex>"` 拆成 1~2 个 16 字节块（与 `UnlockLDACActivity.java:207`
  的 `split(",")` 对齐）。黑/大写/空白都接受，长度不对或非 hex 抛 `ValueError`。
  GUI 与 CLI 共用这一份实现。
- `src/fiil_ble.py` 的 `unlock --code ... --dry-run` **改为完全离线**：
  不连耳机，直接打印左右 license 与 F046/F048 实际会发出的帧。耳机不在身边也能核对。

### 修正

- `fiil_ble.py unlock --code` 之前只认单段激活码，**F048 的右耳 license 会复用左耳的内容**。
  现在支持两段（`--code "左,右"`），并把 `code_right` 显式传下去。

### 测试

- `src/selftest.py` 新增第 7 节「激活码解析 / GUI 复用」14 项。
- 自检总数：**73 通过，0 失败**（1.2.0 是 59）。

---

## [1.2.0] - 2026-11-12

**盲扫版。** 把协议的命令空间整个扫了一遍，挖出 6 条未公开查询命令 + 1 个未使用的命令类别，
并**修正了 1.1.0 对 ACK 码的理解**。同时新增了一个防误发的安全模块（因为扫的时候真把耳机打掉了）。

### 新增

**工具**

- `src/probe_guard.py` — **盲扫安全护栏**
  - 内置 `DANGEROUS_CIDS`（`cid=36` 裸帧 = 恢复出厂设置）、`STATEFUL_CIDS`（会改状态的 12 个 cid）
  - `is_safe_cid()` / `is_safe_query()` / `assert_safe()`，供任何扫描脚本复用
  - 起因：盲扫 cid 时无意对 `cid=36` 发了空帧，耳机当场断开并停止 BLE 广播
- `src/fiil_ble.py` 新增未公开命令常量：`Q_UNKNOWN_10/83/86/8C/8D/FE`、`CID_UNKNOWN_35`、`CID_SET_RESET`
- `src/fiil_ble.py` 的 `status` 子命令末尾补一行提示，说明 142 与 143/144 是独立路径

**文档**

- `docs/PROTOCOL.md` 新增「12. 未公开命令（盲扫发现）」
  - 12.1 `cid=39` 查询族全扫 255 条的完整命中表
  - 12.2 `cid` 命令类别全扫 0–127 的结果（`cid=35` 是 App 完全未使用的第 5 个命令族）
  - 12.3 ⚠️ `cid=36` 裸帧 = 恢复出厂设置（含源码依据与官方 UI 文案佐证）
  - 12.4 **ACK 码的真实含义**（长度 + 首字节校验）

### 修正

- ❌ **1.1.0 说「ACK 只表示命令被收到」——不够准确。** 逐长度实测后确认：
  `setActivationLdac` 的 ACK **只校验「长度 17」+「首字节 ∈ {0,1}」**，完全不看后 16 字节内容。

  | payload | ACK |
  |---|---|
  | 17 字节，首字节 `00`/`01` | `00` |
  | 17 字节，首字节 `02`/`03`/`FF` | `01` |
  | 长度 ≠ 17 | `01` |

  所以 ACK `00` = **格式合法**，与激活码对错无关（这解释了 62 个错误候选为何全拿到 `00`）。
  唯一可信的成功判据仍然只有回读 `142`。

### 新发现

- **固件里没有「回读已写入 license」的命令**。`cid=39` 全 255 条扫完，没有任何回包长度 ≥ 17 且含激活码字段
  → **无法「从一台已授权耳机拷贝 license 到另一台」**，这条路彻底堵死。
- 6 条未公开查询命令（App 从未调用），回包跨连接完全一致（非 nonce）：
  - `0x10` → `7c 05 ee e4`（疑似固件编译号）
  - `0x83` → `d8 80 83 8a f0 18`（疑似 MAC 低 6 字节倒序）
  - `0x86` → `03 0c`
  - `0x8C` / `0x8D` → 16 字节，与 `0x8A`/`0x8B` 同值（UUID 的第 3、4 条查询通道）
  - `0xFE` → `08 00`（疑似协议版本 / 能力位）
- `cid=35` 是固件已实现、但 FIIL+ 源码里**没有任何调用点**的命令类别。

### 已知问题

- ⚠️ 盲扫过程中对 `cid=36` 发了空帧（= `setReset` 恢复出厂），测试机 Key Max 断开并停止 BLE 广播，
  需要**手动重新开机**才能继续测试。相关保护已固化为 `src/probe_guard.py`。
- `cid=35` 的具体命令语义未展开（需逐 cmdId 盲扫，风险高于收益，未做）。

---

## [1.1.0] - 2026-11-11

**真机验证版。** 本次更新在一副 FIIL Key Max（F046，固件 3.0.1.1）上做了完整的收发实测，
既新增了一条可用的链路，也**推翻了自己 1.0.0 的一条核心结论**。

### 新增

**工具**

- `src/fiil_ble.py` — **PC 端纯 BLE 直连工具**（方案五，真机验证）
  - 走 BLE GATT：服务 `0000fdb3`、写 `0000ff17`、通知 `0000ff18`
  - 首次实现「不需要在 Windows 里配出 COM 口」的路径
  - 子命令：`scan` / `models` / `status` / `backup` / `switch` / `unlock` / `raw`
  - 按官方顺序实现开关：开 LDAC 前先 `setLowDelay(0)`（`F046HomeFragment.java:395-405`）
  - 切 LDAC 会重建 A2DP 链路，程序自动重连并复核 `143`/`144`
  - 所有收发原始帧写入 `docs/evidence/ble_*.log`
- `src/selftest.py` 新增第 5 节「BLE 组帧 / 解帧」共 21 项检查
  - Mate / SDP 组帧、真机回包解帧、SET ACK 短帧、半帧保留、非法帧头重同步、机型能力表

**文档**

- `README.md` 新增「方案五：PC 端纯 BLE 直连」，含 UUID 表、帧格式、实测记录
- `docs/PROTOCOL.md` 新增「11. BLE GATT 直连通道」，含服务表、握手、LDAC 命令表、实测帧
- `requirements.txt` 增加 `bleak>=0.22`

### 修正

- ❌ **1.0.0 断言「固件不校验 license 内容」——是错的。**
  真机实测：写 `00 ‖ 设备UUID`、全零、15 种校验和、43 种派生值，ACK 全部回 `00`（成功），
  但 `142`（`getLdacUnlockStatus`）全部变回 `00`，**写错内容会清掉已有解锁状态**。
  - 结论 1：**ACK 只表示命令被收到，不代表 license 被接受**，唯一判据是回读 `142`
  - 结论 2：`activateCode` 含服务器侧私有盐/密钥，**离线伪造已被证伪**（累计 62 个候选全灭）
  - 结论 3：官方后门的全零 license 只在 **F039** 上适用，不能反推到 F046/F048
  - 同步修正 `docs/PROTOCOL.md` 7.1、`docs/ACTIVATION_FLOW.md` 第 7 节、`README.md` FAQ
- `docs/PROTOCOL.md` 「10. 未确认项」按本轮实测更新：「全零 license 在 F043/F048 上的效果」
  由 `⚠️ 静态推断` 改为 `❌ 已被实测否定`；新增 `activateCode 生成算法`、`getCodecStatus 语义` 等条目

### 新发现

- ~~**`142`（授权）与 `143`（开关）是两条独立路径**~~ —— **此结论已于 1.4.3 推翻，保留为教训。**
  当时据 `142=00 / 143=01 / 144=02` 判定「LDAC 依然实际工作」，但读数时手机并未连接耳机，
  `144=02` 是孤立状态、没有参考意义。手机侧实测证明 `142=00` 时
  `mCodecsSelectableCapabilities` 只有 AAC/SBC，A2DP 只能协商出 AAC。
- 连接后**必须先发 `setUnlock` 握手**（`cid=39 cmd=255 payload={0x02,0x34}`），否则后续命令全部静默。
- `0000ff16` 在实机上**同样可写**（1.4.3 更正）：GATT 属性为 `read,write`，
  与 `0000ff17` 写入效果完全一致。早期「ff16 不支持写」的结论来自一次未加握手的尝试。
- Key Max 的**左右耳 UUID 相同**（设备级），与 F048「左右各一次」的设计不同。
- `getPID`（`cid=39 cmd=132`）回包**第 2 字节**才是机型号（`00 2E 01` 中 `0x2E`=46），
  七个机型族 MainFragment 都按 `buff[1]` 校验。
- SPP 路径在 Windows 上实测不可用：COM3 能打开但握手无回包（Windows 的 COM 口只是 SDP 注册结果）。

### 已知问题

- 本项目在验证过程中**把测试机 Key Max 的 `142` 从 `01` 写成了 `00`**（解锁状态被清）。
  `143`/`144` 仍正常，LDAC 仍可用。备份文件里的 `00‖uuid` 形态正是被固件拒绝的那个，
  **无法用它恢复 `142=01`**。这条如实记录在此，作为「不要在生产设备上试写未知 license」的警示。
- `src/fiil_ble.py` 使用了 `X | None` 类型语法，与 `ruff.toml` 的 `target-version = "py38"` 不一致；
  实际运行需要 Python ≥ 3.10。后续会把 target 调整为 py310 或改写注解。

---

## [1.0.0] - 2026-10-26

首个公开版本。

### 新增

**工具**

- `src/fiil_ldac.py` — 串口直写工具
  - 支持 F39 / F43 / F048 三套帧格式
  - 子命令：`list` / `frames` / `read` / `backup` / `activate` / `switch`
  - `frames` 子命令可离线打印帧字节，不连接设备
- `src/fake_server.py` — 本地假服务器
  - 模拟 `newservice.fiil.com` 激活接口
  - 三种模式：`zero` / `random` / `echo`
  - 附带 `sn/reg`、`activation/order`、`activate` 及通用成功壳
- `src/patch_apk.py` — APK 重打包注入
  - 自动定位 `F048HomeFragment.o()` 并注入
  - 三个 fallback 注入点（F048 / F043 / F039）
  - 自动处理 `.locals` 扩容、回编译、zipalign、签名
- `src/selftest.py` — 离线自检，22 项检查
- `examples/dump_frames.py` — 打印各协议帧
- `examples/probe_headset.py` — 只读探测

**文档**

- `docs/PROTOCOL.md` — 三套帧格式与四条通道的完整规格
- `docs/ACTIVATION_FLOW.md` — 激活链路逐步拆解（含文件行号）
- `docs/TROUBLESHOOTING.md` — 常见问题
- `docs/en/README.md` — 英文版 README
- `README.md` — 中文主文档

**仓库**

- GPL-3.0 代码许可 + CC BY-SA 4.0 文档许可
- `NOTICE` / `DISCLAIMER.md` / `CONTRIBUTING.md` / `SECURITY.md` / `CODE_OF_CONDUCT.md`
- GitHub Actions CI：`ruff` + `selftest`（Linux / Windows / macOS）
- Issue 模板与 PR 模板

### 已知限制

- F43 `subId` 左右耳区分方式未在真机验证
- F048 未找到类似 CC Pro2 的隐藏后门
- 全零 license 在 F043 / F048 上的效果为静态推断
- Gaia 1968 的 payload 确切布局未展开

### 逆向依据

FIIL+ 3.5.2（`com.fengeek.f002`），jadx 静态分析。
服务器状态实测于 2026-10-26：`newservice.fiil.com` / `sapp.fengeek.com` / `ms.fiil.com` 全部 NXDOMAIN。

---

## 版本号约定

- **主版本**：协议描述有破坏性更正（例如某条帧格式被证明是错的）
- **次版本**：新增机型、新增工具、新增文档章节
- **修订号**：勘误、排版、错别字

---

## 仓库定位变更（2026-11-12）

本仓库已从「LDAC 离线激活工具集」**转为研究记录仓库**：

- **移除全部下载入口**：GitHub Release 已删除（v1.0.0 tag 保留，仅作历史标记，无附件的发布页已不存在）、
  README 与交付报告里不再提供 exe 打包指引作为「下载途径」。
- **公开完整失败过程**：`research/` 目录收录 29 个探针脚本、59 份真机收发日志、66 个候选的测试结果、
  以及四次判断失误的复盘，全部脱敏后公开。
- **明确定位**：这些代码用于复现与观察协议行为，**不是解锁教程**。
  `activateCode` 无法离线伪造，这是四条断头路都已走到底之后的结论。
- **致谢**：issue #1 的报告者 hyxdbb 与 @winfo2005-glitch 独立复现了同一个失败现象，
  报告者还纠正了本项目关于 F048 走 `writeMate()` 而非 SDP 的错误结论。
