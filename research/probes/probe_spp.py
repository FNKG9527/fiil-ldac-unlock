"""SPP(COM3) 通道探针：F046 官方 App 走的就是 SPP writeMate，不是 BLE。

假设：F046 固件只认 SPP 通道上的 setActivationLdac(cid=1,cmd=12)，
      BLE 通道虽然回 ACK=00，但固件不处理（所以 142 一直是 00）。

用法：
    python _tools/probe_spp.py status
    python _tools/probe_spp.py activate <HEX32>      # 16 字节 activateCode
    python _tools/probe_spp.py zeros
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "fiil-ldac-unlock"
sys.path.insert(0, str(REPO / "src"))

import serial  # noqa: E402

PORT = "COM3"
BAUD = 115200

CID_SET_PARAM = 1
CID_QUERY = 39
SET_ACTIVATE_LDAC = 12
SET_LDAC_SWITCH = 13
Q_LDAC_UNLOCK = 142
Q_LDAC_SWITCH = 143
Q_CODEC = 144
Q_PID = 132
Q_LEFT_UUID = 138
Q_DEVICE_NAME = 3
Q_VERSION = 2


def build_frame(cid: int, cmd: int, payload: bytes = b"", seq: int = 0) -> bytes:
    """Mate 组帧：[seq][cid][1][0] + ([(plen+2), cmd] if cmd else []) + [plen] + payload"""
    out = bytearray([seq & 0xFF, cid & 0xFF, 0x01, 0x00])
    plen = len(payload)
    if cmd != 0:
        out.append((plen + 2) & 0xFF)
        out.append(cmd & 0xFF)
    out.append(plen)
    out += payload
    return bytes(out)


def read_all(ser, timeout=1.2):
    import time
    buf = bytearray()
    end = time.time() + timeout
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            end = time.time() + 0.25
        else:
            time.sleep(0.03)
    return bytes(buf)


def parse_frames(buf: bytes):
    """Mate 解帧：len_field 在 [4]；len==0 → 5B 空帧；len==1 → 6B 无 cmdId 短帧；否则 7+plen"""
    out = []
    i = 0
    while i + 5 <= len(buf):
        lenf = buf[i + 4]
        if lenf == 0:
            out.append((buf[i + 1], None, b"", buf[i:i + 5]))
            i += 5
        elif lenf == 1:
            out.append((buf[i + 1], None, bytes([buf[i + 5]]), buf[i:i + 6]))
            i += 6
        else:
            need = 7 + (lenf - 2)
            if i + need > len(buf):
                break
            out.append((buf[i + 1], buf[i + 5], buf[i + 7:need + i], buf[i:need + i]))
            i += need
    return out


def show(label, frames):
    if not frames:
        print(f"[{label}] <无回包>")
        return None
    for cid, cmd, pl, raw in frames:
        print(f"[{label}] cid={cid} cmd={cmd} payload={pl.hex()}  raw={raw.hex()}")
    return frames[-1][2]


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    ser = serial.Serial(PORT, BAUD, timeout=0.3)
    print(f"[+] 打开 {PORT} @ {BAUD}")

    # 握手
    ser.write(build_frame(CID_QUERY, 255, bytes([0x02, 0x34])))
    r = read_all(ser, 2.0)
    print(f"[握手] {r.hex() or '<无回包>'}")

    if action in ("status", "activate", "zeros"):
        for label, cmd in (("PID", Q_PID), ("UUID-L", Q_LEFT_UUID), ("142", Q_LDAC_UNLOCK),
                           ("143", Q_LDAC_SWITCH), ("144", Q_CODEC)):
            ser.write(build_frame(CID_QUERY, cmd))
            fr = parse_frames(read_all(ser, 0.9))
            show(label, fr)

    if action == "activate":
        code = bytes.fromhex(sys.argv[2])
        lic = bytes([0]) + code
        print(f"\n[!] 写入 license(SPP) = {lic.hex()}")
        ser.write(build_frame(CID_SET_PARAM, SET_ACTIVATE_LDAC, lic))
        show("ACK", parse_frames(read_all(ser, 2.0)))
        ser.write(build_frame(CID_QUERY, Q_LDAC_UNLOCK))
        show("142", parse_frames(read_all(ser, 1.2)))

    if action == "zeros":
        print("\n[!] 写入全零 license(SPP)")
        ser.write(build_frame(CID_SET_PARAM, SET_ACTIVATE_LDAC, bytes(17)))
        show("ACK", parse_frames(read_all(ser, 2.0)))
        ser.write(build_frame(CID_QUERY, Q_LDAC_UNLOCK))
        show("142", parse_frames(read_all(ser, 1.2)))

    ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
