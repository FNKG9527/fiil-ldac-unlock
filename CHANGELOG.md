# 更新日志

本文件格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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

- **`142`（授权）与 `143`（开关）是两条独立路径**。真机实测 `142=00 / 143=01 / 144=02` 时
  LDAC 依然实际工作——即 **开 LDAC 不需要 license**，license 只影响官方 App 的 UI 是否放行开关。
  这是本次逆向对用户最有实际价值的结论。
- 连接后**必须先发 `setUnlock` 握手**（`cid=39 cmd=255 payload={0x02,0x34}`），否则后续命令全部静默。
- `0000ff16` 在实机上**不支持写**，必须用 `0000ff17`。
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

[1.0.0]: https://github.com/FNKG9527/fiil-ldac-unlock/releases/tag/v1.0.0
