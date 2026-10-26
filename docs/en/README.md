# FIIL Earbuds — LDAC Offline Activation Toolkit

> **How to re-enable LDAC on earbuds you already own, after the vendor's activation server went dark.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](../../LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#platform-support)

[简体中文](../../README.md) | **[English](README.md)**

---

## What this is

**LDAC** high-resolution decoding on FIIL earbuds requires a one-time "activation" in the
official FIIL+ app. Technically, the app fetches an `activateCode` from the vendor's server,
writes it to the earbuds over a private Bluetooth channel, and the earbuds flip an internal
flag — only then does the LDAC toggle become available.

**All three FIIL backend domains are now NXDOMAIN** (see [§6](#6-why-the-server-is-provably-dead)),
so tapping "Activate" in the official app just spins forever. Your hardware supports LDAC;
a shut-down server is holding it hostage.

This project reverse-engineers the activation path of FIIL+ 3.5.2 and provides **four
server-independent alternatives**. Every claim carries a `file:line` reference into the
decompiled output.

> This project **only restores functionality on hardware you already own**. It contains no
> APK, no decompiled artifacts, and no copyrighted vendor material. See [DISCLAIMER.md](../../DISCLAIMER.md).

---

## The core finding: only one step needs the network

```
①  Tap "Activate"      F048HomeFragment.B(View)
        ↓
②  Read L/R UUIDs      FiilManager.getUUID(TRUE, cb) / getUUID(FALSE, cb)
        ↓  deviceCode = "<left 32 hex>,<right 32 hex>"
③  HTTP request        GET http://newservice.fiil.com/app/headset/activation/info?deviceCode=xxx
        ↓  server returns {"code":"200","data":"{\"activateCode\":\"...\"}"}
④  UnlockLDACActivity  ← fully OFFLINE from here
        reads "activateCode" from the Intent
        splits on comma into two 16-byte hex halves
        left gets 0x00 prefix, right gets 0x01 → 17 bytes each
        dispatches on the "type" extra to one of four Bluetooth channels
```

**Step ④ never touches the network. If you can manufacture an `activateCode` and put it in the
Intent, the server's death is irrelevant.**

The four channels (`UnlockLDACActivity.java:205-254`):

| `type` | Channel | Code | Models |
|---|---|---|---|
| `1` | F43 SDP | `com.fengeek.utils.l1.n0.setLDAC()` | F043 |
| `2` | F39 / Bluetrum | `F39AppSettingRequest.setActivateLdac()` | CC Pro2 / F039 |
| `3` | F048 SDP | `com.fengeek.main.i.d.e.setActivationLdac()` | F048 |
| other | legacy Gaia | `FiilManager.setUnlockLDAC()` → cmd 1968 | F039/F040 older firmware |

Full protocol spec: [PROTOCOL.md](../PROTOCOL.md).

---

## Four approaches

| # | Approach | root | repack | PC | Models | Tool |
|---|---|---|---|---|---|---|
| 1 | **CC Pro2 hidden backdoor (long-press)** | no | no | no | CC Pro2 / F039 only | stock app |
| 2 | **PC serial write** | no | no | yes | all | [`src/fiil_ldac.py`](../../src/fiil_ldac.py) |
| 3 | **Local fake server + stock app** | maybe | no | yes | all | [`src/fake_server.py`](../../src/fake_server.py) |
| 4 | **Repacked APK with embedded code** | no | yes | yes | all | [`src/patch_apk.py`](../../src/patch_apk.py) |

Least effort first: **1 → 3 → 2 → 4**.

### 1. CC Pro2 long-press backdoor (30 seconds, F039 only)

The app ships a debug backdoor that **never contacts the server**
(`CcPro2NewEleFragment.java:609-650`):

```java
if (com.fengeek.utils.j.f32868a) {          // f32868a = BuildConfig.DEBUG — true in release!
    this.W3.setOnLongClickListener(...);    // W3 = the battery percentage widget
}
// g0(): sends setActivateLdac twice with an all-zero license, no network
```

**How:** stock app → connect CC Pro2 → battery page → **long-press the battery number** →
wait for the LED blink → check the LDAC toggle.

### 2. PC serial write

FIIL's private channel is **SPP / RFCOMM** (UUID `d52b47bc-2dea-42c4-b26d-20252fceeeb3`),
not BLE GATT. Windows maps it to a virtual COM port after pairing, so `pyserial` can talk to it.

```bash
pip install pyserial

python src/fiil_ldac.py list                        # find the COM port
python src/fiil_ldac.py frames --proto f39          # print frames, no connection
python src/fiil_ldac.py backup --port COM5          # back up the current license
python src/fiil_ldac.py activate --port COM5 --zeros --proto f39
python src/fiil_ldac.py switch --port COM5 --on --proto f39
python src/fiil_ldac.py read --port COM5            # verify
```

`--proto`: `f39` (CC Pro2 / F039), `f43` (F043), `f048` (F048).

### 3. Local fake server

Run an HTTP server on your LAN impersonating `newservice.fiil.com`, so the stock app believes
the backend is alive and walks its normal activation path.

```bash
python src/fake_server.py --host 0.0.0.0 --port 8080
#   --mode zero     all-zero license (default)
#   --mode random   random 16 bytes (firmware does not validate contents)
#   --mode echo     echo back the deviceCode (closest to real server)
#   --code "AA..,BB.."  fixed code
```

Then either point `newservice.fiil.com` at your PC in the phone's hosts file (needs root), or
set an HTTP proxy to `<PC-LAN-IP>:8080` (no root needed — the app speaks plain http).

### 4. Repacked APK

Replace the body of `F048HomeFragment.o()` with a direct `startActivity(UnlockLDACActivity)`
carrying a hardcoded code, skipping the network call entirely.

```bash
# Prerequisites: stock APK at <repo>/fiil.apk, apktool.jar at <repo>/tools/,
# JDK 11+, Android SDK build-tools
python src/patch_apk.py decompile
python src/patch_apk.py inject
python src/patch_apk.py build
adb uninstall com.fengeek.f002
adb install -r build/fiil_patched.apk
```

⚠️ Repacking changes the signature — **you must uninstall the original**, losing login state.

---

## Install

```bash
git clone https://github.com/FNKG9527/fiil-ldac-unlock.git
cd fiil-ldac-unlock
pip install -r requirements.txt
```

`requirements.txt` is just `pyserial>=3.5` (approach 2 only). Approaches 1, 3 and 4 use the
standard library only.

### Platform support

| Platform | 2 (serial) | 3 (fake server) | 4 (repack) |
|---|---|---|---|
| Windows | ✅ auto COM port after pairing | ✅ | ✅ |
| Linux | ⚠️ needs `rfcomm bind` or a SPP helper | ✅ | ✅ |
| macOS | ⚠️ needs `socat` to bridge `/dev/tty.*` | ✅ | ✅ |

### Self-test

No earbuds, no serial port required — verifies the frame bytes against the reverse-engineered spec:

```bash
python src/selftest.py
# 22 passed, 0 failed  (with decompiled artifacts present)
# 15 passed, 0 failed  (without; last 7 are skipped)
```

---

## Repository layout

```
fiil-ldac-unlock/
├── src/                    # the four tools + selftest
├── docs/                   # protocol spec, activation flow, troubleshooting (+ en/)
├── examples/               # standalone frame dumper and read-only probe
├── .github/workflows/      # CI: ruff + selftest on Linux/Windows/macOS
├── LICENSE                 # GPL-3.0
├── NOTICE                  # trademarks
├── DISCLAIMER.md           # scope and compliance
└── README.md
```

---

## FAQ

**My model isn't listed.**
Run `python src/fiil_ldac.py frames --proto f39` (prints only, no connection) and compare with
[PROTOCOL.md](../PROTOCOL.md). If unsure, start with the read-only `examples/probe_headset.py`.

**Will an all-zero license brick my earbuds?**
The vendor's own backdoor sends an all-zero license (`CcPro2NewEleFragment.java:642-650`),
which proves the firmware does not validate the contents. Still — **run `backup` first**.

**LDAC disappeared after a firmware update.**
Expected; the update clears the activation flag. Re-run your chosen approach.

More in [TROUBLESHOOTING.md](../TROUBLESHOOTING.md).

---

## 6. Why the server is provably dead

```
PS> Resolve-DnsName newservice.fiil.com
Resolve-DnsName : newservice.fiil.com : DNS name does not exist
PS> Resolve-DnsName sapp.fengeek.com
Resolve-DnsName : sapp.fengeek.com : DNS name does not exist
PS> Resolve-DnsName ms.fiil.com
Resolve-DnsName : ms.fiil.com : DNS name does not exist
```

All three backend domains are NXDOMAIN. Every online feature of the app (activation, OTA,
store, voice) is dead, **while all local Bluetooth features (EQ, ANC, LDAC toggle) still work** —
because those go over SPP and never touch the network.

---

## Contributing

Evidence-backed corrections and new-model test data are welcome. Hard rule:
**no conclusion is merged without a source** — either a `file:line` into the decompiled output,
or a raw log under `docs/evidence/` containing complete TX/RX bytes.
See [CONTRIBUTING.md](../../CONTRIBUTING.md).

## License

Code: **GNU GPL v3.0** ([LICENSE](../../LICENSE)). Docs: **CC BY-SA 4.0**.
Trademarks: [NOTICE](../../NOTICE). Scope and compliance: [DISCLAIMER.md](../../DISCLAIMER.md).
