# FIIL 耳机 LDAC 离线激活工具集

> **当官方服务器已经下线，如何在自己买的耳机上重新打开 LDAC。**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#平台支持)
[![Protocol](https://img.shields.io/badge/transport-SPP%2FRFCOMM%20%7C%20Bluetrum-orange.svg)](docs/PROTOCOL.md)

**[简体中文](README.md)** | [English](docs/en/README.md)

---

## 这是什么

FIIL 耳机的 **LDAC 高清解码**需要先在官方 App（FIIL+）里点一次「激活」。
激活的本质是：App 从厂商服务器拿到一段 `activateCode`，通过蓝牙写进耳机，
耳机把内部的一个标志位置 1，LDAC 开关才变成可点。

**但 FIIL 的三个后端域名已经全部 NXDOMAIN 了**（详见 [服务器状态证据](#为什么说服务器已经死了)），
官方 App 里点「激活」只会转圈失败——你的耳机硬件明明支持 LDAC，却被一个已经关停的服务器锁住了。

本项目把 FIIL+ 3.5.2 的激活链路完整逆向出来，提供 **4 种不依赖服务器的替代方案**。
所有结论都标注了反编译产物的 `文件:行号`。

> 本项目**只恢复你已购买设备的既有功能**，不提供任何绕过设备安全机制的手段，
> 不包含官方 APK、反编译产物或任何受版权保护的素材。详见 [DISCLAIMER.md](DISCLAIMER.md)。

---

## 核心结论：激活链路只有一步依赖网络

```
①  点「激活」          F048HomeFragment.B(View)
        ↓
②  读左右耳 UUID       FiilManager.getUUID(TRUE, cb) / getUUID(FALSE, cb)
        ↓  拼成 deviceCode = "<左耳32hex>,<右耳32hex>"
③  HTTP 请求           GET http://newservice.fiil.com/app/headset/activation/info?deviceCode=xxx
        ↓  服务器返回 {"code":"200","data":"{\"activateCode\":\"...\"}"}
④  UnlockLDACActivity  ← 从这里开始**完全离线**
        取 Intent 里的 "activateCode"
        按逗号切两段 16 字节 hex
        左耳补 0x00、右耳补 0x01 → 各 17 字节
        按 Intent 里的 "type" 分派到四条蓝牙通道写进耳机
```

**关键：第 ④ 步不联网。只要能造出一个 `activateCode` 字符串塞进 Intent，服务器死不死都无所谓。**

`UnlockLDACActivity` 的四条通道（`UnlockLDACActivity.java:205-254`）：

| `type` | 通道 | 代码位置 | 机型 |
|---|---|---|---|
| `1` | F43 SDP | `com.fengeek.utils.l1.n0.setLDAC()` | F043 |
| `2` | F39 / Bluetrum | `F39AppSettingRequest.setActivateLdac()` | CC Pro2 / F039 |
| `3` | F048 SDP | `com.fengeek.main.i.d.e.setActivationLdac()` | F048 |
| 其它 | Gaia 老协议 | `FiilManager.setUnlockLDAC()` → 命令 1968 | F039/F040 等老固件 |

协议细节见 [docs/PROTOCOL.md](docs/PROTOCOL.md)。

---

## 四种方案

| # | 方案 | 需要 root | 需要重打包 | 需要 PC | 适用机型 | 工具 |
|---|---|---|---|---|---|---|
| 一 | **CC Pro2 隐藏后门（长按）** | 否 | 否 | 否 | 仅 CC Pro2 / F039 | 原版 App |
| 二 | **PC 串口直接写码** | 否 | 否 | 是 | 全机型 | [`src/fiil_ldac.py`](src/fiil_ldac.py) |
| 三 | **本地假服务器 + 原版 App** | 视情况 | 否 | 是 | 全机型 | [`src/fake_server.py`](src/fake_server.py) |
| 四 | **重打包 APK 内嵌激活码** | 否 | 是 | 是 | 全机型 | [`src/patch_apk.py`](src/patch_apk.py) |

按折腾程度从低到高：**一 → 三 → 二 → 四**。

### 方案一：CC Pro2 长按后门（30 秒，仅 F039）

App 里留了一个**连服务器都不问**的调试后门（`CcPro2NewEleFragment.java:609-650`）：

```java
if (com.fengeek.utils.j.f32868a) {          // f32868a = BuildConfig.DEBUG，发布包里是 true
    this.W3.setOnLongClickListener(...);    // W3 = 电量数字控件
}
// g0(): 直接下发两次 setActivateLdac，内容是全零 license，不联网
```

**操作**：原版 App 连上 CC Pro2 → 进电量页 → **长按电量数字** → 等指示灯闪一下 → 看 LDAC 开关是否可点。

### 方案二：PC 串口写码

FIIL 的私有通道是 **SPP / RFCOMM**（UUID `d52b47bc-2dea-42c4-b26d-20252fceeeb3`），
不是 BLE GATT。Windows 配对后会自动映射成虚拟 COM 口，`pyserial` 直接读写即可。

```bash
pip install pyserial

# 1. 耳机与 PC 配对，设备管理器里找到新增的 COM 口
python src/fiil_ldac.py list

# 2. 只看帧，不连接（先确认机型对得上）
python src/fiil_ldac.py frames --proto f39

# 3. 备份当前 license（重要，写坏了还能恢复）
python src/fiil_ldac.py backup --port COM5

# 4. 写码（--zeros = 全零 license，等效方案一的后门）
python src/fiil_ldac.py activate --port COM5 --zeros --proto f39

# 5. 打开 LDAC
python src/fiil_ldac.py switch --port COM5 --on --proto f39

# 6. 验证
python src/fiil_ldac.py read --port COM5
```

`--proto` 取值：`f39`（CC Pro2 / F039）、`f43`（F043）、`f048`（F048）。

### 方案三：本地假服务器

在局域网起一个 HTTP 服务冒充 `newservice.fiil.com`，让原版 App 以为服务器还活着，
从而走完「激活按钮 → 拿 activateCode → 写进耳机」的原始链路。

```bash
# PC 上起服务
python src/fake_server.py --host 0.0.0.0 --port 8080

# 模式
#   --mode zero     全零 license（默认，等效方案一）
#   --mode random   随机 16 字节（固件不校验内容）
#   --mode echo     把 deviceCode 原样回填（最像真服务器）
#   --code "AA..,BB.."  固定激活码
```

然后二选一：

- **改 hosts**（需 root / Magisk）：`<PC局域网IP>  newservice.fiil.com`
- **走 HTTP 代理**（无需 root）：手机 Wi-Fi → 代理 → `<PC局域网IP>:8080`
  （App 只发 http，不加密，不用装证书）

优点：不用卸载 App，登录态和绑定数据全保住。

### 方案四：重打包 APK

把 `F048HomeFragment.o()` 的方法体换成直接 `startActivity(UnlockLDACActivity)` 并带上写死的码，
跳过网络请求。脚本自动找注入点、把 `.locals` 提到 100、注入 smali、回编译、签名。

```bash
# 前置：原版 APK 放 <仓库根>/fiil.apk，apktool.jar 放 <仓库根>/tools/
# JDK 11+ 与 Android SDK build-tools（zipalign / apksigner）

python src/patch_apk.py decompile
python src/patch_apk.py inject                 # 默认全零，或 --code "左32hex,右32hex"
python src/patch_apk.py build

adb uninstall com.fengeek.f002
adb install -r build/fiil_patched.apk
```

⚠️ 重打包后签名变了，**必须先卸载原版**，登录态/绑定数据会丢失。

---

## 安装

```bash
git clone https://github.com/FNKG9527/fiil-ldac-unlock.git
cd fiil-ldac-unlock
pip install -r requirements.txt
```

`requirements.txt` 只有一项：`pyserial>=3.5`（仅方案二需要）。
方案一、三、四只用 Python 标准库。

### 平台支持

| 平台 | 方案二（串口） | 方案三（假服务器） | 方案四（重打包） |
|---|---|---|---|
| Windows | ✅ 配对后自动生成 COM 口 | ✅ | ✅ |
| Linux | ⚠️ 需 `rfcomm bind` 或蓝牙 SPP 工具 | ✅ | ✅ |
| macOS | ⚠️ 需 `socat` 桥接 `/dev/tty.*` | ✅ | ✅ |

### 自检

不需要耳机、不需要串口，验证组帧字节是否与逆向结果一致：

```bash
python src/selftest.py
# 结果：22 通过，0 失败（有反编译产物时）
# 结果：15 通过，0 失败（无反编译产物时，后 7 项 SKIP）
```

---

## 仓库结构

```
fiil-ldac-unlock/
├── src/
│   ├── fiil_ldac.py        # 方案二：串口直写（F39 / F43 / F048 三套帧）
│   ├── fake_server.py      # 方案三：本地假服务器
│   ├── patch_apk.py        # 方案四：APK 重打包注入
│   └── selftest.py         # 离线自检
├── docs/
│   ├── PROTOCOL.md         # 三套帧格式与四条通道的完整规格
│   ├── ACTIVATION_FLOW.md  # 激活链路逐步拆解（含文件行号）
│   ├── TROUBLESHOOTING.md  # 常见问题
│   └── en/                 # English translation
├── examples/
│   ├── dump_frames.py      # 打印各协议帧，不连接设备
│   └── probe_headset.py    # 只读探测：读激活状态与 UUID
├── .github/workflows/ci.yml
├── LICENSE                 # GPL-3.0
├── NOTICE                  # 商标与归属声明
├── DISCLAIMER.md           # 使用边界与合规声明
├── CONTRIBUTING.md
├── SECURITY.md
├── CHANGELOG.md
└── README.md
```

---

## 常见问题

**Q：我的耳机型号不在表里怎么办？**
先用 `python src/fiil_ldac.py frames --proto f39` 之类**只看帧不连接**，对照 [docs/PROTOCOL.md](docs/PROTOCOL.md)
判断机型走哪套协议；拿不准就先跑 `examples/probe_headset.py` 只读探测。

**Q：写全零 license 会不会把耳机写坏？**
官方自己的后门就在发全零 license（`CcPro2NewEleFragment.java:642-650`），
说明固件不校验内容。但**动手前一定先 `backup`**。

**Q：固件升级后 LDAC 又没了？**
正常，升级会清掉激活标志。重新跑一次对应方案即可。

**Q：会不会被判定为盗版？**
不。LDAC 解码能力是耳机硬件本身支持的，激活只是厂商的软件锁；
本项目恢复的是你已购买设备上的既有功能。详见 [DISCLAIMER.md](DISCLAIMER.md)。

更多见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

---

## 为什么说服务器已经死了

```powershell
PS> Resolve-DnsName newservice.fiil.com
Resolve-DnsName : newservice.fiil.com : DNS name does not exist

PS> Resolve-DnsName sapp.fengeek.com
Resolve-DnsName : sapp.fengeek.com : DNS name does not exist

PS> Resolve-DnsName ms.fiil.com
Resolve-DnsName : ms.fiil.com : DNS name does not exist
```

三个后端域名全部 NXDOMAIN。App 里所有联网功能（激活、OTA、商城、语音）都已失效，
**但蓝牙本地功能（EQ、降噪、LDAC 开关）仍然可用**——因为那部分走 SPP，不经过网络。

---

## 贡献

欢迎提交**带证据的**勘误与新机型实测数据。硬性规则：**没有来源的结论不合并。**

来源只有两种：反编译产物的 `文件:行号`，或 `docs/evidence/` 下的原始日志（需含完整 TX/RX 字节）。
详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 安全

发现安全问题请**不要开公开 issue**，按 [SECURITY.md](SECURITY.md) 的流程私下报告。

## 许可

代码以 **GNU General Public License v3.0** 发布，见 [LICENSE](LICENSE)。
文档（`docs/`、`README.md`）以 **CC BY-SA 4.0** 发布。

商标归属见 [NOTICE](NOTICE)。使用边界见 [DISCLAIMER.md](DISCLAIMER.md)。

## 致谢

- [jadx](https://github.com/skylot/jadx) — 反编译
- [apktool](https://apktool.org/) — 资源与 smali 处理
- [pyserial](https://github.com/pyserial/pyserial) — 串口通信
