# F046 LDAC 研究 → 模块改动清单

这份文档把 `RESEARCH_2026-11_F046_LDAC.md` 的研究结论翻译成**可以直接动手的改动项**。
每条都标了优先级、涉及文件、以及改动理由来自哪条实测证据。

> 阅读顺序建议：先看「0. 一句话」，再按 P0 → P1 → P2 往下做。
>
> **2026-11-17 修订**：原 P0-1「恢复出厂后必须提示重启耳机」已降级并移到 P2-4。
> 原因：该条依赖的「17 次 SET 全 ACK=01」证据链被查出错用了另一套 API 的帧形状
> （详见研究档案 §2.3 的两套 API 警告与 §2.5 的复核说明），结论待耳机上线后重测。
> 同时修正了研究档案 §2.3 的 `cid=1` 子命令表（原表把 `8=setTuning` 写成 `setLowDelay`、
> 把 `18=setSingle` 写成 `setTuning`，并把 F048 专属的 `2/6/9` 混进了 F046 的表）。

---

## 落地状态（2026-11-17 已实施）

| 编号 | 状态 | 落地位置 |
| --- | --- | --- |
| P0-1 | ✅ 已修 | 143/142 解析改成「有回包才置状态」；新增 `FiilStatus.ldacUnlockKnown` / `FiilRfcommController.ldacUnlockKnown`，空帧只打日志 |
| P0-2 | ✅ 已修 | `FIILProtocol.setLdacSwitch` 返回 `Boolean`，新增 `ldacSwitchBlockReason()`；`BluetoothProcessHook` 弹提示 + `publishState(force = true)` 弹回开关 |
| P1-1 | ✅ 已加 | `RfcommDebugPage` 的 `LdacDiagCard`（143/142/手机侧 + 144/254/140/141 原始回包 + 重新扫描）；发送入口 `FIILProtocol.requestLdacDiagnostics()` |
| P1-2 | ✅ 已加 | `ModelCapabilityTest.ldacSwitchGatedByEarType` / `ldacLicenseSlotOnlyForF046`、`LdacDiagnosticsProtocolTest`（5 条） |
| P1-3 | ✅ 已加 | `FiilMate.Query` 的 142/143 标「已验证」，144 标「语义未定」，140 标「与 `WIND_ADAPTIVE` 同号不同义」 |
| P2-1 | ✅ 已加 | 140/141 license 槽在调试页只读展示（`FiilModels.hasLdacLicenseSlot` 门控，仅 F046） |
| P2-2 | ⚠ 部分 | 手机侧只显示「LDAC 使用中 / 已声明未启用 / 未声明」，**分不出 AAC 与 SBC** —— `FiilCodec.query` 只返回 `supported/enabled`。为免与耳机侧混成同一个字段，这一项留在调试页，没有进详情页 |
| P2-3 | ✅ 遵守 | 模块内没有任何写 140/141/142 的入口 |
| P2-4 | 📄 保留 | 模块无恢复出厂入口，该条继续作为「将来若加」的规范 |
| 附：文案 | ✅ 已改 | `PodDetailPage` 四态：读取中 → 已启用 → 授权位未回报 → 引导解锁（`LDAC_UNLOCK_HINT`） |

---

## 0. 一句话

**LDAC 开关（143）模块已经做对了，不用改。**
**LDAC 授权（142）在协议层无法写入，模块应停止尝试，改为「诊断可见 + 引导用户」。**
剩下的是**健壮性补强**和**几个协议已支持但模块没做的新能力**。

---

## P0 · 必须修（会导致用户可见的错误行为）

### P0-1 · `ldacUnlocked` 的解析要判长度

**问题**：`FiilRfcommController.kt:1505`
```kotlin
ldacUnlocked = frame.byteAt(0, 0) == 1
```
若耳机回 `plen = 0` 的空帧（表示「不认识这条命令」），`byteAt(0, 0)` 会取到默认值 `0`，
于是 `ldacUnlocked` 被静默置成 `false`——**「不支持」与「未授权」被混为一谈**。
用户看到的是「需先在 FIIL+ 官方 App 里解锁高清音频」，而真实情况是**这条命令根本没被响应**。

