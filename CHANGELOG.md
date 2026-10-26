# 更新日志

本文件格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
