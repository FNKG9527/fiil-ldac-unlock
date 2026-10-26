# 激活链路逐步拆解

> 本文把 FIIL+ 3.5.2 的 LDAC 激活流程按代码执行顺序拆开，
> 每一步都给出 `文件:行号`。路径相对于反编译产物根目录。

---

## 0. 一句话总结

**只有「向服务器要 activateCode」这一步需要网络；拿到字符串之后全是离线蓝牙操作。**

---

## 1. 入口：用户点「激活」

📖 `com/fengeek/main/f048/fragment/F048HomeFragment.java:344-350`

```java
public /* synthetic */ void B(View view) {
    com.fengeek.utils.f0.d(f29875a, "onClick: 激活", 3);
    if (q(true)) {          // 连接检查
        return;
    }
    m();                    // 继续
}
```

绑定在 `:597-601`：

```java
this.f29877c.E.setOnClickListener(... B ...);   // 激活按钮
this.f24504r.setOnClickListener(... D ...);     // LDAC 开关
```

### 连接检查 `q(boolean)`

📖 `:686-688`

```java
private boolean q(boolean isToast) {
    return !isConnect(true) || isSingleConnect(isToast);
}
```

- 没连上 → 拦截
- 只有单耳 → 拦截（并 toast「单耳不允许操作」）

---

## 2. 读左右耳 UUID

📖 `:633-650`（`m()`）

```java
private void m() {
    FiilManager.getInstance().getUUID(true,  new <左耳回调>);
    FiilManager.getInstance().getUUID(false, new <右耳回调>);
}
```

两个回调最终都调用 `o()`（`:249` 和 `:270` 附近的 `onResult`）。

### UUID 从哪来

- **F39 通道**：`F39LdacUuidRequest` 查 `0x8A`（左）/ `0x8B`（右）
- **其它通道**：`FiilManager.getUUID()` 内部按机型走对应协议

---

## 3. 拼 deviceCode 并发请求

📖 `:652-665`（`o()`）

```java
public void o() {
    ...
    String str = NewBlueToothUtils.getInstance().byteToHexStr(this.f29885k, "")
               + ","
               + NewBlueToothUtils.getInstance().byteToHexStr(this.f29886l, "");
    if (str.equals(",")) {
        return;                        // 两个都空，放弃
    }
    networkingGet(h.a.c.f47048a + str, new b());
}
```

`h.a.c.f47048a` = `http://newservice.fiil.com/app/headset/activation/info?deviceCode=`

最终请求：

```
GET http://newservice.fiil.com/app/headset/activation/info?deviceCode=00112233...,FFEEDDCC...
```

---

## 4. 解析服务器响应

📖 `com/fengeek/main/f039new/ui/fragment/CcPro2NewEleFragment.java:222-262`

```java
// 内部类 b 实现 p0.d（网络回调）
JSONObject obj = new JSONObject(data);
String code = obj.optString("code");
if (!"200".equals(code)) { toast(msg); return; }

JSONObject inner = new JSONObject(obj.getString("data"));   // data 是字符串！
String activateCode = inner.optString("activateCode");
String orderSn      = inner.optString("orderSn");

if (!TextUtils.isEmpty(activateCode)) {
    // → UnlockLDACActivity, type=2
} else if (TextUtils.isEmpty(orderSn)) {
    // → 购买页
} else {
    // → 订单页
}
```

⚠️ **`data` 是字符串化的 JSON**，要先 `optString` 再 `new JSONObject`。
假服务器如果直接返回嵌套对象，App 会解析失败。

---

## 5. 写进耳机（离线）

📖 `com/fengeek/main/heat_info_fragment/ldac/UnlockLDACActivity.java`

### onCreate

```java
// :265-271
this.f31480g.setText(intent.getStringExtra("activateCode"));
this.f31482i = intent.getIntExtra("type", 0);
if (this.f31482i == 2) {
    // 初始化 F39SharedViewModel（只有 F39 需要）
}
```

### h() 分派

```java
// :205-254
String[] parts = code.split(",");
byte[] left16  = hexStrToByteArray(parts[0]);
byte[] right16 = hexStrToByteArray(parts[1]);

byte[] left  = new byte[17];
byte[] right = new byte[17];
System.arraycopy(left16,  0, left,  1, 16);
System.arraycopy(right16, 0, right, 1, 16);
left[0]  = 0;    // 左耳
right[0] = 1;    // 右耳

switch (type) {
    case 1: /* F43  SDP    */ break;
    case 2: /* F39  Bluetrum*/ break;
    case 3: /* F048 SDP    */ break;
    default:/* Gaia 1968  */ break;
}
```

### 单耳保护

