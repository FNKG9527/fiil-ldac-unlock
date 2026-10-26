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
- [5. F048 SDP 通道](#5-f048-sdp-通道)
- [6. Gaia 老协议通道](#6-gaia-老协议通道)
- [7. license 的构造](#7-license-的构造)
- [8. 服务器接口](#8-服务器接口)
- [9. 机型路由表](#9-机型路由表)
- [10. 未确认项](#10-未确认项)

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

## 5. F048 SDP 通道

📖 静态分析 + ✅ 组帧已核对。

### 5.1 帧格式

与 F43 **同构**（同一个 `FF 01 00 | len | 02 34 | ...` 布局），只是命令号不同。

### 5.2 命令

📖 `com/fengeek/main/i/d/e.java:442`

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

**实例**

```
FF 01 00 13 02 34 00 01 0C 11 00 00×16     ← 左耳（27 字节）
FF 01 00 13 02 34 00 01 0C 11 01 00×15     ← 右耳
```

### 5.3 连接前提

📖 `com/fengeek/main/i/b.java` 是 `BluetoothStream`：
`connectStream(handler, socket, earType)` 启动读线程（`:216-222`），
`write(byte[])` 直接写 socket（`:228-235`），`writeMate(...)` 是另一套无 `FF` 头的格式（`:237-262`）。

---

## 6. Gaia 老协议通道

📖 仅静态分析。

`type` 为 0 或其它值时走这条路。

### 6.1 命令号

📖 `com/fiil/sdk/gaia/father/Gaia.java:230-231, 314`

| 常量 | 值 |
|---|---|
| `FFCOMMAND_GetLDACBuyType` | `1967` |
| `FFCOMMAND_SetLDACSwitchType` | `1970` |
| `FFCOMMAND_GetLDACSwitchType` | `1971` |
| `FFCOMMAND_SetUnlockLADC` | `1968` |

⚠️ 注意 `LADC` 是厂商的拼写错误（不是 `LDAC`），源码里就是这个拼法。

### 6.2 发送

📖 `com/fiil/sdk/command/u.java`（`FiilCommandF039`）`:41-46`

```java
public void setUnlockLDAC(byte[] bArr, CommandBooleanListener listener) {
    this.commandId = getGaiaIntValue("FFCOMMAND_SetUnlockLADC");   // 1968
    this.buffer = getSendBuffer(VENDOR_FF, 1968, false, bArr);
    getCommandQueue().a(this);
}
```

基类 `com/fiil/sdk/command/FiilCommandUtil.java:1303-1305` 里是空实现，实际逻辑只在子类。

### 6.3 解析

📖 `com/fiil/sdk/gaia/father/GaiaSdkCommand.java:1700-1709`

`analysisSetLDACSwitchType` → `onResult(bArr[0] == 0)`（`0` 表示成功）。

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

📖 **不校验**——证据是官方自己的后门（`CcPro2NewEleFragment.java:642-650`）发送的是：

```java
new byte[17]                        // 左耳：全 0
new byte[]{1, 0, 0, ...}            // 右耳：01 开头，其余全 0
```

厂商自己都在发全零 license，说明激活标志只看「有没有写过」，不看内容。

⚠️ **这是当前固件的行为**，未来固件可能加校验。

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
| F048 | `F048HomeFragment` | `3` | F048 SDP |
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
| 全零 license 在 F043/F048 上的效果 | ⚠️ | 只在 F039 的后门代码里确认；F043/F048 是静态推断 |
| 写入后是否需要重启耳机 | ⚠️ | 代码里没有重启调用，但真机是否立即生效未验证 |
| 固件 OTA 后激活标志是否必然清除 | ⚠️ | 推测会清，未逐版本验证 |
| Gaia 1968 的 payload 确切布局 | 📖 | 只找到 `getSendBuffer(VENDOR_FF, 1968, false, bArr)`，未展开 `getSendBuffer` |

如果你验证了其中任何一条，欢迎按 [CONTRIBUTING.md](../CONTRIBUTING.md) 提交。

---

## 参考

- [ACTIVATION_FLOW.md](ACTIVATION_FLOW.md) — 激活链路逐步拆解
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — 常见问题
- [../src/fiil_ldac.py](../src/fiil_ldac.py) — 协议的可执行实现
