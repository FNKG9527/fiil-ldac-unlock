# 贡献指南

感谢你想帮忙。这个仓库有一条**硬性规则**：

> **没有来源的结论不合并。**

---

## 什么是最有价值的贡献

按价值排序：

1. **新机型的实测数据** —— 你有一副表里没有的 FIIL 耳机，跑通了某种方案
2. **带证据的勘误** —— 本文档某条 `文件:行号` 对不上，或结论有误
3. **固件版本差异** —— 同一机型不同固件的协议差异
4. **平台适配** —— Linux / macOS 下的串口桥接脚本

---

## 来源要求

结论的「来源」只有两种，二者必居其一：

### A. 反编译产物的 `文件:行号`

```markdown
`com/fengeek/main/f048/fragment/F048HomeFragment.java:652-665`
```

路径相对于 `jadx_out/sources/`。

### B. `docs/evidence/` 下的原始日志

日志文件必须包含：

- **完整的 TX/RX 十六进制字节**（不能是摘要）
- **设备型号与固件版本**
- **采集时间**
- **采集方式**（用什么工具抓的）

格式示例：

```
# 2026-10-12  FIIL CC Pro2  FW 1.2.3
# 工具：Android HCI Snoop Log / btsnoop_hci.log
TX> 00 01 01 10 0F 0C 11 00 00 00 ...
RX< 00 01 02 00 01 ...
```

---

## 提交什么

| 类型 | 方式 |
|---|---|
| 文档勘误 | Pull Request，直接改 `.md` |
| 新机型支持 | 先开 Issue 说明机型/固件/日志，再提 PR |
| 新工具/脚本 | 先开 Issue 讨论，避免白做 |
| 安全问题 | **不要开公开 Issue**，见 [SECURITY.md](SECURITY.md) |

---

## 代码规范

- Python 3.8+，只用标准库（`pyserial` 是唯一例外，且仅方案二需要）
- 每个函数带 docstring，说明它对应哪个逆向位置
- 新增协议常量时，注释里必须写 `文件:行号`
- 不要引入需要编译的依赖
- 改动后必须 `python src/selftest.py` 全绿

```bash
python -m pip install -r requirements.txt
python src/selftest.py
```

---

## Commit 信息

```
<type>: <简短描述>

<可选：为什么这么改>

Refs: <文件:行号 或 evidence 文件路径>
```

`<type>` 取值：`feat` / `fix` / `docs` / `test` / `chore`

---

## 不要提交

- 官方 APK 或任何反编译产物
- 你自己的 `activateCode`（如果它是从厂商那里拿到的）
- 任何包含个人信息（IMEI、MAC、账号）的日志

`.gitignore` 已经覆盖常见情况，但请自行确认。

---

## 审查流程

1. 自动检查（GitHub Actions）：`ruff` + `selftest`
2. 人工检查：**来源是否可验证**
3. 合并

来源不可验证的 PR 会被要求补充，两周无响应则关闭。

---

## 行为准则

见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