📖 `:141-145`

```java
if (heatsetType == 1) {
    Toast("单耳不允许操作");
    return;             // 不执行 h()
}
```

### 成功回调

📖 `:194-202`

```java
if (f31484k == 2) {
    startActivity(new Intent(this, UnlockSuccessToastActivity.class));
}
```

---

## 6. 开关 LDAC（激活之后）

📖 `F048HomeFragment.java:354-371`（`D(View)`）

```java
public /* synthetic */ void D(View view) {
    if (q(true)) return;

    if (v0.getBoolean(ctx, com.fengeek.main.l.a.c1.f32000a)) {
        N();                          // 已确认过 → 直接切
    } else if (this.f29884j) {
        N();                          // 本地状态已解锁 → 直接切
    } else {
        new com.fengeek.main.l.a.c1(ctx, new <回调>).show();
        // ↑ 未解锁时弹提示框（引导去激活）
    }
}
```

也就是说：**激活状态是 LDAC 开关的前置条件**。
没激活时点开关只会弹「请先激活」的对话框。

---

## 7. CC Pro2 的隐藏后门（跳过整个网络环节）

📖 `CcPro2NewEleFragment.java:609-616` + `:642-650`

```java
// :609-616
if (com.fengeek.utils.j.f32868a) {              // f32868a = BuildConfig.DEBUG
    this.W3.setOnLongClickListener(new View.OnLongClickListener() {
        @Override public boolean onLongClick(View v) { g0(); return true; }
    });
}

// :642-650
private void g0() {
    F39SharedViewModel.sendRequest(
        F39AppSettingRequest.setActivateLdac(new byte[17]));
    F39SharedViewModel.sendRequest(
        F39AppSettingRequest.setActivateLdac(new byte[]{1, 0, ...}));
    // 没有 networkingGet，没有 activateCode 字符串
}
```

📖 `com/fengeek/utils/j.java:8`

```java
public static boolean f32868a = true;    // 就是 BuildConfig.DEBUG，发布版没关
```

**这是整个逆向里最有价值的一条**：它证明了

1. 写码不需要服务器
2. 固件不校验 license 内容（官方自己发全零）
3. `type=2`（F39）通道的完整调用方式

---

## 8. 时间线：用户实际经历了什么

```
2023 之前   买耳机 → App 激活 → 服务器发码 → 写入 → LDAC 可用
2024-2025   FIIL 业务收缩，App 停止更新
2026-10     newservice.fiil.com / sapp.fengeek.com / ms.fiil.com 全部 NXDOMAIN
            新买的耳机（或恢复出厂/升级固件后）无法激活
            但硬件 LDAC 能力还在，只是标志位没置 1
```

本项目做的事：**用 4 种方式绕过第 ③ 步，把第 ④ 步照原样执行一遍。**

---

## 9. 相关文件索引

| 文件（相对 `jadx_out/sources/`） | 作用 |
|---|---|
| `com/fengeek/main/f048/fragment/F048HomeFragment.java` | F048 入口：激活按钮、开关、UUID、请求 |
| `com/fengeek/main/f039new/ui/fragment/CcPro2NewEleFragment.java` | F039 入口 + 隐藏后门 + 响应解析 |
| `com/fengeek/main/f046/fragment/F046HomeFragment.java` | F043 入口 |
| `com/fengeek/main/heat_info_fragment/ldac/UnlockLDACActivity.java` | **核心**：四条通道分派 |
| `com/fengeek/utils/l1/n0.java` | F43 通道门面 |
| `com/fengeek/utils/l1/v0/a.java` | F43 SDP 组帧 |
| `com/fengeek/utils/l1/v0/d.java` | F43 license 命令 |
| `com/fengeek/utils/l1/v0/f.java` | F43 开关命令 |
| `com/fengeek/utils/l1/v0/i.java` | F43 UUID 与协议号 |
| `com/fengeek/main/i/b.java` | F048 BluetoothStream + 组帧 |
| `com/fengeek/main/i/d/e.java` | F048 激活命令 |
| `com/bluetrum/devicemanager/z.java` | F39 组帧与分片 |
| `com/bluetrum/devicemanager/f39/request/F39AppSettingRequest.java` | F39 APP_SETTING |
| `com/bluetrum/devicemanager/f39/request/F39LdacUuidRequest.java` | F39 UUID 查询 |
| `com/fiil/sdk/command/u.java` | Gaia 通道（F039 老固件） |
| `com/fiil/sdk/gaia/father/Gaia.java` | Gaia 命令号表 |
| `h/a/c.java` | 服务器 URL 常量 |
| `com/fengeek/utils/j.java` | `BuildConfig.DEBUG` 常量 |
