---
name: 新机型支持
about: 你的 FIIL 耳机型号不在文档表里，但你已经跑通了
title: "[model] "
labels: new-model
assignees: ""
---

## 机型

- 耳机型号：
- 固件版本：
- App 版本（FIIL+ 版本号）：

## 你是怎么跑通的

- [ ] 方案一：CC Pro2 长按后门
- [ ] 方案二：串口直写（`src/fiil_ldac.py`）—— 用的哪个 `--proto`？
- [ ] 方案三：假服务器（`src/fake_server.py`）
- [ ] 方案四：重打包 APK（`src/patch_apk.py`）

## 协议特征

**这是最关键的部分。** 请提供：

1. 你抓到的**完整** TX/RX 十六进制字节
2. 与 [docs/PROTOCOL.md](../../docs/PROTOCOL.md) 里哪一套帧格式对得上
3. 如果有差异，具体差异在哪

```
TX> 
RX< 
```

## 抓包方式

- [ ] Android HCI Snoop Log（`btsnoop_hci.log`）
- [ ] 串口监听（`src/fiil_ldac.py` 的调试输出）
- [ ] Wireshark + 蓝牙适配器
- [ ] 其它：

## 验证结果

- [ ] 写入后 LDAC 开关可以点了
- [ ] 手机侧确认连上了 LDAC（采样率/位深）
- [ ] 音质有明显提升
- [ ] 重启耳机后仍然有效

## 是否愿意提 PR

- [ ] 愿意，我会补充文档
- [ ] 愿意，但我需要指导
- [ ] 只提供数据，不改文档
