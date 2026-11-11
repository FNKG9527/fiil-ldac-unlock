#!/usr/bin/env python3
"""
FIIL LDAC 解锁器 —— 图形界面版
=================================

给 ``src/fiil_ble.py`` 套一层 tkinter 界面，把「扫描 → 读状态 → 开 LDAC」这条
真机验证过的路径变成点按钮。命令行能做到的事这里都能做，且所有收发字节仍会
逐行显示，方便对照 ``docs/PROTOCOL.md``。

运行::

    python src/fiil_gui.py

设计约定
--------
* BLE 全部跑在后台线程里的独立 asyncio 事件循环，界面线程永不阻塞。
* 破坏性操作（写授权码、取消激活）一律先弹确认框，并说明后果。
* 「已解锁(142)」和「LDAC 开关(143)」分开显示 —— 实测这两条是独立路径
  （见 docs/DELIVERY_REPORT.md），混在一起会误导用户。

真机验证（FIIL Key Max / F046 / 固件 3.0.1.1）::

    扫描     → B0:F1:A3:A8:7A:C8  svc=FDB3,mfr=0x0234
    读状态   → 142=00 143=01 144=02(LDAC)
    关 LDAC  → 143=00 复核通过
    开 LDAC  → setLowDelay(0) → setLdacSwitch(1) → 断链(预期) → 重连 143=01/144=02
"""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

# 允许 `python src/fiil_gui.py` 与 `python -m src.fiil_gui` 两种跑法
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import fiil_ble as B  # noqa: E402

APP_TITLE = "FIIL LDAC 解锁器"
APP_SUBTITLE = "纯 BLE 直连 · 不依赖 FIIL 官方服务器"


# ----------------------------------------------------------------------------
# 参数容器：fiil_ble 的各子命令都从一个 argparse.Namespace 取参数，
# 这里给界面准备一个同样形状的替身。
# ----------------------------------------------------------------------------


class Options:
    """喂给 fiil_ble.Session / 各 cmd_* 的参数替身。"""

    def __init__(self) -> None:
        self.addr: str | None = None
        self.scan_timeout = 8.0
        self.connect_timeout = 20.0
        self.gap = 0.8
        self.switch_wait = 1.2
        self.reconnect_delay = 4.0
        self.write_response = False
        # 证据落在仓库根的 docs/evidence/，与命令行版保持一致
        self.evidence_dir = str(_HERE.parent / "docs" / "evidence")

        # switch / unlock 专用
        self.on = True
        self.off = False
        self.no_verify = False
        self.yes = False
        self.dry_run = False
        self.code: str | None = None
        self.zeros = False
        self.from_device_uuid = False


# ----------------------------------------------------------------------------
# 把 fiil_ble.Session 的输出去向改到界面：子类化并覆盖 log / save_evidence
# ----------------------------------------------------------------------------


class GuiSession(B.Session):
    """把每一行日志转发给回调，而不是打到 stdout。"""

    sink = None  # type: ignore[assignment]  # 由 App 在构造时注入

    def log(self, s: str = "") -> None:
        self.lines.append(s)
        if GuiSession.sink is not None:
            GuiSession.sink(s)

    def save_evidence(self):  # noqa: D102 - 沿用父类逻辑，只是别 print 到控制台
        if not self.lines:
            return None
        out_dir = Path(self.args.evidence_dir)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = B.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = out_dir / f"ble_{self.tag}_{ts}.log"
            head = [
                "=" * 78,
                f"# FIIL BLE 会话  tag={self.tag}  addr={self.address}  {B.datetime.now():%Y-%m-%dT%H:%M:%S}",
                "=" * 78,
            ]
            path.write_text("\n".join(head + self.lines) + "\n", encoding="utf-8")
            if GuiSession.sink is not None:
                GuiSession.sink(f"[+] 证据已存 {path}")
            return path
        except OSError:
            return None


def _payload_of(frames, query: int) -> bytes:
    return b"".join(f.payload for f in frames if f.cid == B.CID_QUERY and f.cmd == query)