**改动**：
```kotlin
// 现在
ldacUnlocked = frame.byteAt(0, 0) == 1

// 建议
val len = frame.payloadLength          // 按实际 API 取
if (len >= 1) {
    ldacUnlocked = frame.byteAt(0, 0) == 1
    ldacUnlockKnown = true
}
// len == 0 → 保持上一次的值，不动 ldacUnlockKnown
```

**为什么重要**：`PodDetailPage.kt:404` 的文案依赖 `ldacUnlocked`。
如果它是被「空帧」误置成 false 的，用户会被引导去做一件没必要的事（去官方 App 解锁）。

**顺带**：`143` 的解析（`ldacEnabled`）建议做同样的长度判断。

**涉及文件**：`pods/FiilRfcommController.kt:1505` 附近、`pods/FiilStatus.kt:119`

---

### P0-2 · `setLdacSwitch` 的失败要能反馈到 UI

**问题**：`BluetoothProcessHook.kt:1063` 调 `FIILProtocol.setLdacSwitch(want)`，
但 `setLdacSwitch` 内部有多条**静默 return**：
```kotlin
if (!FiilRfcommController.isMateDialect) { Log.i(...); return }
if (!FiilModels.supportsLdac(earType)) { Log.i(...); return }
```
这些路径下 UI 的乐观更新已经发生（开关已经「点下去」），但耳机侧什么都没发。
用户看到开关是开的，实际没开。

**改动**：让 `setLdacSwitch` 返回 `Boolean`（是否真的下发了帧），
`BluetoothProcessHook` 在 `false` 时**回滚 UI 状态**并发一个 toast。

**实测依据**：`BluetoothProcessHook.kt:1078-1092` 的注释已经意识到了这个问题
（「如果这条分支只打日志就返回，用户以为 LDAC 开了」），但只解决了 `FiilCodec.setLdac` 那条路径，
没解决 `FIILProtocol.setLdacSwitch` 的三条静默 return。

**涉及文件**：`pods/FIILProtocol.kt:577`、`hook/BluetoothProcessHook.kt:1045`

---

## P1 · 建议做（提升可诊断性，成本低）

### P1-1 · 新增「耳机侧状态」诊断面板

模块已经有 `RfcommDebugPage.kt`。建议在其中加一块**常驻的 LDAC 状态区**，展示：

| 字段 | 来源 | 说明 |
|---|---|---|
| `142` 授权 | `cid=39 cmd=0x8E` | `00` = 未授权 / `01` = 已授权 |
| `143` 开关 | `cid=39 cmd=0x8F` | 耳机自己的开关 |
| `144` codec | `cid=39 cmd=0x90` | 语义未定，但可观测变化 |
| **`140` 槽 L** | `cid=39 cmd=0x8C` | 16 字节 hex |
| **`141` 槽 R** | `cid=39 cmd=0x8D` | 应与 140 相同 |
| 手机侧 codec | `FiilCodec` | A2DP 实际协商结果 |
| 能力位 | `cid=39 cmd=254` | `08 00`，位含义未知 |

**价值**：
- 用户报「LDAC 开不了」时，一眼能看出卡在哪一层（耳机未授权 / 耳机开关没开 / 手机没协商上）。
- `140/141` 槽的内容是**当前耳机里存的 license**，是判断「耳机被写过什么」的唯一窗口。
- 这是**唯一不会引起副作用**的增强——全是读操作。

**涉及文件**：`ui/pages/RfcommDebugPage.kt`、`pods/FIILProtocol.kt`（加一个 `requestLicenseSlot()`）

