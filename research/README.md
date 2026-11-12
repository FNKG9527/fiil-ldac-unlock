# FIIL LDAC 解锁研究全记录

本目录保存这次研究的**完整过程材料**：探针脚本、原始收发日志、时间线、以及**所有判断失误**。

保留失败记录是这个仓库存在的主要理由——结论本身（"做不到"）只占一行，
而"为什么做不到、试过什么、错在哪里"才是可复用的东西。

> 所有材料已脱敏：设备 UUID（即发给激活服务器的 `deviceCode`）、本机路径、
> 手机型号与 adb 序列号、内网 IP、用户名均已替换为占位符。
> 耳机 MAC 地址与耳机状态数据按本人要求保留原样。

---

## 目录

- [1. 研究对象与最终结果](#1-研究对象与最终结果)
- [2. 代价：一台已解锁的耳机变成未解锁](#2-代价一台已解锁的耳机变成未解锁)
- [3. 时间线](#3-时间线)
- [4. 66 个候选 license 的测试记录](#4-66-个候选-license-的测试记录)
- [5. 四次判断失误](#5-四次判断失误)
- [6. 协议层的关键发现](#6-协议层的关键发现)
- [7. 为什么这条路走不通](#7-为什么这条路走不通)
- [8. 材料索引](#8-材料索引)

---

## 1. 研究对象与最终结果

| 项目 | 内容 |
|---|---|
| 耳机 | FIIL Key Max（机型族 F046，earType 46） |
| 固件 | `03 00 01 01`（3.0.1.1） |
| 连接方式 | Bluetooth LE，service `0000fdb3-…`，写 `0000ff17`，通知 `0000ff18` |
| App | FIIL+ `com.fengeek.f002` 3.5.2（versionCode 175） |
| 手机 | Redmi K50 Ultra，Android 15（API 35） |
| 最终结果 | **`activateCode` 无法离线伪造** |

耳机侧 GATT 只有一个 vendor service：

```
SERVICE 0000fdb3-0000-1000-8000-00805f9b34fb
    CHAR 0000ff18  notify, read                                    ← 通知
    CHAR 0000ff16  read, write                                     ← 可写，与 ff17 等价
    CHAR 0000ff17  write-without-response, write                   ← 主要写入通道
```

---

## 2. 代价：一台已解锁的耳机变成未解锁

这台耳机是**用户通过官方渠道正常激活过**的。研究过程中为了找固件真正接受的 license 形态，
向它写入了大量候选，其中第一次写入就把原有授权状态清掉了。

**耳机本身没有损坏**：能开机、能连接、能听歌，`143`（开关）可读可写。
**失去的是 LDAC 授权状态**：手机侧 `mCodecsSelectableCapabilities` 从含 LDAC 变成只有 AAC/SBC。

### 时间线铁证

```
2026-11-11 22:54:52   142 = 01   ← 官方激活状态，正常
2026-11-11 22:56:06   142 = 01
2026-11-11 22:58:17   142 = 01
2026-11-11 22:59:50   写入 license = 00 || 设备UUID16B
2026-11-11 23:00:01   142 = 00   ← 从此再未恢复
```

对应日志：`logs/ble_status_20261111_225452.log` → `logs/ble_unlock_write_20261111_225950.log`
→ `logs/ble_unlock_verify_20261111_230001.log`。

### 为什么备份救不回来

研究开始时做过一次备份，内容为：

```
license_left  = 00 || <设备UUID16B>
license_right = 01 || <设备UUID16B>
```

但 `00 || UUID` 这个形态**恰好就是被固件拒绝的那个**（见第 4 节）。
备份记录的是"我以为的 license 构造方式"，不是"耳机里真实的授权数据"——
后者从来无法读取，因为协议里没有任何 license 回读命令（第 6 节）。

**教训：没有可回读的备份，就不该在已激活的设备上做破坏性写入。**

---

## 3. 时间线

### 第一阶段：逆向 App（无破坏性）

- 反编译 FIIL+ 3.5.2，定位 `UnlockLDACActivity.java:205-254` 的四通道分派
- 找到 `setActivationLdac` = `cid=1` / `cmdId=12` / payload = 17 字节 license
- 确认 `activateCode` 全部来自服务器 JSON，客户端零生成逻辑
- 确认官方后门（`CcPro2NewEleFragment.java:640-650` 长按电量）只在 F039/CC Pro2 上成立

### 第二阶段：打通纯 BLE 开关链路（成功）

```
扫描   → B0:F1:A3:A8:7A:C8  svc=FDB3  mfr=0x0234
握手   → 00 27 01 00 04 FF 02 02 34  →  00 27 02 00 03 FF 01 01 FF
读 142 → 06 27 01 00 02 8E 00        →  payload=01  （当时已授权）
写开关 → 02 01 01 00 03 0D 01 01     →  02 01 02 00 03 0D 01 00  （ACK 成功）
```

这一段是成功的：`143` 可以自由开关并回读。

### 第三阶段：试图伪造 license（失败，且造成损失）

累计 66 个候选，全部 ACK 成功但 `142` 不变。见第 4 节。

### 第四阶段：手机侧验证（推翻旧结论）

把手机真正连上后读 `dumpsys bluetooth_manager`，才发现此前"LDAC 在工作"的判断不成立。
见第 5 节第 2 条。

---

## 4. 66 个候选 license 的测试记录

判定方法：写完立刻回读 `142`。翻回 `01` 才算命中。

| 组别 | 候选数 | 内容 | 结果 |
|---|---|---|---|
| A. 基础形态 | 4 | `00‖UUID` / `01‖UUID` / 全零 / 左右各写一次 | 全拒 |
| B. 结构变体 | 4 | `UUID‖00` / 裸 UUID / 尾字节 00 / 尾字节 FF | 全拒 |
| C. 校验和 | 15 | sum8、xor8、CRC16(hi/lo)、neg-sum8，放第 15 或第 0 字节 | 全拒 |
| D. 派生哈希 | 43 | md5/sha1/sha256 × (原始/hex小写/hex大写/加 PID) × 5 种盐 × 4 种拼接 | 全拒 |

### 关键观察：ACK 与是否被接受无关

`setActivationLdac` 的 ACK 是**形状校验**，不是内容校验：

| payload 长度 | 首字节 | ACK `payload[0]` |
|---|---|---|
| 17 | `0x00` / `0x01` | `0x00`（成功） |
| 17 | `0x02` / `0x03` / `0xFF` | `0x01`（失败） |
| 1–16、18–24 | 任意 | `0x01` |

也就是说：**只要给 17 字节且首字节是 0 或 1，命令一律回"成功"，无论后面 16 字节是什么。**
这也是为什么 66 个错误候选全都拿到了 `00` 的 ACK。

**唯一有效的判据是回读 `142`。**

### 一条失败的捷径：把设备 UUID 当 license

曾怀疑"license 就是设备自己的 UUID"，因为 Key Max 的 `0x8C` 查询会返回设备 UUID：
`42 50 32 36 32 30 35 12 00 3B 51 45 06 20 BB 78`。

写入 `00 || UUID` 后 `142` 仍为 00 → 否证。

更重要的是，后来查源码发现 **`0x8C` 根本不是 license 回读口**，它是 `getWindAdaptive`（防风噪），
定义在 `com/fengeek/main/i/d/f.java:315-329`（F049 机型类）。
它返回 UUID 只是因为**固件对所有未实现的命令号都回同一个默认响应（设备 UUID）**。
0x8D、0x8D 之外的其他未知命令号也验证了这一点。

> 这条经验很值钱：**收到 16 字节数据不等于找到了回读口，也可能是默认响应。**

---

## 5. 四次判断失误

全部保留，因为它们比结论更有用。

### 失误 1：把「未知命令的默认响应」当成 license 回读口

- **错误判断**：`0x8C`/`0x8D` 返回 16 字节，且写入 DEADBEEF 标记后仍返回同样的值 → 认为找到了回读口。
- **实际情况**：那 16 字节是**设备 UUID**，固件对任何未实现的命令号都返回它。
- **发现方式**：grep 命令号来源，查到 `0x8C` = `getWindAdaptive`（`f.java:315-329`），与 LDAC 无关。
- **教训**：先查命令号在源码里的定义，再判断回包含义。别从数据形状反推语义。

### 失误 2：把「耳机侧 144=02」当成「LDAC 正在工作」

- **错误判断**：读到 `142=00 / 143=01 / 144=02`，得出"未授权也能用 LDAC"的结论，并写进了
  README、PROTOCOL.md §7.2、CHANGELOG 和代码提示，影响 1.1.0~1.4.2 共四个版本。
- **实际情况**：那几次读数时**手机根本没连耳机**（`A2dpStateMachine: state=Disconnected`）。
  耳机侧 `144` 在未连接状态下没有参考意义。
- **推翻方式**：手机连上后读 `mCodecsSelectableCapabilities`，只有 AAC/SBC；
  `mCodecConfig` 实际协商 AAC。`143` 在 01/00 之间来回切，`mCodecConfig` 始终 AAC。
- **教训**：**判断编解码是否生效必须看对端（手机）的协商结果**，不能只看耳机自己报的状态。
  这也是本项目对"真机验证"这个概念理解最深的一次修正。

### 失误 3：以为恢复出厂后耳机不广播了

- **错误判断**：盲扫时误发 `cid=36`（`setReset`，裸帧即恢复出厂）后，多轮 10 秒扫描都扫不到耳机，
  于是断定"耳机需要手动开机才能恢复"。
- **实际情况**：耳机一直在广播，是 **10 秒扫描窗口太短**。
  改成 `BleakScanner.discover(timeout=20, return_adv=True)` 后一次命中。
- **教训**：bleak 在 Windows 上扫描间歇广播设备需要更长窗口 + `return_adv=True`。

### 失误 4：早期认为 `0xFF16` 不可写

- **错误判断**：项目文档长期写着"ff16 不支持写，必须用 ff17"。
- **实际情况**：GATT 枚举显示 `ff16` 属性是 `read,write`，实测与 ff17 行为完全一致。
- **根源**：早期那次尝试**没发握手帧**，耳机对一切命令静默，被误判成"这个特征不可用"。
- **教训**：`setUnlock` 握手（`cid=39 cmd=255 payload={0x02,0x34}`）不发，后续全部静默。
  没回包时先怀疑流程，别先怀疑硬件。

---

## 6. 协议层的关键发现

### 握手是强制的

```
TX  00 27 01 00 04 FF 02 02 34
RX  00 27 02 00 03 FF 01 FF
```

不发这一帧，耳机对后续**所有**查询完全静默。

### 机型号在 PID 回包的第 2 字节

`getPID`（`cid=39 cmd=132`）返回 `00 2E 01`，`0x2E` = 46 = F046。
七个机型族的 `MainFragment` 都按 `buff[1]` 校验，不是 `buff[0]`。

### 机型能力矩阵（七个机型族全核对）

| 机型族 | `setLdacSwitch` | `getLdacSwitchStatus`(143) | `getLdacUnlockStatus`(142) | `setActivationLdac`(12) |
|---|:---:|:---:|:---:|:---:|
| F045 | ✗ | ✗ | ✗ | ✗ |
| **F046** | ✓ | ✓ | ✓ | ✓ |
| F047 | ✗ | ✗ | ✗ | ✗ |
| **F048** | ✓ | ✓ | ✓ | ✓ |
| F049 | ✓ | ✓ | ✗ | ✗ |
| F051 | ✓ | ✓ | ✗ | ✗ |
| F053 | ✓ | ✓ | ✗ | ✗ |

只有 F046/F048 存在「授权」概念。F049/F051/F053 能开关 LDAC 但协议里没有 142、没有写 license
的方法 —— **这三款的 LDAC 本来就不需要解锁**。

### 固件确实校验 license 内容

`setActivationLdac` 的 6 个调用点全部是"写 license"本身，**后面没有任何"提交/生效"的第二条命令**：

- `F046HomeFragment.java:95` —— 取消激活（17 个零）
- `F046UnlockLDACActivity.java:116` —— 单次写左耳，首字节硬编码 0
- `UnlockLDACActivity.java:238` / `:244` —— type=3 时左右各一次
- 定义在 `i/d/c.java:287`、`i/d/e.java:442`

写错内容会**清掉已有授权**且不自动恢复，说明固件在收到 license 时就地校验并覆盖了状态位。

---

## 7. 为什么这条路走不通

四个方向全部堵死：

| 方向 | 结论 | 证据 |
|---|---|---|
| **服务端** | 全 APK 仅 5 个 fiil 域名，全部 NXDOMAIN；旧 IP `39.106.10.142:8085` timeout | `logs/` 无相关记录，见 `probes/probe_dns.py` 运行结果 |
| **客户端** | `activateCode` 命中 139 处，全部是 `JSON.parseObject(data).getString("activateCode")`，零生成逻辑 | 反编译源码 |
| **原生层** | 29 个 `.so`：`libBluetoothData.so` 只有数组切分 JNI；`libitls.so` 是阿里 ID²；`libdevInfo.so` 是广告 SDK | `nm`/`strings` 扫描 |
| **日志** | Logan 加密日志已成功解密（AES-128-CBC，key=`0123456789012345`，gzip 单元），但只含连接与读状态会话，无 `activateCode` | `probes/decrypt_logan.py` |

另外几个限定条件：手机无 root、App 非 debuggable、无 btsnoop 抓包，
所以**当初激活成功时的真实报文已不可恢复**。

### 唯一的例外：F049/F051/F053

这三款机型协议里根本没有授权概念，用户本来就能直接用 LDAC —— 不需要任何破解。

---

## 8. 材料索引

### `probes/` — 探针脚本（29 个）

| 脚本 | 用途 |
|---|---|
| `scan_wide.py` | 宽窗口 BLE 扫描（20s + `return_adv=True`），按 SVC/MFR/名字三重打分 |
| `probe_ldac_ble.py` | 最早的 LDAC BLE 探针：`status` / `cancel` / `activate` / `switch` |
| `probe_uuid.py` | 读左右耳 UUID / PID / 版本 |
| `probe_license_oracle.py` | 批量测 license 候选，用 `142` 当判据 |
| `probe_license_struct.py` | 结构性候选（前缀/后缀/裸 UUID） |
| `probe_license_length.py` | 长度扫描（1~24 字节），建立 ACK 对照表 |
| `probe_ack_layout.py` | 11 种前缀与长度组合，确认 ACK 只校验形状 |
| `probe_readback.py` | DEADBEEF 标记实验，找 license 回读口（失败，见失误 1） |
| `probe_unknown_q.py` / `probe_unknown2.py` | 未知命令号探测 |
| `probe_cid_sweep.py` | cid 全扫（含触发 `cid=36` 恢复出厂的那次） |
| `probe_query_sweep.py` | cid=39 查询命令全扫（255 条） |
| `probe_ff16.py` | ff16 vs ff17 写入对照（见失误 4） |
| `probe_mimic_official.py` | 完整复刻官方激活流程 |
| `probe_spp.py` | SPP/RFCOMM 通道尝试（Windows 上不可用） |
| `gatt_enum.py` | GATT 服务树完整枚举 |
| `ldac_matrix.py` | A2DP 协商 × `143` 开关对照实验 |
| `ldac_watch.py` | 持续轮询 142/143/144 的状态监控 |
| `decrypt_logan.py` | Logan 加密日志解密 |
| `cleanup_8c.py` | 清理 DEADBEEF 标记 |
| `probe_dns.py` | 域名存活探测 |
| `probe_setkey.py` / `probe_setkey2.py` | 按键映射命令扫描 |

脚本已参数化路径，但**未做通用化打磨**——它们是为这一台设备、这一次研究临时写的，
保留原始形态便于对照日志。运行前请自行检查副作用，尤其是 `cid=36` 相关。

### `logs/` — 原始收发日志（58 个）

全部为 `fiil_session` 格式的原始 TX/RX 十六进制记录，覆盖：

- `ble_status_*` —— 9 项状态完整读取
- `ble_unlock_write_*` / `ble_unlock_verify_*` —— 每次 license 写入与回读
- `ble_switch_on/off_*` —— `143` 开关操作
- `ble_probe_*` —— 各类探针
- `ble_matrix_*` —— A2DP 对照实验
- `ble_watch_*` —— 状态监控

### 其它

- [`redact.py`](redact.py) —— 脱敏脚本（可复现脱敏过程）
- [../docs/PROTOCOL.md](../docs/PROTOCOL.md) —— 协议完整文档
- [../docs/ACTIVATION_FLOW.md](../docs/ACTIVATION_FLOW.md) —— 激活流程逆向
- [../docs/DELIVERY_REPORT.md](../docs/DELIVERY_REPORT.md) —— 交付报告（含失败结论）

---

## 致谢与免责

这次研究在一个真实用户的设备上完成，并且付出了上面描述的代价。
把失败过程完整公开，是希望后来者不必再用另一副耳机去验证同样的死胡同。

本项目仅供协议研究与个人学习。不包含官方 APK、反编译产物或任何受版权保护的素材。
详见 [../DISCLAIMER.md](../DISCLAIMER.md)。