# ----------------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------------


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.opts = Options()
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.busy = False
        GuiSession.sink = self.log_queue.put

        root.title(f"{APP_TITLE} — {APP_SUBTITLE}")
        root.geometry("980x720")
        root.minsize(860, 620)

        self._build_header()
        self._build_body()
        self._build_log()

        self.root.after(80, self._pump_log)
        self.append("=== FIIL LDAC 解锁器 ===")
        self.append("步骤：① 扫描 → ② 选中设备 → ③ 读状态 → ④ 开 LDAC")
        self.append("提示：切 LDAC 时耳机会主动断链重建 A2DP，属正常现象，程序会自动重连复核。")
        self.append("")

    # --- 顶部 ---
    def _build_header(self) -> None:
        bar = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text=APP_TITLE, font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        ttk.Label(bar, text=f"  {APP_SUBTITLE}", foreground="#666").pack(side="left")

    # --- 主体 ---
    def _build_body(self) -> None:
        body = ttk.Frame(self.root, padding=(12, 4, 12, 6))
        body.pack(fill="x")

        # 设备区
        dev = ttk.LabelFrame(body, text="设备", padding=10)
        dev.pack(fill="x")

        row = ttk.Frame(dev)
        row.pack(fill="x")
        ttk.Label(row, text="BLE 地址").pack(side="left")
        self.addr_var = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.addr_var, width=24).pack(side="left", padx=(6, 8))
        self.scan_btn = ttk.Button(row, text="扫描", command=self.do_scan, width=8)
        self.scan_btn.pack(side="left")
        self.status_btn = ttk.Button(row, text="读状态", command=self.do_status, width=10)
        self.status_btn.pack(side="left", padx=6)
        self.backup_btn = ttk.Button(row, text="备份 UUID", command=self.do_backup, width=12)
        self.backup_btn.pack(side="left")

        self.combo = ttk.Combobox(dev, values=[], width=76, state="readonly")
        self.combo.pack(fill="x", pady=(8, 0))
        self.combo.bind("<<ComboboxSelected>>", self._on_pick)

        # 状态区
        st = ttk.LabelFrame(body, text="耳机状态（142 与 143 是两条独立路径）", padding=10)
        st.pack(fill="x", pady=(8, 0))

        grid = ttk.Frame(st)
        grid.pack(fill="x")
        self.kv: dict[str, tk.StringVar] = {}
        fields = [
            ("name", "设备名"),
            ("fw", "固件"),
            ("model", "机型"),
            ("battery", "电量"),
            ("unlock", "LDAC 已解锁 (142)"),
            ("switch", "LDAC 开关 (143)"),
            ("codec", "当前编解码 (144)"),
        ]
        cols = 3
        for i, (key, label) in enumerate(fields):
            r, c = divmod(i, cols)
            grid.columnconfigure(c * 2 + 1, weight=1)
            ttk.Label(grid, text=label + "：", foreground="#555").grid(
                row=r, column=c * 2, sticky="e", padx=(0, 4), pady=3
            )
            var = tk.StringVar(value="—")
            self.kv[key] = var
            ttk.Label(grid, textvariable=var, anchor="w", font=("Microsoft YaHei UI", 9)).grid(
                row=r, column=c * 2 + 1, sticky="ew", padx=(0, 20), pady=3
            )

        # 操作区
        act = ttk.LabelFrame(body, text="操作", padding=10)
        act.pack(fill="x", pady=(8, 0))

        r2 = ttk.Frame(act)
        r2.pack(fill="x")
        self.on_btn = ttk.Button(r2, text="开 LDAC", command=self.do_switch_on, width=14)
        self.on_btn.pack(side="left")
        self.off_btn = ttk.Button(r2, text="关 LDAC", command=self.do_switch_off, width=14)
        self.off_btn.pack(side="left", padx=8)
        self.verify_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r2, text="写后重连复核", variable=self.verify_var).pack(side="left", padx=(4, 0))

        r3 = ttk.Frame(act)
        r3.pack(fill="x", pady=(8, 0))
        ttk.Label(r3, text="授权码").pack(side="left")
        self.code_var = tk.StringVar(value="")
        ttk.Entry(r3, textvariable=self.code_var, width=40).pack(side="left", padx=(6, 6))
        ttk.Label(r3, text="（32 hex ×1 或 ×2，逗号分隔）", foreground="#888").pack(side="left")
        self.write_btn = ttk.Button(r3, text="写入授权码", command=self.do_unlock, width=12)
        self.write_btn.pack(side="left", padx=8)
        self.zero_btn = ttk.Button(r3, text="取消激活", command=self.do_zero, width=10)
        self.zero_btn.pack(side="left")

        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill="x", pady=(8, 0))

    # --- 日志 ---
    def _build_log(self) -> None:
        box = ttk.LabelFrame(self.root, text="收发日志 / 证据", padding=(8, 6))
        box.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.text = scrolledtext.ScrolledText(
            box, height=16, wrap="none", font=("Microsoft YaHei UI", 9), state="disabled"
        )
        self.text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # 日志泵
    # ------------------------------------------------------------------
    def append(self, line: str) -> None:
        self.log_queue.put(line)

    def _pump_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.text.configure(state="normal")
                self.text.insert("end", line + "\n")
                self.text.see("end")
                self.text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(80, self._pump_log)

    # ------------------------------------------------------------------
    # 后台执行框架
    # ------------------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for w in (
            self.scan_btn,
            self.status_btn,
            self.backup_btn,
            self.on_btn,
            self.off_btn,
            self.write_btn,
            self.zero_btn,
        ):
            w.configure(state=state)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _run(self, coro_factory, done_msg: str = "") -> None:
        if self.busy:
            return
        self._set_busy(True)

        def worker() -> None:
            try:
                asyncio.run(coro_factory())
                if done_msg:
                    self.append(done_msg)
            except SystemExit as exc:  # Session 连不上时抛这个
                self.append(f"[!] {exc}")
            except Exception as exc:  # noqa: BLE001
                self.append(f"[!] 出错：{type(exc).__name__}: {exc}")
            finally:
                self.root.after(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def _target(self) -> str | None:
        addr = self.addr_var.get().strip()
        if not addr:
            messagebox.showwarning("还没选设备", "先点「扫描」再选一台耳机，或手动填 BLE 地址。")
            return None
        self.opts.addr = addr
        return addr

    # ------------------------------------------------------------------
    # 各操作
    # ------------------------------------------------------------------
    def _on_pick(self, _evt=None) -> None:
        sel = self.combo.get()
        if not sel:
            return
        addr = sel.split()[0]
        self.addr_var.set(addr)
        self.append(f"[*] 已选择 {addr}")

    def do_scan(self) -> None:
        self.append("")
        self.append("[*] 开始扫描 ...")

        async def job():
            from bleak import BleakScanner

            found = await BleakScanner.discover(timeout=self.opts.scan_timeout, return_adv=True)
            rows, hits = [], []
            for addr, (dev, adv) in sorted(found.items()):
                score = 0
                if B.SERVICE_UUID in [u.lower() for u in adv.service_uuids]:
                    score += 10
                if B.MFR_ID in adv.manufacturer_data:
                    score += 10
                if "FIIL" in (adv.local_name or dev.name or "").upper():
                    score += 5
                tags = []
                if B.SERVICE_UUID in [u.lower() for u in adv.service_uuids]:
                    tags.append("svc=FDB3")
                if B.MFR_ID in adv.manufacturer_data:
                    tags.append("mfr=0x0234")
                name = adv.local_name or "-"
                rows.append(f"{addr}   {adv.rssi} dBm   {name}   {','.join(tags)}".strip())
                if score >= 10:
                    hits.append(addr)
            for r in rows:
                self.append("    " + r)
            if not hits:
                self.append(f"[!] 共 {len(rows)} 台，没有识别到 FIIL 耳机。")
                self.append("    检查：耳机是否已开机 / 是否已在其他设备上连着 / 手机上蓝牙是否占用了它。")
            else:
                self.append(f"[+] 找到 {len(hits)} 台 FIIL：{', '.join(hits)}")
                self.addr_var.set(hits[0])
            self.root.after(0, lambda: self._fill_combo(rows, hits))

        self._run(job)

    def _fill_combo(self, rows: list[str], hits: list[str]) -> None:
        self.combo.configure(values=rows)
        for r in rows:
            if r.startswith(hits[0] if hits else "\0"):
                self.combo.set(r)
                break

    def do_status(self) -> None:
        target = self._target()
        if not target:
            return
        self.append("")
        self.append(f"[*] 读取 {target} 状态 ...")

        async def job():
            async with GuiSession(target, self.opts, tag="gui_status") as s:
                await s.handshake()
                state = await B.query_all(s)
            pid = state.get("机型PID") or b""
            ear = pid[B.PID_EAR_TYPE_INDEX] if len(pid) > B.PID_EAR_TYPE_INDEX else None
            self.root.after(0, lambda: self._apply_state(state, ear))

        self._run(job)

    def _apply_state(self, state: dict, ear: int | None) -> None:
        self.kv["name"].set(state.get("设备名", b"").decode("utf-8", "replace") or "—")
        self.kv["fw"].set(B._hex(state.get("固件版本", b"")) or "—")
        self.kv["model"].set(B.MODELS.get(ear, f"未知({ear})") if ear is not None else "—")
        bat = state.get("电量", b"")
        self.kv["battery"].set(f"{bat[1]}%" if len(bat) >= 2 and bat[1] <= 100 else (B._hex(bat) or "—"))
        self.kv["unlock"].set(B.describe_bool(state.get("LDAC已解锁", b"")))
        self.kv["switch"].set(B.describe_bool(state.get("LDAC开关", b"")))
        self.kv["codec"].set(B.describe_codec(state.get("当前编解码", b"")))

        unlocked = state.get("LDAC已解锁", b"")[:1] == b"\x01"
        self.append("")
        self.append("  ── 状态摘要 ──────────────────────────")
        self.append(f"  机型        {self.kv['model'].get()}")
        self.append(f"  已解锁(142) {self.kv['unlock'].get()}")
        self.append(f"  开关(143)   {self.kv['switch'].get()}")
        self.append(f"  编解码(144) {self.kv['codec'].get()}")
        if not unlocked:
            self.append("  说明：142=否 只表示 FIIL+ App 的 UI 不放行，")
            self.append("        不影响本程序直接开 LDAC（实测已验证）。")

    def do_backup(self) -> None:
        target = self._target()
        if not target:
            return
        self.append("")
        self.append(f"[*] 备份 {target} 的 UUID ...")

        async def job():
            async with GuiSession(target, self.opts, tag="gui_backup") as s:
                await s.handshake()
                lu = await s.send("左耳UUID(138)", B.CID_QUERY, B.Q_LEFT_UUID)
                ru = await s.send("右耳UUID(139)", B.CID_QUERY, B.Q_RIGHT_UUID)
                pid = await s.send("机型PID(132)", B.CID_QUERY, B.Q_PID)
            lv, rv = _payload_of(lu, B.Q_LEFT_UUID), _payload_of(ru, B.Q_RIGHT_UUID)
            pv = _payload_of(pid, B.Q_PID)
            ear = pv[B.PID_EAR_TYPE_INDEX] if len(pv) > B.PID_EAR_TYPE_INDEX else None

            out_dir = Path("backup")
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = B.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = out_dir / f"ble_license_{ts}.txt"
            lines = [
                f"# FIIL BLE license 备份 {ts}",
                f"# addr = {target}",
                f"# earType = {ear}",
                f"left_uuid  = {lv.hex()}",
                f"right_uuid = {rv.hex()}",
            ]
            if len(lv) == 16:
                lines.append(f"license_left  = {B.build_license(lv, 0x00).hex()}")
            if len(rv) == 16:
                lines.append(f"license_right = {B.build_license(rv, 0x01).hex()}")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.append(f"[+] 已备份到 {path}")
            self.append(f"    左耳 UUID = {lv.hex()}")
            self.append(f"    右耳 UUID = {rv.hex()}")

        self._run(job)

    def _switch(self, want: bool) -> None:
        target = self._target()
        if not target:
            return
        self.append("")
        self.append(f"[*] {'打开' if want else '关闭'} LDAC ...")

        async def job():
            lost = False
            async with GuiSession(target, self.opts, tag=f"gui_switch_{'on' if want else 'off'}") as s:
                await s.handshake()
                if want:
                    # 官方顺序（F046HomeFragment.java:395-405）
                    await s.send("setLowDelay(0)", B.CID_SET_LATENCY, 0, bytes([0]), wait=0.6)
                try:
                    frames = await s.send(
                        "setLdacSwitch",
                        B.CID_SET_PARAM,
                        B.SET_LDAC_SWITCH,
                        bytes([1 if want else 0]),
                        wait=self.opts.switch_wait,
                    )
                    acks = [f.ok for f in frames if f.cmd == B.SET_LDAC_SWITCH]
                    if acks and acks[0] is not None:
                        self.append(f"[+] 耳机 ACK：{'成功' if acks[0] else '失败'}")
                except Exception as exc:  # noqa: BLE001
                    lost = True
                    self.append(f"[*] 链路断开（预期）：{type(exc).__name__}: {exc}")

            if not self.verify_var.get():
                self.append("[=] 已跳过复核")
                return
            if lost:
                await asyncio.sleep(self.opts.reconnect_delay)
            self.append("[*] 重连复核 ...")
            async with GuiSession(target, self.opts, tag=f"gui_switch_{'on' if want else 'off'}_verify") as s:
                await s.handshake()
                sw = await s.send("LDAC开关(143)", B.CID_QUERY, B.Q_LDAC_SWITCH)
                cd = await s.send("编解码(144)", B.CID_QUERY, B.Q_CODEC)
            swv, cdv = _payload_of(sw, B.Q_LDAC_SWITCH), _payload_of(cd, B.Q_CODEC)
            ok = (swv[:1] == b"\x01") if want else (swv[:1] == b"\x00")
            self.append(f"  143 = {B.describe_bool(swv)}    144 = {B.describe_codec(cdv)}")
            self.append(
                f"[{'✓' if ok else '!'}] LDAC {'已打开' if want and ok else ('已关闭' if ok else '未达预期')}"
            )
            self.root.after(
                0,
                lambda: (
                    self.kv["switch"].set(B.describe_bool(swv)),
                    self.kv["codec"].set(B.describe_codec(cdv)),
                ),
            )

        self._run(job)

    def do_switch_on(self) -> None:
        self._switch(True)

    def do_switch_off(self) -> None:
        self._switch(False)

    def do_unlock(self) -> None:
        target = self._target()
        if not target:
            return
        text = self.code_var.get().strip()
        if not text:
            messagebox.showwarning("缺少授权码", "请填 32 个十六进制字符（16 字节）的 activateCode。")
            return
        try:
            blocks = B.parse_activate_codes(text)
        except ValueError as exc:
            messagebox.showerror("授权码格式不对", str(exc))
            return

        warn = (
            "即将把授权码写入耳机。\n\n"
            f"目标：{target}\n"
            f"共 {len(blocks)} 段（F046 只需 1 段，F048 左右各 1 段）\n\n"
            "⚠ 写错内容会清掉耳机已有的解锁状态，且无法恢复。\n"
            "⚠ 命令返回 ACK 不代表耳机接受，写入后必须回读「已解锁(142)」才算成功。\n\n"
            "确认写入？"
        )
        if not messagebox.askyesno("确认写入授权码", warn):
            return

        self.append("")
        self.append(f"[*] 写入 {len(blocks)} 段授权码 ...")

        async def job():
            async with GuiSession(target, self.opts, tag="gui_unlock") as probe:
                await probe.handshake()
                pv = _payload_of(await probe.send("机型PID(132)", B.CID_QUERY, B.Q_PID), B.Q_PID)
            ear = pv[B.PID_EAR_TYPE_INDEX] if len(pv) > B.PID_EAR_TYPE_INDEX else None
            if ear is not None and ear not in B.LICENSE_CAPABLE_EAR_TYPES:
                self.append(f"[!] 机型 earType={ear} 的协议族没有 setActivationLdac，无法写授权码。")
                return

            plan = [(B.build_license(blocks[0], 0x00), "左耳")]
            if ear == 48 or len(blocks) > 1:
                src = blocks[1] if len(blocks) > 1 else blocks[0]
                plan.append((B.build_license(src, 0x01), "右耳"))

            async with GuiSession(target, self.opts, tag="gui_unlock_write") as s:
                await s.handshake()
                for lic, label in plan:
                    await s.send(
                        f"setActivationLdac({label})", B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, lic, wait=1.2
                    )

            await asyncio.sleep(self.opts.reconnect_delay)
            self.append("[*] 重连回读（唯一可信判据）...")
            async with GuiSession(target, self.opts, tag="gui_unlock_verify") as s:
                await s.handshake()
                uv = await s.send("LDAC已解锁(142)", B.CID_QUERY, B.Q_LDAC_UNLOCK)
            uvv = _payload_of(uv, B.Q_LDAC_UNLOCK)
            good = uvv[:1] == b"\x01"
            self.append(f"  142 = {B.describe_bool(uvv)}")
            self.append("[✓] 授权码被接受" if good else "[!] 142 仍为 0 —— 耳机没接受这份授权码")
            self.root.after(0, lambda: self.kv["unlock"].set(B.describe_bool(uvv)))

        self._run(job)

    def do_zero(self) -> None:
        target = self._target()
        if not target:
            return
        msg = (
            "即将写入 17 字节全零 license —— 这是官方的「取消激活」原语。\n\n"
            "（依据 F046HomeFragment.java:93-96）\n\n"
            "写完耳机会变成未授权状态，且无法自行恢复。确认？"
        )
        if not messagebox.askyesno("确认取消激活", msg):
            return
        self.append("")
        self.append("[*] 写入全零 license（取消激活）...")

        async def job():
            async with GuiSession(target, self.opts, tag="gui_zero") as s:
                await s.handshake()
                await s.send(
                    "setActivationLdac(全零)", B.CID_SET_PARAM, B.SET_ACTIVATE_LDAC, bytes(17), wait=1.2
                )
            self.append("[+] 已发送「取消激活」原语")

        self._run(job)


def main() -> int:
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