**注意**：`140/141` 在 11-11 的全扫里**没有回包**（落在 `25..127` 段），
而 11-12 的扫描里**回 16 字节 UUID**。这个矛盾尚未查明。
所以实现时**必须容忍无回包**，UI 显示「不可用」而不是报错。

---

### P1-2 · 把 `supportsLdac` 与官方能力表对齐校验

模块 `FiilModels.kt` 的 `LDAC_EAR_TYPES = setOf(39, 46, 48, 49, 51, 53)`
与第三方对同型号同固件的独立逆向记录 `PROTOCOL_FIIL.md:239` 完全一致：

| 机型 | LDAC 开关（1/13） |
|---|---|
| F045 | ✗ |
| **F046** | **✓** |
| F047 | ✗ |
| F048 | ✓ |
| F049 | ✓ |
| F051 | ✓ |
| F053 | ✓ |

**建议**：加一个单元测试断言这个集合，防止将来误加/误删。
`app/src/test/java/moe/chenxy/fiilpods/pods/ModelCapabilityTest.kt` 已有测试基建。

**顺带**：同一份资料显示 **F046 不支持** `cid=1 cmd=14/15/16/17/18`（自适应 EQ / 耳道 / 环境 / 风噪 / 云感调音）。
模块的 `requestAdaptiveSwitches()` 是按机型分发的，确认 F046 不在分发列表里即可。

---

### P1-3 · `FiilMate` 常量补注释，标注「已验证/未验证」

模块 `FiilMate.kt` 的常量有些是实测确认的，有些是从源码推的。建议加标记：

```kotlin
// 已验证（2026-11-16 真机实测，F046 / 3.0.1.1）
const val LDAC_UNLOCK = 142      // cid=39，回 00/01
const val LDAC_SWITCH = 143      // cid=39，回 00/01
const val LDAC_SWITCH_W = 13     // cid=1 cmd=13，payload=[0/1]，ACK=0
const val LDAC_ACTIVATE = 12     // cid=1 cmd=12，payload=17字节裸license，ACK由长度+side决定

// 未验证 / 语义未定
const val CODEC_STATUS = 144     // 已知回 01/02，与授权无因果
```

**价值**：后来人不会再走「用 `cmd=12` 发 `[13,1,1]`」这种错路。

---

## P2 · 可选（新功能，需评估用户价值）

### P2-1 · 展示 `140/141` license 槽（只读）

**为什么有意义**：这是耳机里**真实存储的授权数据**。用户可以拿它去：
- 对比「两台同型号耳机」是否被写入了不同内容；
- 确认某个操作是否真的改写了耳机状态（而不只是 UI 变化）。

**技术可行性**：`cid=39 cmd=0x8C/0x8D` 是只读镜像，写入无效（实测 T1/T2）。
**完全安全**，不会改任何状态。

**风险**：若耳机回空帧，UI 要能优雅降级。

---

### P2-2 · 「手机侧 codec 交叉验证」提示

模块已经有 `FiilCodec`（走 `BluetoothA2dp.setCodecConfigPreference`）。
建议在详情页加一行小字：**「手机实际编码：LDAC / AAC / SBC」**（来自 `FiilCodec` 的实时值）。

**为什么**：`142` 是「耳机是否被授权」，`143` 是「耳机开关」，而**用户真正关心的是「我有没有在听 LDAC」**——
那是 A2DP 协商结果，只有 `FiilCodec` 知道。
三层状态分开显示，用户就不会被 142 的 `00` 误导。

**涉及文件**：`ui/pages/PodDetailPage.kt`、`pods/FiilCodec.kt`

---

### P2-3 · 不要对用户暴露「写 license」能力

**技术上完全可行**（`cid=1 cmd=12`，17 字节裸帧，`ACK=0`，槽位精确回显，可持久化）。
**但**：实测 5000+ 次写入，`142` **从未**变成 `01`。

如果把它做成用户功能（「手动输入授权码」）：
- 用户会输入各种东西，全部「成功」（`ACK=0`），然后 `142` 还是 `00`；
- 更糟的是，**写错内容会清掉已有的授权**（历史记录：`00||uuid` 让 `142` 从 `01` 掉到 `00`）。

