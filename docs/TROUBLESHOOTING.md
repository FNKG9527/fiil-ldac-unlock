# 常见问题

## 通用

### Q：我的耳机型号不在 README 的表里，能用吗？

先用**只读**方式确认走哪套协议：

```bash
python src/fiil_ldac.py frames --proto f39    # 只看帧，不连接设备
```

对照 [PROTOCOL.md](PROTOCOL.md) 的帧格式，看哪一套的字节结构与你抓到的日志一致。
拿不准就先跑 `examples/probe_headset.py`，它只读不写。

### Q：怎么知道自己耳机现在是不是已激活状态？

```bash
python src/fiil_ldac.py read --port COM5 --proto f39
```

会读 `LDAC_ACTIVATION_STATE`（`0x8E`）和 `LDAC_OPEN_STATE`（`0x8F`）。

### Q：写完码要不要重启耳机？

代码里没有重启调用，写完后 `UnlockLDACActivity` 只是刷新状态。
如果 App 里开关还是灰的，**把耳机放回充电盒再拿出来**（等价于断连重连）通常就够了。

### Q：写完码开关能点了，但一连上还是 AAC / SBC？

LDAC 需要三边同时开：**耳机侧（本项目负责）**、**手机蓝牙设置里的「高清音频」**、
**开发者选项里的「蓝牙音频编解码器 → LDAC」**。
耳机侧开了之后，去手机蓝牙设置里把 LDAC 打开。

---

## 方案一：CC Pro2 长按后门

### Q：长按没反应？

三个前提缺一不可：

1. 必须是 **CC Pro2 / F039**（后门只在这个 Fragment 里）
2. 必须连上耳机（不是只看设备列表）
3. 必须长按**电量数字**本身，不是长按整行或空白区域

`com.fengeek.utils.j.f32868a` 就是 `BuildConfig.DEBUG`，
在 FIIL+ 3.5.2 发布包里它是 `true`——如果厂商以后发了新版本把它改成 `false`，后门就失效了。

### Q：长按之后 LDAC 开关还是灰的？

后门只发一次全零 license。如果没生效，用方案二直接读一次激活状态确认写进去了没有。

---

## 方案二：串口直写

### Q：找不到 COM 口？

Windows 上必须**先在系统设置里配对**，配对成功后设备管理器才会出现「标准串行 over 蓝牙链接」。
如果出现了但 App 里连不上，说明 FIIL 的 SPP 服务只允许一个连接——**先把手机 App 断开**。

Linux 上需要：

```bash
sudo rfcomm bind 0 <MAC地址> 1
# 然后 /dev/rfcomm0 就是串口
```

macOS 上 SPP 支持很差，建议用 `socat` 桥接，或者直接用方案三。

### Q：写入超时 / 没回应？

1. 确认 UUID 对：`d52b47bc-2dea-42c4-b26d-20252fceeeb3`
2. 确认波特率（SPP 虚拟串口通常忽略波特率，但有些驱动要求 115200）
3. 确认 `--proto` 选对
4. 先跑 `read`，能读到数据说明链路通

### Q：`backup` 备份出来的东西是空的？

说明当前耳机里没有 license（未激活状态）。
备份文件会保存一个全零的占位，这是正常的。

### Q：写坏了怎么办？

```bash
python src/fiil_ldac.py activate --port COM5 --zeros --proto f39
```

全零是官方后门用的值，等价于「未激活」。之后再重新写正确的码。

**实在不行**：耳机放回充电盒，长按两只耳机 10 秒恢复出厂设置。

---

## 方案三：假服务器

### Q：App 还是转圈 / 提示网络错误？

按顺序排查：

1. **手机和 PC 在同一局域网**（能 ping 通 PC 的 IP）
2. **PC 防火墙放行 8080**（Windows 第一次运行会弹窗，要点「允许」）
3. **hosts 改对了**：`<PC-IP>  newservice.fiil.com`（中间是空格或 Tab，不是冒号）
4. **App 重启过**（改 hosts 后必须杀掉 App 重开，DNS 有缓存）
5. **用 `-v` 看服务端日志**，确认请求到底有没有打进来

```bash
python src/fake_server.py --host 0.0.0.0 --port 8080 -v
```

### Q：改 hosts 需要 root，我没有 root？

用**代理**方式：手机 Wi-Fi 设置 → 代理 → 手动 → 填 `<PC-IP>:8080`。

App 用的是 OkHttp，默认读系统代理。而且它只发 `http://`，不加密，
所以**不需要装 CA 证书**。

### Q：代理方式下 App 连不上蓝牙了？

有些 App 会检测到代理后降级。这时候只能走 root + hosts。

### Q：假服务器会不会把我的数据发出去？

不会。`src/fake_server.py` 只在本机监听，所有请求都在你的局域网内处理，
没有任何外发代码。你可以自己 `grep -n "urlopen\|requests\|socket.connect" src/fake_server.py` 验证。

---

## 方案四：重打包 APK

### Q：`apktool d` 报错？

94 MB 的 APK 反编译需要：

- **JDK 11+**（`java -version` 确认）
- **至少 4 GB 空闲内存**（apktool 是 Java 写的，大 APK 很吃内存）
- 磁盘空间 ≥ 1 GB

### Q：`apktool b` 失败，报 smali 语法错误？

注入片段里的寄存器编号必须与 `.locals` 匹配。
脚本会自动把 `.locals` 提到 100，如果你手动改过 smali，需要自己确认。

### Q：装上去闪退？

1. `adb logcat | findstr fengeek` 看崩溃栈
2. 大概率是签名问题——必须**先 `adb uninstall com.fengeek.f002`** 再装
3. 如果是 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`，说明没卸载干净

### Q：能保留登录态吗？

**不能。** 签名变了就必须重装，重装就丢数据。
如果你在意登录态，用方案三（假服务器）。

---

## 其它

### Q：固件升级后 LDAC 又没了？

正常。升级会清激活标志。重新跑对应方案即可。

### Q：会不会影响保修？

理论上不会（没有物理改动），但厂商可能有软件层面的检测。
自行判断风险，见 [DISCLAIMER.md](../DISCLAIMER.md)。

### Q：能做成 Android App 吗？

技术上可以（把 `fiil_ldac.py` 的组帧逻辑用 Kotlin 重写，走 `BluetoothSocket`）。
欢迎 PR。

### Q：为什么不做成一键 GUI？

保持最小依赖，命令行更容易审计和复现。
如果你做了 GUI，欢迎作为独立仓库链接过来。
