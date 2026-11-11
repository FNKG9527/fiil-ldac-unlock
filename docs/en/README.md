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

**All three FIIL backend domains are now NXDOMAIN** (see [server-status evidence](#why-the-server-is-provably-dead)),
so tapping "Activate" in the official app just spins forever. Your hardware supports LDAC;
a shut-down server is holding it hostage.

This project reverse-engineers the activation path of FIIL+ 3.5.2, brute-scans the whole command
space of the private protocol, and provides **five server-independent alternatives** — plus an
honest, measured list of what is possible and what is not. Every claim carries a `file:line`
reference into the decompiled output.

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

**Step ④ never touches the network.** But the 1.1.0 on-device test added a far more important
fact: **the firmware does validate the license it is given, and a wrong one wipes the existing
unlock state** (see FAQ). So "the server is dead" does not mean "any locally minted code will do" —
the real break is the **server-side signature** in step ③, not step ④.

An equally important measurement: on F046, `142` (authorization) and `143` (toggle) are
**two independent paths** — the LDAC toggle itself does not need a license. See the FAQ entry
"Is LDAC still usable?" below.

The four channels (`UnlockLDACActivity.java:205-254`):

| `type` | Channel | Code | Models |
|---|---|---|---|
| `1` | F43 SDP | `com.fengeek.utils.l1.n0.setLDAC()` | F043 |
| `2` | F39 / Bluetrum | `F39AppSettingRequest.setActivateLdac()` | CC Pro2 / F039 |
| `3` | F048 SDP | `com.fengeek.main.i.d.e.setActivationLdac()` | F048 |
| other | legacy Gaia | `FiilManager.setUnlockLDAC()` → cmd 1968 | F039/F040 older firmware |

Full protocol spec: [PROTOCOL.md](../PROTOCOL.md).

---

## Five approaches

| # | Approach | root | repack | PC | Needs a COM port | Models | Tool |
|---|---|---|---|---|---|---|---|
| 1 | **CC Pro2 hidden backdoor (long-press)** | no | no | no | no | CC Pro2 / F039 only | stock app |
| 2 | **PC serial write** | no | no | yes | **yes** | all | [`src/fiil_ldac.py`](../../src/fiil_ldac.py) |
| 3 | **Local fake server + stock app** | maybe | no | yes | no | all | [`src/fake_server.py`](../../src/fake_server.py) |
| 4 | **Repacked APK with embedded code** | no | yes | yes | no | all | [`src/patch_apk.py`](../../src/patch_apk.py) |
| 5 | **PC direct BLE connection (no COM port)** | no | no | yes | **no** | F046 / F048 (Mate) | [`src/fiil_ble.py`](../../src/fiil_ble.py) |

Least effort first: **1 → 5 → 3 → 2 → 4**.

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

`--proto` (four frame families, see the comparison table in
[docs/PROTOCOL.md](../PROTOCOL.md)):

| Value | Models | Header | Length field covers |
|---|---|---|---|
| `f39` | CC Pro2 / F039 (Bluetrum fragments) | 5 bytes | this fragment's payload only |
| `f43` | F043 (SDP) | 8 bytes | `cmdId` too (`+2`) |
| `f048` | F048 (SDP) | 8 bytes | `cmdId` too (`+2`) |
| `gaia` | F039–F043 legacy (`com.fiil.sdk`) | 8 bytes | **payload only** |

⚠️ `gaia` is new in 1.4.0 and has only been verified at the frame level (byte-for-byte
against the decompiled source); there is no F039–F043 hardware here to test it on.
The LDAC switch command id for the `f048` channel is still not located in the source.

### 3. Local fake server

Run an HTTP server on your LAN impersonating `newservice.fiil.com`, so the stock app believes
the backend is alive and walks its normal activation path.

```bash
python src/fake_server.py --host 0.0.0.0 --port 8080
#   --mode zero     all-zero license (default)
#   --mode random   random 16 bytes
#   --mode echo     echo back the deviceCode (closest to real server)
#   --code "AA..,BB.."  fixed code
```

> ⚠️ 1.1.0 correction: the firmware **does** validate the license. `zero` and `random` only
> exercise the protocol path — they will not produce a working unlock. Use `--code` with a code
> you obtained legitimately.

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

### 5. PC direct BLE connection (1.1.0, verified on hardware)

Approach 2 needs Windows to expose a COM port for the headset, which many models never do.
FIIL earbuds also answer the **same Mate frames over BLE GATT**, so a PC can talk to them directly:

| Role | UUID |
|---|---|
| Service | `0000fdb3-0000-1000-8000-00805f9b34fb` |
| Write | `0000ff17-0000-1000-8000-00805f9b34fb` |
| Notify | `0000ff18-0000-1000-8000-00805f9b34fb` |
| CCCD | `00002902-0000-1000-8000-00805f9b34fb` |

> `0000ff16` exists but **does not accept writes** — measured on hardware.

```bash
pip install bleak

python src/fiil_ble.py scan                 # find FIIL devices (svc 0xFDB3 + mfr 0x0234)
python src/fiil_ble.py status               # read model / firmware / battery / LDAC state
python src/fiil_ble.py backup               # snapshot the current license
python src/fiil_ble.py switch --on          # turn LDAC on (official ordering built in)
python src/fiil_ble.py switch --off
```

Switching LDAC rebuilds the A2DP link, so **the connection dropping is expected** — the tool
reconnects and re-reads `143`/`144` to confirm.

---

## Install

```bash
git clone https://github.com/FNKG9527/fiil-ldac-unlock.git
cd fiil-ldac-unlock
pip install -r requirements.txt
```

`requirements.txt` has two entries: `pyserial>=3.5` (approach 2) and `bleak>=0.22` (approach 5).
Approaches 1, 3 and 4 use the standard library only.

### Platform support

| Platform | 2 (serial) | 3 (fake server) | 4 (repack) | 5 (BLE) |
|---|---|---|---|---|
| Windows | ✅ auto COM port after pairing | ✅ | ✅ | ✅ needs Win10 1809+ |
| Linux | ⚠️ needs `rfcomm bind` or a SPP helper | ✅ | ✅ | ✅ BlueZ ≥ 5.43 |
| macOS | ⚠️ needs `socat` to bridge `/dev/tty.*` | ✅ | ✅ | ✅ macOS 11+ |

### Self-test

No earbuds, no serial port required — verifies the frame bytes against the reverse-engineered spec:

```bash
python src/selftest.py
# 59 passed, 0 failed  (with decompiled artifacts present)
# 38 passed, 0 failed  (without; last 21 are skipped)
```

---

## Repository layout

```
fiil-ldac-unlock/
├── src/                    # the five tools + probe guard + selftest
├── docs/                   # protocol spec, activation flow, troubleshooting (+ en/)
├── examples/               # standalone frame dumper and read-only probe
├── backup/                 # license snapshots from the `backup` subcommand (gitignored)
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

It will **wipe the unlock state**, not brick them. This is the most important correction 1.1.0 made.

Earlier versions inferred "the firmware does not validate the contents" from the vendor backdoor
sending an all-zero license. **That inference was wrong**, and the on-device test disproved it:

| License written | Earbuds ACK | Read back `142` |
|---|---|---|
| `00 ‖ device UUID (16B)` | `00` (success) | **`00` (unlock state cleared)** |
| 17 zero bytes | `00` (success) | `00` |
| 15 checksum variants | `00` (success) | `00` |
| 43 md5/sha1 derivatives | `00` (success) | `00` |

Three conclusions:

1. **ACK only means "the frame was formatted correctly", not "the license was accepted".**
   1.2.0 narrowed this down further by scanning every payload length: the ACK validates
   **"length == 17"** and **"first byte ∈ {0,1}"** and nothing else. The only trustworthy success
   signal is reading back `142` (`getLdacUnlockStatus`).
2. The firmware **does** validate the content. A wrong license silently clears an existing unlock,
   and it does not come back on its own.
3. `activateCode` is **not** a simple derivative of the device UUID, and not a plain checksum —
   it almost certainly contains a server-side salt/key. With the vendor server gone
   (`newservice.fiil.com` NXDOMAIN), **offline forgery is disproven**.

So: **always `backup` first**, and do not expect "just write some code" to unlock anything.

**Is LDAC still usable?**

Yes — but not the way the official UI suggests. On hardware (FIIL Key Max / F046, firmware 3.0.1.1)
`142` (authorization) and `143` (toggle) turned out to be **two independent paths**:

| `142` | `143` | `144` | LDAC actually active |
|---|---|---|---|
| `00` | `01` | `02` | **yes** |

The LDAC toggle itself needs no license; the license only gates whether the official app's UI
allows you to touch that toggle. This project therefore treats **turning LDAC on/off** as the
primary feature (verified on hardware) and keeps "write a license" as a channel for a code you
obtained elsewhere.

One more negative result from 1.2.0: all 255 query commands under `cid=39` were scanned, and
**none of them can read back a written license** — so you can neither forge one nor copy it off
another already-authorized earbud.

**LDAC disappeared after a firmware update.**
Expected; the update clears the activation flag. Re-run your chosen approach.

**Is there any command I must never send while probing?**

Yes — one of them **factory resets** the earbuds.

`setReset` is implemented like this (`com/fengeek/main/i/d/c.java:489-502`): it **only sets
`commandClassifyId(36)`, with no `commandId` and no payload**. So any 5-byte empty frame with
`cid=36` is a factory reset — that is exactly how the test unit was knocked offline during the
cid scan (it disconnected, stopped advertising, and needed a manual power cycle).

Every scanning script must skip `cid=36`. The project ships that guard as
[`src/probe_guard.py`](../../src/probe_guard.py):

```python
from probe_guard import is_safe_cid, assert_safe

if not is_safe_cid(cid):
    continue          # skips cid=36 plus 12 state-changing families
assert_safe(cid, cmd)  # raises UnsafeCommandError
```

Another finding worth recording: `cid=35` is a fifth command family that the firmware implements
but FIIL+ never calls. It does ACK, but its semantics were left unexplored (risk outweighed value).

More in [TROUBLESHOOTING.md](../TROUBLESHOOTING.md).

---

## Why the server is provably dead

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