**结论**：保持不暴露。若为了调试需要，放在 `RfcommDebugPage` 里，并加明显的「会覆盖耳机内授权数据」警告。

---

### P2-4 · 若将来给「恢复出厂」加入口，提示用户重启耳机

**前提说明**：模块**当前没有**恢复出厂入口 —— 全树只有
`FiilCommands.kt:56 const val SET_RESET = 521`，而 `521` 是 **GAIA** 命令号
（`FFCOMMAND_SET_RESET`），F046 根本不走 GAIA（见研究档案 §1.1）。所以这条只是**前瞻建议**。

**若要新增**，正确的帧是 Mate 的 `cid=36` 5 字节裸帧：
```
00 24 01 00 00    →    0A 24 02 00 01 00      payload[0]=00 表示被接受
```
（无 cmdId、无 payload。注意：**不是** `FiilCommands.SET_RESET = 521`。）

**实测影响**（这部分不依赖 ACK，是前后快照直接对比得来的，可信）：
- `142` 授权位 **不动**（`00` → `00`）—— 恢复出厂**不会**重置授权；
- `143` 开关 **被重置**（`01` → `00`）；
- `144` codec **变化**（`01` → `02`）；
- 固件版本 / 校验和 / `138`/`139` UUID / `254` 能力位 **全部不变**。

**改动建议**：
1. 发 `cid=36` 后弹一个提示：「已恢复出厂设置。建议**长按电源键 4 秒关机再开机**，确保状态稳定。」
2. 重连后主动重读 `142`/`143`/`144` 刷新 UI（因为 `143` 会被重置成 `00`，UI 若不刷新会显示旧值）。
3. **不要**告诉用户「不重启就改不了设置」—— 这条结论的证据链有问题，见研究档案 §2.5 的警告。

**涉及文件**（新增时）：`pods/FIILProtocol.kt`、`hook/SettingsControlCard.kt`、对应 UI 页面

---

## 附 · 关于「142 无法置位」这件事，模块该怎么表述

模块当前 `PodDetailPage.kt:404`：
```kotlin
!ldacUnlocked -> "需先在 FIIL+ 官方 App 里解锁高清音频"
```

这句话**本身是对的**（官方 App 是唯一已知能置位 142 的途径）。但可以更准确一点：

> 「此耳机的 LDAC 需要先在 FIIL+ 官方 App 内完成高清音频解锁。
> 解锁后回到本页下拉刷新即可。」

**理由**：用户看到「需先解锁」后的第一个疑问通常是「解锁完要不要重启/重连」。
明确告诉他「下拉刷新」，减少来回。

---

## 附 · 模块**不需要**做的事

以下都是这次研究**实测否证**的方向，模块不必投入：

| 不要做 | 原因 |
|---|---|
| 实现 GAIA 协议的 LDAC 解锁 | F046 固件完全不实现 GAIA，ch6 上零回包 |
| dump 耳机固件（GAIA 文件系统） | 同上，`OPEN_FILE` 零回包 |
| 读 GAIA 鉴权位图（1408） | 同上 |
| 试用模式（12308/12309） | 同上 |
| 用 `cmd=12` 发 `setLDAC` | 帧形状错误，永远 `ACK=1` |
| 用 19 字节 `[12,17,side,UUID]` 写 license | 那是 F048 的形状，F046 要 17 字节裸帧 |
| 把 `ACK` 当写入成功的判据 | `ACK` 只判长度+side，与内容无关 |
| 尝试「写→重启→看 142」 | 已实测否证，142 不是槽位内容的函数 |
| 尝试 USB 裸访问 | 非管理员 + HID `OutputReportByteLength=0`，物理上发不出字节 |
| 认为左右耳 UUID 不同 | Key Max 左右耳同 UUID，设备级 |
