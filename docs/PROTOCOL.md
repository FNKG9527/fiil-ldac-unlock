# FIIL LDAC 激活协议规格

> 本文是 FIIL 耳机 LDAC 激活相关的**全部协议事实**，全部来自对 FIIL+ 3.5.2（`com.fengeek.f002`）
> 的静态逆向。每条结论都带 `文件:行号`，路径相对于反编译产物根目录（`jadx_out/sources/` 或 `apktool_out/`）。

**标记约定**

| 标记 | 含义 |
|---|---|
| ✅ | 已在真机验证 |
| 📖 | 仅静态代码阅读，未真机验证 |
| ⚠️ | 静态分析与实测不符，原因未定位 |

---

## 目录

- [1. 激活链路总览](#1-激活链路总览)
- [2. UnlockLDACActivity：四条通道的分派](#2-unlockldacactivity四条通道的分派)
- [3. F39 / Bluetrum 通道](#3-f39--bluetrum-通道)
- [4. F43 SDP 通道](#4-f43-sdp-通道)
- [5. F048 通道](#5-f048-通道)
- [6. Gaia 老协议通道](#6-gaia-老协议通道)
- [7. license 的构造](#7-license-的构造)
  - [7.3 哪些机型存在「授权」这件事](#73-哪些机型存在授权这件事2026-11-12-全机型核对)
- [8. 服务器接口](#8-服务器接口)
- [9. 机型路由表](#9-机型路由表)
- [10. 未确认项](#10-未确认项)
- [11. BLE GATT 直连通道（Mate 帧，1.1.0 新增）](#11-ble-gatt-直连通道mate-帧110-新增)
- [12. 未公开命令（1.2.0 新增，盲扫发现）](#12-未公开命令120-新增盲扫发现)
- [13. 四套帧格式对照（1.4.0 新增）](#13-四套帧格式对照140-新增)

---

## 1. 激活链路总览

📖 全部来自静态分析。

```
用户点「激活」
    ↓
F048HomeFragment.B(View)                    com/fengeek/main/f048/fragment/F048HomeFragment.java:344-350
    ├─ q(true)  检查连接状态（未连接/单耳则拦截）      :686-688
    └─ m()                                        :633
         ├─ FiilManager.getUUID(TRUE,  cb)  读左耳 UUID
         └─ FiilManager.getUUID(FALSE, cb)  读右耳 UUID
              ↓ 两个回调都进 o()
         o()                                      :652-665
              str = hex(left) + "," + hex(right)
              if (str.equals(",")) return;
              networkingGet(h.a.c.f47048a + str, new b())
                    ↓
GET http://newservice.fiil.com/app/headset/activation/info?deviceCode=<左hex>,<右hex>
                    ↓
服务器返回 {"code":"200","msg":"","data":"{\"activateCode\":\"...\",\"orderSn\":\"\"}"}
                    ↓
CcPro2NewEleFragment 内部类 b（p0.d 回调）解析      :222-262
    ├─ activateCode 非空        → UnlockLDACActivity, type=2
    ├─ activateCode 空 + orderSn 空  → 跳购买页
    └─ activateCode 空 + orderSn 非空 → 跳订单页
                    ↓
UnlockLDACActivity                          com/fengeek/main/heat_info_fragment/ldac/UnlockLDACActivity.java
    ├─ onCreate :265-271
    │     f31480g.setText(intent.getStringExtra("activateCode"))
    │     f31482i = intent.getIntExtra("type", 0)
    └─ h() :205-254   ← 真正写码，完全离线
```

**结论：从 `UnlockLDACActivity` 开始不再有任何网络调用。**
`UnlockLDACActivity.java` 全文 273 行，没有 import 任何网络类。

---

## 2. `UnlockLDACActivity`：四条通道的分派

📖 `UnlockLDACActivity.java:205-254`

```java
// 62/65 行：左右耳各 17 字节
byte[] f31485l = new byte[17];   // 左耳
byte[] f31486m = new byte[17];   // 右耳

// h() 内：按逗号切成两段 hex
String[] parts = activateCode.split(",");
byte[] left16  = hexStrToByteArray(parts[0]);   // 16 字节
byte[] right16 = hexStrToByteArray(parts[1]);   // 16 字节

System.arraycopy(left16,  0, f31485l, 1, 16);
System.arraycopy(right16, 0, f31486m, 1, 16);
f31485l[0] = 0;   // 左耳前缀 0x00
f31486m[0] = 1;   // 右耳前缀 0x01

switch (type) {
    case 1:  n0.getInstance().setLDAC(f31485l, f31486m, cb);                    // F43
    case 2:  F39SharedViewModel.sendRequest(
                 F39AppSettingRequest.setActivateLdac(f31485l));
             F39SharedViewModel.sendRequest(
                 F39AppSettingRequest.setActivateLdac(f31486m));
             + getOpenState() + getActivationState();                            // F39
    case 3:  com.fengeek.main.i.d.e.getInstance()
                 .setActivationLdac(f31485l, cb);
             ...setActivationLdac(f31486m, cb);                                  // F048
    default: FiilManager.getInstance().setUnlockLDAC(f31485l, cb);
             ...setUnlockLDAC(f31486m, cb);                                      // Gaia 1968
}
```

其它细节：

| 行为 | 位置 | 说明 |
|---|---|---|
| 单耳拦截 | `:141-145` | `heatsetType == 1` 时 toast「单耳不允许操作」，不执行 `h()` |
| 成功跳转 | `:194-202` | `f31484k == 2` 时跳 `UnlockSuccessToastActivity` |
| hex 解析 | `:154-168` | 两字符一个字节，`hexStrToByteArray` |

---

## 3. F39 / Bluetrum 通道

📖 静态分析 + ✅ 组帧字节已由 `selftest.py` 逐字节核对。

### 3.1 传输层

走 Bluetrum 自定义 BLE 服务（不是 SPP）。命令在 `com.bluetrum.devicemanager` 包下。

### 3.2 帧格式

📖 `com/bluetrum/devicemanager/z.java:36-68`（`b()` 方法）

```
偏移  0      1        2            3                        4
     seq   command  commandType  (total-1)<<4 | index      len
     ↓
     5 字节头 + 本片 payload
```

| 字段 | 取值 | 来源 |
|---|---|---|
| `seq` | 0-15 循环递增 | `z.java:44` |
| `command` | 见下表 | 各 Request 子类 `super((byte)N)` |
| `commandType` | `1`=REQUEST, `2`=RESPONSE, `3`=NOTIFY | `Command.java:25-27`、`Request.java:16` |
| 分片字段 | 高 4 位 = `total-1`，低 4 位 = 当前 index | `z.java:56-62` |
| `len` | 本片 payload 长度 | `z.java:63` |
| 单片上限 | **15 字节** | `z.java:29` `new a0(15)` |

### 3.3 命令表

| 命令 | 值 | 类 |
|---|---|---|
| `APP_SETTING` | `0x01` | `F39AppSettingRequest` → `super((byte)1)` |
| `LDAC_UUID` | `0x27` (=39) | `F39LdacUuidRequest` → `super((byte)39)` |

### 3.4 APP_SETTING 子类型

📖 `com/bluetrum/devicemanager/f39/request/F39AppSettingRequest.java`

| 常量 | 值 | 含义 |
|---|---|---|
| `SETTING_TYPE_ACTIVATE_LDAC` | `12` (`0x0C`) | 写入 license |
| `SETTING_TYPE_LDAC` | `13` (`0x0D`) | 开/关 LDAC |

**写 license**：payload = `[0x0C, 0x11] + 17 字节 license`（共 19 字节，切 2 帧）

```
00 01 01 10 0F 0C 11 00 00 00 00 00 00 00 00 00 00 00 00 00    ← 20 字节
01 01 01 11 04 00 00 00 00                                     ←  9 字节
```

**开关 LDAC**：payload = `[0x0D, 0x01, on?0x01:0x00]`（共 3 字节，单帧）

```
04 01 01 00 03 0D 01 01      ← 开
```

### 3.5 LDAC_UUID 查询

📖 `F39LdacUuidRequest`。payload = 1 字节子命令。

| 子命令 | 值 | 含义 |
|---|---|---|
| `LDAC_ACTIVATION_STATE` | `0x8E` (`-114`) | 查激活状态 |
| `LDAC_OPEN_STATE` | `0x8F` (`-113`) | 查开关状态 |
| `LDAC_LEFT_UUID` | `0x8A` (`-118`) | 查左耳 UUID |
| `LDAC_RIGHT_UUID` | `0x8B` (`-117`) | 查右耳 UUID |

```
00 27 01 00 01 8E      ← 查激活状态
```

响应 payload 是 17 字节 license（首字节 0x00 左 / 0x01 右）。

---

## 4. F43 SDP 通道

📖 静态分析 + ✅ 组帧已核对。

### 4.1 传输层

**SPP / RFCOMM**，两个 UUID（`com/fengeek/utils/l1/v0/i.java:10-13`）：

| 常量 | UUID |
|---|---|
| `f33092a` | `d52b47bc-2dea-42c4-b26d-20252fceeeb3` |
| `f33093b` | `3E48516C-47C0-4FE5-AA96-E039B51039D9` |

协议号（`i.java:16-37`）：2305 到 2312。

### 4.2 帧格式

📖 `com/fengeek/utils/l1/v0/a.java:20-44`（`getPayload()`），
与 `com/fengeek/main/i/b.java:264-291`（`write()`）**完全同构**：

```
FF 01 00 | (len+2) | 02 34 | cmdHi cmdLo | subId | len | values
```

| 字段 | 值 | 说明 |
|---|---|---|
| `FF 01 00` | SOF + 版本 + 标志 | 固定 |
| `len+2` | payload 长度 + 2 | 只算 `values` 长度 |
| `02 34` | 魔数 | `0x02` = 帧类型，`0x34` = 52 |
| `cmdHi cmdLo` | 命令号，大端 | 2311 = `09 07`，2308 = `09 04` |
| `subId` | 协议号低字节 | 见下表 |
| `len` | `values` 长度 | |
| `values` | 实际数据 | |

### 4.3 命令

📖 `com/fengeek/utils/l1/v0/d.java`（license）、`f.java`（开关）

| 操作 | cmdId | subId | values | 类 |
|---|---|---|---|---|
| 写左耳 license | `2311` | `4` | 17 字节 | `d.setLeftLDAC()` :35-39 |
| 写右耳 license | `2311` | `4` | 17 字节 | `d.setRightLDAC()` :41-45 |
| 开/关 LDAC | `2308` | `4` | `[0x01]` / `[0x00]` | `f.setLdac()` :29-33 |

⚠️ **注意**：左右耳用的是同一个 `cmdId=2311, subId=4`，靠 `values[0]`（`0x00`/`0x01`）区分。

**实例**

```
FF 01 00 13 02 34 09 07 04 11 00 00×16     ← 左耳（27 字节）
FF 01 00 13 02 34 09 07 04 11 01 00×15     ← 右耳
FF 01 00 03 02 34 09 04 04 01 01           ← 开 LDAC（11 字节）
```

### 4.4 调用链

📖 `com/fengeek/utils/l1/n0.java:372-392`

```java
public void setLDAC(byte[] left, byte[] right, callback) {
    b();
    this.f32983b.sendRequest(d.setLeftLDAC(left),  ...);
    this.f32983b.sendRequest(d.setRightLDAC(right), ...);
}
```

---

## 5. F048 通道

📖 静态分析 + ✅ 组帧已核对。

### 5.1 帧格式：**Mate**，不是 SDP

> ⚠️ **1.4.1 修正**：本节早期版本说 F048「与 F43 同构、走 SDP」，**这是错的**。
>
> 判据链：
> 1. `com/fengeek/main/i/d/e.java` 的每个方法末尾都是
>    `a.getInstance().addCommand(aVar)`（`a` = `com.fengeek.main.i.d.a`，CommandManager）
> 2. CommandManager 的 `sendCommand()`（`com/fengeek/main/i/d/a.java:235-243`）只有一句发送：
>    `com.fengeek.main.i.b.getInstance().writeMate(aVar, this.f31875h);`
> 3. `writeMate`（`com/fengeek/main/i/b.java:237-262`）生成的就是 Mate 帧
> 4. 同文件 `:264` 那个 SDP 版 `write(baseCommand, handle)` **全工程无人调用**（死代码）
>
> 所以 F048 的线格式与 F046 **完全一致**，只有连接层不同
> （F048 用 RFCOMM UUID `d52b47bc-2dea-42c4-b26d-20252fceeeb3`，
> 见 `F048MainFragment.java:640` / `:728`；F046 用标准 SPP `00001101-…`）。

Mate 帧布局（`b.java:237-262`）：

```
seq | cid | 01 | 00 | (len(payload)+2) | cmdId | len(payload) | payload
```

`commandId == 0` 时省略 `(len+2, cmdId)` 两字节。

### 5.2 写 license

📖 `com/fengeek/main/i/d/e.java:442-457`

```java
public void setActivationLdac(byte[] licenseBuff, infoListener) {
    if (infoListener == null) return;
    if (!com.fengeek.main.i.a.f31837c) {        // 未连接则直接返回
        Log.d(f31884g, "setUnlock: 耳机未连接");
        return;
    }
    com.fengeek.main.i.c.a aVar = new com.fengeek.main.i.c.a();
    aVar.setCommandClassifyId(1);
    aVar.setCommandId(12);
    aVar.setBuffer(licenseBuff);
    aVar.setInfoListener(infoListener);
    a.getInstance().addCommand(aVar);
}
```

| 字段 | 值 |
|---|---|
| `classifyId` | `1` |
| `cmdId` | `12` (`0x0C`) |
| buffer | 17 字节 license |

**实例（Mate 帧，24 字节）**

```
00 01 01 00 13 0C 11 00 00×16     ← 左耳
00 01 01 00 13 0C 11 01 00×15     ← 右耳
```

### 5.3 LDAC 开关

📖 `com/fengeek/main/i/d/e.java:573-588`

```java
public void setLdacSwitch(boolean z, com.fengeek.main.i.d.i.b bVar) {
    if (bVar == null) { Log.d(f31884g, "getChangLian: infoListener 为空"); return; }
    if (!com.fengeek.main.i.a.f31837c) { Log.d(f31884g, "setUnlock: 耳机未连接"); return; }
    com.fengeek.main.i.c.a aVar = new com.fengeek.main.i.c.a();
    aVar.setCommandClassifyId(1);
    aVar.setCommandId(13);
    aVar.setBuffer(new byte[]{ z ? (byte) 1 : (byte) 0 });
    aVar.setInfoListener(bVar);
    a.getInstance().addCommand(aVar);
}
```

→ **cid=1 / cmdId=13 / payload={0,1}，与 F046 的 `c.java:371-385` 逐字节相同**，
连承载也一样（都是 Mate）。两者的区别只在**型号门控**，不在帧。

```
00 01 01 00 03 0D 01 01     ← 开（8 字节）
00 01 01 00 03 0D 01 00     ← 关
```

> ⚠️ 早期版本曾误判「F048 的源码里没有 setLdacSwitch」，是因为只搜了 `c.java`（F046 类）。
> 七个机型族分别是 `b.java`=F045、`c.java`=F046、`d.java`=F047、`e.java`=F048、
> `f.java`=F049、`g.java`=F051、`h.java`=F053，方法名高度同构但**不在同一个文件里**。

### 5.4 连接前提

📖 `com/fengeek/main/i/b.java` 是 `BluetoothStream`：
`connectStream(handler, socket, earType)` 启动读线程（`:216-222`），
`write(byte[])` 直接写 socket（`:228-235`），`writeMate(...)` 是 Mate 组帧（`:237-262`）。

> 📌 注意区分两条互不相干的链路：
>
> - **SDP 帧**（`FF 01 00 | len+2 | 02 34 | …`）由 `com/fengeek/utils/l1/v0/a.getPayload()`
>   构造，经 `DeviceCommManager.sendRequest(request)` 下发（F43 / CC Pro2 那套私有 SDK）。
> - **Mate 帧**（`seq | cid | 01 | 00 | …`）由 `com/fengeek/main/i/b.java:237` 的
>   `writeMate()` 构造，经 `CommandManager.sendCommand()`（`d/a.java:243`）下发
>   （F045–F053 七个机型族）。
>
> `b.java:264` 里那个 SDP 版 `write(baseCommand, handle)` 生成格式对，但**全工程无人调用**——
> 属于遗留死代码，不要被它误导。

---

## 6. Gaia 老协议通道

📖 仅静态分析。

`type` 为 0 或其它值时走这条路。

### 6.1 命令号

📖 `com/fiil/sdk/gaia/father/Gaia.java:229-333`

| 常量 | 值 | 十六进制 | 源码行 |
|---|---|---|---|
| `FFCOMMAND_GetHeadsetUUID` | `1966` | `0x07AE` | `:229` |
| `FFCOMMAND_GetLDACBuyType` | `1967` | `0x07AF` | `:230` |
| `FFCOMMAND_GetLDACSwitchType` | `1971` | `0x07B3` | `:231` |
| `FFCOMMAND_SetLDACSwitchType` | `1970` | `0x07B2` | `:314` |
| **`FFCOMMAND_SetUnlockLADC`** | **`1968`** | **`0x07B0`** | **`:333`** |

⚠️ 注意 `LADC` 是厂商的拼写错误（不是 `LDAC`），源码里就是这个拼法。

### 6.2 帧格式

📖 `com/fiil/sdk/command/FiilCommandUtil.java:517-534 getSendBuffer`，
偏移常量见 `com/fiil/sdk/gaia/father/Gaia.java:344-359`

```
偏移  0     1      2       3              4      5        6      7        8..
     SOF | ver  | flags | payloadLen | vendHi vendLo | cmdHi cmdLo | payload
```

| 常量 | 值 | 说明 |
|---|---|---|
| `SOF` | `0xFF` | 帧首 |
| `PROTOCOL_VERSION` | `1` | 普通帧 |
| `NEW_PROTOCOL_VERSION` | `241`(`0xF1`) | 新协议帧 |
| `flags` | `0` | 恒 0，源码里硬编码 |
| `VENDOR_FF` | `564`(`0x0234`) | FIIL 厂商号 |
| `OFFS_PAYLOAD` | `8` | payload 起始偏移 |

⚠️ **`payloadLen` 只算 payload**，不含 8 字节头。这与另外两套帧的长度语义都不同：
SDP 的长度字段含 `cmdId`（`+2`），Mate 的长度字段也含 `cmdId`。三种帧混用时最容易在这里错。

逐字节示例（Gaia 1968 写左耳全零 license）：

```
FF 01 00 11 02 34 07 B0  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
│  │  │  │  └──┬─┘ └──┬─┘ └──────────── 17 字节 payload（17 = 0x11）─────────┘
│  │  │  │     │       └ VENDOR_FF=564 / 1968
│  │  │  │     └ payloadLen = 17
│  │  │  └ flags = 0
│  │  └ version = 1
│  └ SOF
```

### 6.3 payload 布局（**本轮新解出，之前标「未展开」**）

📖 `com/fiil/sdk/command/u.java:41-46`

```java
public void setUnlockLDAC(byte[] bArr, CommandBooleanListener listener) {
    this.commandId = getGaiaIntValue("FFCOMMAND_SetUnlockLADC");   // 1968
    this.buffer = getSendBuffer(getGaiaIntValue("VENDOR_FF"), this.commandId, false, bArr);
    getCommandQueue().a(this);
}
```

`bArr` **原样透传，没有任何额外包装**。调用方 `com/fiil/sdk/manager/FiilManager.java:1526-1531`
也只是检查 `isGaiaConnect()` 后转调。所以 payload 就是 17 字节 license 本体，与
F39/F43/F048 的 license 格式完全一致（`00|01` + 16 字节）。

### 6.4 回包判据

📖 `com/fiil/sdk/gaia/father/GaiaSdkCommand.java:1986-1995`、`:1700-1709`

`analysisSetUnlockLADC` 与 `analysisSetLDACSwitchType` 都是：

```java
aVar.getBaseCommandListener().onSuccess();
((CommandBooleanListener) aVar.getBaseCommandListener()).onResult(bArr[0] == 0);
```

→ **回包首字节为 `0` 才算成功**。

⚠️ 但 `analysisGetLDACSwitchType`（`:924-933`）取的是 **`bArr[1]`**：

```java
((CommandIntegerListener) aVar.getBaseCommandListener()).onResult(bArr[1]);
```

SET 看 `[0]`、GET 看 `[1]`，两个下标不同，实现时最容易在这里错。

### 6.5 命令号是怎么解析出来的

📖 `com/fiil/sdk/utils/ReflectUtils.java:8-53`

命令号不是硬编码，而是反射查表：

- `getGaiaIntValue(name)` → `Class.forName("com.fiil.sdk.gaia.father.Gaia").getDeclaredField(name).getInt(null)`
- `getCommandMethod(id)` → 反射读 `com.fiil.sdk.config.Config.sMap`（`Config.java:312-326` 逐条 `put`）

→ 所以上面这些数值在源码里可静态确定，不必抓包。本项目的 `GAIA_CMD_*` 常量就是这么来的。

### 6.6 可执行实现

`src/fiil_ldac.py` 的 `gaia_frame` / `gaia_activate_frames` / `gaia_switch_frame` /
`gaia_query_frame` / `gaia_ack_ok` / `gaia_switch_state`，以及 `--proto gaia`。

```bash
python src/fiil_ldac.py frames --proto gaia                                # 只打印帧
python src/fiil_ldac.py activate --proto gaia --zeros --dry-run            # 离线核对
python src/fiil_ldac.py switch --proto gaia --on --dry-run
```

⚠️ **未在真机验证**：本机只有 Key Max（F046，走 Mate/BLE），没有 F039–F043 系列耳机。

---

## 7. license 的构造

📖 `UnlockLDACActivity.java:62-65, 205-254`

```
license(17 字节) = [耳别] + [16 字节 UUID]

耳别：0x00 = 左耳，0x01 = 右耳
UUID：来自耳机本身，通过 FiilManager.getUUID() 或 F39 的 LDAC_UUID 查询获得
```

`activateCode` 字符串格式：

```
"<左耳 16 字节 hex 共 32 字符>,<右耳 16 字节 hex 共 32 字符>"
```

例：`00112233445566778899AABBCCDDEEFF,FFEEDDCCBBAA99887766554433221100`

### 7.1 固件是否校验内容？

**校验。** ⚠️ 这一节在 1.1.0 被**推翻重写**。早期版本根据官方后门（`CcPro2NewEleFragment.java:642-650`）
发送全零 license，推断「固件不校验内容」——**该推断是错的**，已被真机实测推翻。

真机实测（FIIL Key Max / F046 / 固件 3.0.1.1），把 `142`（`getLdacUnlockStatus`）当 oracle：

| 写入内容 | 耳机 ACK（`cid=1 cmd=12` 回包） | 读回 `142` |
|---|---|---|
| `00 ‖ 设备UUID16B`（= 自洽构造） | `00` | **`00`**（解锁状态被清掉） |
| `17 字节全零` | `00` | `00` |
| 15 种校验和变体（sum8/xor8/crc16/neg…@0或@15） | `00` | `00` |
| 43 种派生（md5/sha1/sha256 × 7 种盐 × 4 种拼接） | `00` | `00` |
| `uuid16B ‖ 00` | `01` | `00` |
| 裸 `uuid16B`（payload len=`0x10`） | `01` | `00` |

三条结论：

1. **ACK 只表示「命令被收到」，不表示「license 被接受」。** 判断唯一依据是回读 `142`。
2. 固件确实校验内容，**写错内容会清掉已有解锁状态**，且不会自动恢复。
3. `activateCode` **不是设备 UUID 的简单派生**，也不是纯校验和——极可能含服务器侧私有盐/私钥。
   在官方服务器下线（`newservice.fiil.com` NXDOMAIN）的今天，**离线伪造 license 已被证伪**（累计 62 个候选全灭）。

> 那官方后门为什么发全零？因为它在 F039（CC Pro2）上触发的是**另一套固件逻辑**，
> 不能反推到 F046/F048。跨机型套用结论正是 1.0.0 犯的错。

### 7.2 `142` 与 `143` 是两条独立路径

真机实测（F046）：

| `142` 授权 | `143` 开关 | `144` 编解码 | LDAC 实际生效 |
|---|---|---|---|
| `00` | `01` | `02` | **是** |

即 **LDAC 开关本身不需要 license**，license 只影响官方 App 的 UI 是否放行那个开关
（`SettingsControlCard.kt:184` 的 `isEnabled = ... && s.ldacUnlocked` 就是这个 UI 门）。
所以「开 LDAC」可以在未授权状态下离线完成，「写 license」是另一件事。

### 7.3 哪些机型存在「授权」这件事（2026-11-12 全机型核对）

📖 `com/fengeek/main/i/d/{b,c,d,e,f,g,h}.java`（依次对应 F045/F046/F047/F048/F049/F051/F053）

七个机型族里，LDAC 相关方法的实现情况**并不一致**：

| 机型族 | `setLdacSwitch` | `getLdacSwitchStatus`<br>(39/143) | `getLdacUnlockStatus`<br>(39/142) | `setActivationLdac`<br>(1/12) | 有激活 UI |
|---|:---:|:---:|:---:|:---:|:---:|
| F045 (`b.java`) | ✗ | ✗ | ✗ | ✗ | ✗ |
| **F046** (`c.java`) | ✓ | ✓ | ✓ | ✓ | ✓ |
| F047 (`d.java`) | ✗ | ✗ | ✗ | ✗ | ✗ |
| **F048** (`e.java`) | ✓ | ✓ | ✓ | ✓ | ✓ |
| F049 (`f.java`) | ✓ | ✓ | **✗** | ✗ | ✗ |
| F051 (`g.java`) | ✓ | ✓ | **✗** | ✗ | ✗ |
| F053 (`h.java`) | ✓ | ✓ | **✗** | ✗ | ✗ |

三条可直接引用的结论：

1. **只有 F046 与 F048 存在「授权/解锁」这个概念。** 它们同时实现了写 license（`setActivationLdac`）
   和读授权状态（`getLdacUnlockStatus` / 142），App 里也有激活入口（「激活」按钮 → 服务器 → 激活码页面）。
2. **F049 / F051 / F053 能开关 LDAC，但没有授权概念。** 这三个类里**没有 `getLdacUnlockStatus`，
   也没有 `setActivationLdac`**，`f049`/`f051`/`f053` 三个包下更搜不到任何「激活」字样或
   `UnlockLDACActivity` / `LDACProductRegistActivity` 引用 —— 用户在这三款耳机上从来不会看到「激活」按钮。
   换句话说，**它们的 LDAC 是直接可用的，不需要解锁**。
3. **F045 / F047 完全没有 LDAC 相关命令**，连开关都没有（硬件层面就不支持）。

`setLdacSwitch` 的实现本身（`c.java:371-385` / `e.java:573-588` / `f.java:527-542` /
`g.java:462-477` / `h.java:528-543`）五处**逐字节相同**：

```java
if (bVar == null) { ... return; }              // 回调为空
if (!com.fengeek.main.i.a.f31837c) { ... }     // 耳机未连接
aVar.setCommandClassifyId(1);
aVar.setCommandId(13);
aVar.setBuffer(new byte[]{ z ? (byte) 1 : (byte) 0 });
```

→ **没有任何一处检查授权状态**。授权只影响官方 App 的界面显示，不影响命令是否下发。

> 对 F048 用户的意义：`142=0` 时 App 把开关控件整个 `setVisibility(8)` 隐藏了
> （`F048HomeFragment.java:729`），但底层 `setLdacSwitch` 依旧只检查「是否已连接」。
> 也就是说 **F048 的 LDAC 开关同样不需要 license**，只是官方 App 不给你点。

---

## 8. 服务器接口

📖 `h/a/c.java:8-17`

| 常量 | URL |
|---|---|
| `f47048a` | `http://newservice.fiil.com/app/headset/activation/info?deviceCode=` |
| `f47049b` | `http://newservice.fiil.com/app/headset/sn/reg` |
| `f47050c` | `http://newservice.fiil.com/app/headset/activation/order` |
| `f47051d` | `http://newservice.fiil.com/app/headset/activate` |

### 8.1 响应格式

⚠️ 外层是对象，`data` 字段是**字符串化的 JSON**（不是嵌套对象）：

```json
{
  "code": "200",
  "msg": "",
  "data": "{\"activateCode\":\"<左32hex>,<右32hex>\",\"orderSn\":\"\"}"
}
```

三个分支（`CcPro2NewEleFragment.java:222-262`）：

| `activateCode` | `orderSn` | 跳转 |
|---|---|---|
| 非空 | — | `UnlockLDACActivity`，`type=2` |
| 空 | 空 | 购买页 |
| 空 | 非空 | 订单页 |

### 8.2 域名状态

✅ 实测（2026-10）：`newservice.fiil.com`、`sapp.fengeek.com`、`ms.fiil.com` **全部 NXDOMAIN**。

---

## 9. 机型路由表

📖 综合各 Fragment 的调用点得出。

| 机型 | Fragment / Activity | `type` | 通道 |
|---|---|---|---|
| F039 / CC Pro2 | `CcPro2NewEleFragment` | `2` | F39 Bluetrum |
| F039 / CC Pro2（长按后门） | `CcPro2NewEleFragment.g0()` | — | F39 Bluetrum，不联网 |
| F043 | `F046HomeFragment` | `1` | F43 SDP |
| F048 | `F048HomeFragment` | `3` | F048（Mate 帧） |
| F040 等老固件 | — | `0` | Gaia 1968 |

`FiilCommandUtil` 体系里还有 `FiilCommandF039`（Gaia 1968），说明 F039 存在新旧两套固件，
老的走 Gaia，新的走 Bluetrum。

---

## 10. 未确认项

诚实清单，请勿当作结论使用：

| 项 | 状态 | 说明 |
|---|---|---|
| F43 `subId=4` 的右耳为何不递增 | ⚠️ | 左右耳同 `cmdId`/`subId`，仅靠 `values[0]` 区分；未在真机确认固件确实这样解 |
| F048 是否也有长按后门 | 📖 | 只在 `CcPro2NewEleFragment` 找到后门，F048 未找到 |
| 全零 license 在 F043/F048 上的效果 | ❌ | 1.1.0 真机实测：F046 上**写全零会清掉解锁状态**，不是"等效激活" |
| 写入后是否需要重启耳机 | ⚠️ | 代码里没有重启调用；F046 实测写入后立即生效（142 立刻变化），无需重启 |
| 固件 OTA 后激活标志是否必然清除 | ⚠️ | 推测会清，未逐版本验证 |
| Gaia 1968 的 payload 确切布局 | ✅ | 1.4.0 解出：`getSendBuffer` 原样透传 `bArr`，见 [§6.3](#63-payload-布局本轮新解出之前标未展开) |
| `activateCode` 的生成算法 | ❌ | 62 个候选（校验和/派生/结构变体）全部被拒，含服务器私有盐，**未解出** |
| `getCodecStatus`(144) 返回值语义 | ⚠️ | 源码里是孤立方法（无调用点），`01`=非LDAC / `02`=LDAC 是本项目真机实测推断 |
| PID 回包第 3 字节含义 | ⚠️ | 实测 `00 2E 01`，第 2 字节 `0x2E`=46 已确认是机型号，第 3 字节未定 |

如果你验证了其中任何一条，欢迎按 [CONTRIBUTING.md](../CONTRIBUTING.md) 提交。

---

## 11. BLE GATT 直连通道（Mate 帧，1.1.0 新增）

SPP/RFCOMM 不是唯一入口。同一副耳机在 **BLE 侧**就有完整的私有服务，
而且帧格式与 SPP 侧的 `writeMate` **逐字节相同**，因此可以完全绕开"配出 COM 口"这一步。

### 11.1 服务与特征

📖 `com/fengeek/main/j/a.java:8`（服务 UUID）、`com/fengeek/main/ble/FIILPeripheral.java`

| 项 | UUID | 说明 |
|---|---|---|
| 服务 | `0000fdb3-0000-1000-8000-00805f9b34fb` | 常量 `f31893b` |
| 写特征 | `0000ff17-0000-1000-8000-00805f9b34fb` | 源码里未硬编码，由调用方传入 |
| 通知特征 | `0000ff18-0000-1000-8000-00805f9b34fb` | 同上 |
| CCCD | `00002902-0000-1000-8000-00805f9b34fb` | `FIILPeripheral.f27180b` |

厂商 ID `564`（`0x0234`，常量 `f31895d`）可用于从广播里认出 FIIL 设备。

> ⚠️ `0000ff16` 在实机上**不支持写**（写下去无回包）——早期证据
> `_fiil_public/docs/evidence/log_unlock16_*.txt` 只有 TX 没有 RX 就是这个原因。必须用 `ff17`。

### 11.2 帧格式

与 [3.2](#32-帧格式) 的 Mate 帧完全一致（`com/fengeek/main/i/b.writeMate` /
`com/fengeek/main/ble/FIILPeripheral.write(baseCommand)`）：

```
[seq] [cid] [0x01] [0x00] + ([(plen+2), cmdId] if cmdId != 0) + [plen] + [payload]
```

读回包：

```
[seq] [cid] [0x02] [0x00] [len] + ([(plen+2), cmdId, status] if len > 1) + [plen] + [payload]
```

`len <= 1` 时是短帧（SET 命令的 ACK），此时 `payload = {status}`。

### 11.3 必发的握手

**连接后必须先发 `setUnlock`（`cid=39`, `cmdId=255`, payload=`{0x02, 0x34}`），
否则后续所有命令静默无回包。** 这是真机踩过的坑。

```
→ 00 27 01 00 04 FF 02 02 34
← 00 27 02 00 03 FF 01 FF
```

### 11.4 LDAC 相关命令

| 动作 | cid | cmdId | payload | 成功判据 |
|---|---|---|---|---|
| 读授权 | `39` | `142` | `{0}` | 回包 `payload[0]`，`1`=已解锁 |
| 读开关 | `39` | `143` | `{0}` | 回包 `payload[0]`，`1`=已开 |
| 读编解码 | `39` | `144` | `{0}` | `01`=非LDAC，`02`=LDAC（实测推断） |
| 写授权 | `1` | `12` | 17 字节 license | 回包 `payload[0]==0`，**但不代表被接受**（见 7.1） |
| 写开关 | `1` | `13` | `{0}` 或 `{1}` | 回包 `payload[0]==0` |
| 关低延迟 | `37` | `0` | `{0}` | 开 LDAC 前**必须先发** |

**官方开关顺序**（`F046HomeFragment.java:395-405`）：

```
开 LDAC：setLowDelay(0) → setLdacSwitch(1)
关 LDAC：setLdacSwitch(0)
```

顺序反了会被固件拒绝。切 LDAC 会重建 A2DP 链路，**连接断开属预期**，重连复核即可。

### 11.5 实测帧（Key Max / F046 / 固件 3.0.1.1）

```
读 PID     : 03 27 01 00 02 84 00  → 03 27 02 00 04 84 01 00 2E 01
读左耳 UUID: 01 27 01 00 02 8A 00  → 01 27 02 00 12 8A 10 42 50 32 36 32 30 35 12 00 3B 51 45 06 20 BB 78
读授权 142 : 02 27 01 00 02 8E 00  → 02 27 02 00 03 8E 01 01
读开关 143 : 03 27 01 00 02 8F 00  → 03 27 02 00 03 8F 01 00
关低延迟   : 05 25 01 00 01 00     → 05 25 02 00 01 00   (payload=00)
开 LDAC    : 06 01 01 00 03 0D 01 01 → 07 01 02 00 03 0D 01 00   (payload=00 成功)
```

值得注意：**Key Max 的左右耳 UUID 相同**（均为 `4250323632303512003b51450620bb78`），
说明 F046 的 UUID 是设备级而非耳级——这与 F048 左右各一次的设计不同。

### 11.6 可执行实现

见 [`../src/fiil_ble.py`](../src/fiil_ble.py)，子命令 `scan / models / status / backup / switch / unlock / raw`，
原始收发帧写入 `docs/evidence/ble_*.log`。

---

## 12. 未公开命令（1.2.0 新增，盲扫发现）

✅ 全部真机实测（Key Max / F046 / 固件 3.0.1.1）。

FIIL+ 只调用了协议的一小部分。为找「回读已写入 license」之类的隐藏命令，对两类命令空间做了**全量盲扫**：
逐条发送，记录任何回包。结论是**没有出厂的 license 回读命令**，但确实挖出了 6 条未公开查询命令和 1 个未使用的命令类别。

### 12.1 cid=39 查询族全扫（0–254，共 255 条）

有实质回包的命令（含 App 已知 + 未公开）：

| cmdId | App 是否使用 | 回包 payload | 推断含义 |
|---|---|---|---|
| `0x10` (16) | **未使用** | `7c 05 ee e4` | 疑似固件编译号 / 内部版本 |
| `0x83` (131) | **未使用** | `d8 80 83 8a f0 18` | 疑似 MAC 低 6 字节（倒序） |
| `0x86` (134) | **未使用** | `03 0c` | 未定（2 字节） |
| `0x8C` (140) | **未使用** | 16B，与 138/139 同值 | 同 UUID 的第三条查询通道 |
| `0x8D` (141) | **未使用** | 16B，与 138/139 同值 | 同 UUID 的第四条查询通道 |
| `0xFE` (254) | **未使用** | `08 00` | 疑似协议版本 / 能力位 |
| `1`–`8`, `12`, `13`, `16`–`20`, `22`, `24` | 部分使用 | 见 §11.4 | 已知状态量 |
| `128`, `129`, `130` | 使用 | `00` / `01` / `01` | 长按 / 声调 / 其他状态 |
| `132`, `138`, `139`, `142`, `143`, `144` | 使用 | 见 §11.4 | PID / UUID / LDAC / 编解码 |

**关键否定结论**：全 255 条命令里**没有任何一条回读已写入的 license 内容**（没有任何回包长度 ≥ 17 且含激活码字段）。
这从固件侧再次确认：license 写进耳机后不可读出，**也就无法「从一台已授权耳机拷贝 license 到另一台」**。

**稳定性验证**：`0x10` / `0x83` / `0x86` / `0xFE` 在「同一连接内重复 3 次」与「断开重连后再读 3 次」的回包完全一致
→ 是设备稳定标识，**不是 nonce**，可放心作设备指纹。

### 12.2 cid 命令类别全扫（0–127）

只有 5 个 cid 对最小探测帧（5 字节空帧）有回包：

| cid | 状态 |
|---|---|
| `32` `33` `34` `36` | App 已知（EQ / 媒体 / 按键 / 复位） |
| `35` | **App 完全未使用** —— 固件实现了第 5 个命令族，但 FIIL+ 源码里没有任何 `setCommandClassifyId(35)` |

`cid=35` 的具体命令语义未展开（需要逐 cmdId 盲扫，风险高于收益，本轮未做）。

### 12.3 ⚠️ 危险命令：cid=36 的裸帧 = 恢复出厂设置

`c.java:489-502` 的 `setReset` **只设置 `commandClassifyId(36)`、不带 `commandId` 也不带 payload**。
这意味着**任何 `cid=36` 的 5 字节空帧都是一次恢复出厂设置**。

盲扫 cid 时这条命令被无意触发，耳机当场断开并停止 BLE 广播（官方 UI 文案也印证：`T1X_MoreSetting_remind_detail`
= 「耳机设置将恢复默认值，和手机连接信息不会被清除」、`T1X_MoreSetting_ResumeSynchronizationPrompt` = 「…将会重启耳机」）。

**任何扫描类脚本都必须跳过 cid=36。** `src/probe_guard.py` 已内置该保护。

### 12.4 ACK 码的真实含义（重要修正）

对不同长度的 license payload 逐一实测（1–24 字节），ACK 码规律：

| payload 长度 | ACK `payload[0]` |
|---|---|
| **17** | **`00`** |
| 1–16、18–24 | `01` |

进一步固定 17 字节、只改内容：

| payload | ACK |
|---|---|
| 首字节 `00` 或 `01`，后 16 字节任意 | `00` |
| 首字节 `02`/`03`/`FF`，后 16 字节任意 | `01` |
| 16B UUID + 末字节 `00`（首字节非 0/1） | `01` |

**结论**：`setActivationLdac` 的 ACK 只校验「长度 17」+「首字节 ∈ {0,1}」这两件事，
**完全不校验后 16 字节内容**。所以：

- ACK `00` **只表示格式合法**，与激活码是否正确无关
- 唯一可信的成功判据仍然只有**回读 142 是否为 `01`**

这解释了为什么 62 个错误候选全都拿到 ACK `00`。

---

## 13. 四套帧格式对照（1.4.0 新增）

FIIL+ 里同时存在四套私有帧。它们的**长度字段含义各不相同**，混用时极易出错，
所以集中对照一次。

| | **Mate** | **SDP** | **F39 / Bluetrum** | **Gaia** |
|---|---|---|---|---|
| 典型机型 | F045–F053（**含 F048**） | F043 / CC Pro2 | F039 / CC Pro2（Bluetrum） | F039–F043（`com.fiil.sdk`） |
| 承载 | SPP `writeMate` / BLE `0xff17` | SPP `sendRequest`（`DeviceCommManager`） | SPP | SPP |
| 帧头长度 | 4–6 字节 | 8 字节 | 5 字节 | 8 字节 |
| 长度字段**包含** | `cmdId`（`+2`） | `cmdId`（`+2`） | 仅本片 payload | **仅 payload** |
| 命令定位 | `cid` + `cmdId` | `commandId` + `subId` | `command` + 分片序号 | `vendorId` + `commandId` |
| 帧首 | 无固定 magic | `FF 01 00` | 无固定 magic | `FF` |
| ACK 判据 | `payload[0] == 0` | 同 Mate | 见 §3 | `payload[0] == 0`（GET 看 `[1]`） |
| 实现 | `fiil_protocol.build_frame` | `fiil_ldac.sdp_frame` | `fiil_ldac.f39_frames` | `fiil_ldac.gaia_frame` |

逐字节并列（都是「写左耳全零 license」这一件事）：

```
Mate  : 00 01 01 00 13 0C 11 00 00 … （4 字节头 + [13 0C] + [11] + 17B）
SDP   : FF 01 00 13 02 34 00 01 0C 11 00 00 … （8 字节头 + 17B）
F39   : 00 01 01 10 0F 0C 11 00 00 …（分片，第 0 片 15 字节）
Gaia  : FF 01 00 11 02 34 07 B0 00 00 … （8 字节头 + 17B）
```

同一件事（开 LDAC）：

```
Mate  : 00 01 01 00 03 0D 01 01
SDP   : FF 01 00 03 02 34 00 01 0D 01 01      ← F048
F39   : 00 01 01 00 03 0D 01 01                ← 与 Mate 相同
Gaia  : FF 01 00 01 02 34 07 B2 01
```

注意 SDP 与 Gaia 的头都是 8 字节、都有 `FF 01 00` 与 `02 34`，但：

- SDP 第 3 字节是 `payloadLen + 2`（含 `cmdId`），随后紧跟 `cmdId`、`subId`、`len`
- Gaia 第 3 字节是 `payloadLen`（**不含**命令段），命令在 `[6][7]`，payload 从 `[8]` 开始

两者**只有 `payloadLen` 差 2 与命令字段位置不同**，肉眼容易看混。

---

## 参考

- [ACTIVATION_FLOW.md](ACTIVATION_FLOW.md) — 激活链路逐步拆解
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — 常见问题
- [../src/fiil_ldac.py](../src/fiil_ldac.py) — 协议的可执行实现（Mate / SDP / F39 / Gaia 四套帧）
- [../src/fiil_ble.py](../src/fiil_ble.py) — PC 端 BLE 直连实现（方案五）
