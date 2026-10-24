#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NTAG213 NDEF 写入工具（PN532 串口 / HSU）

用法:
  python nfc_write.py --list                                  # 列出串口
  python nfc_write.py --uri "pqfast://dev?i=1101660607..." --port COM3
  python nfc_write.py --read --port COM3                      # 读回验证
  python nfc_write.py --erase --port COM3                     # 清空 NDEF

说明:
  NTAG213 = NFC Forum Type 2，45 页 x 4 字节
    页 0-2  UID / 锁位（只读）
    页 3    CC = E1 10 12 00（出厂已格式化，144 字节 NDEF 区）
    页 4-39 用户区 144 字节
  NDEF 结构: 03 <len> <record> FE
  URI record: D1 01 <plen> 55 <prefix> <uri>
"""
import argparse
import sys
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.exit("需要 pyserial：pip install pyserial")

# ---------------- PN532 HSU 帧 ----------------
# HSU 唤醒：14 字节 0x55 前导 + 唤醒帧
WAKEUP = (bytes([0x55] * 14)
         + bytes([0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF,
                    0x00, 0xFF, 0x00, 0xFF, 0x00, 0xFF]))


def build_frame(data):
    ln = len(data)
    lcs = (0x100 - ln) & 0xFF
    dcs = (0x100 - (sum(data) & 0xFF)) & 0xFF
    return b"\x00\x00\xff" + bytes([ln, lcs]) + data + bytes([dcs, 0x00])


def read_frame(ser, timeout=2.0):
    """返回响应数据（含 D5 前缀），失败返回 None
    注意：PN532 对每条命令先回一个 6 字节 ACK 帧（00 00 FF 00 FF 00），
    真正的响应帧紧随其后，必须跳过 ACK。"""
    t0 = time.time()
    buf = b""
    while time.time() - t0 < timeout:
        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue
        buf += chunk
        while True:
            i = buf.find(b"\x00\x00\xff")
            if i < 0 or len(buf) < i + 5:
                break
            ln = buf[i + 3]
            if len(buf) < i + 5 + ln + 2:
                break
            if ln == 0:                      # ACK 帧，跳过
                buf = buf[i + 6:]
                continue
            return buf[i + 5:i + 5 + ln]
    return None


def cmd(ser, data, timeout=1.5):
    ser.reset_input_buffer()
    ser.write(build_frame(data))
    ser.flush()
    return read_frame(ser, timeout)


# ---------------- 卡片操作 ----------------
def fw_version(ser):
    r = cmd(ser, bytes([0xD4, 0x02]))
    if r and len(r) >= 6 and r[0] == 0xD5 and r[1] == 0x03:
        return "PN532 IC=0x%02X ver=%d.%d" % (r[2], r[3], r[4])
    return None


def sam_config(ser):
    # Normal mode, timeout 0x14, IRQ 0x01
    cmd(ser, bytes([0xD4, 0x14, 0x01, 0x14, 0x01]))


def list_target(ser):
    """返回 UID(bytes) 或 None"""
    r = cmd(ser, bytes([0xD4, 0x4A, 0x01, 0x00]))
    if not r or len(r) < 7 or r[0] != 0xD5 or r[1] != 0x4B:
        return None
    nbtg = r[2]
    if nbtg == 0:
        return None
    # D5 4B NbTg Tg SENS_RES(2) SEL_RES(1) NFCIDLen(1) NFCID...
    uid_len = r[7]
    uid = r[8:8 + uid_len]
    return uid


def data_exchange(ser, payload, timeout=1.0):
    """payload 为卡片命令字节；返回 (status, data)"""
    r = cmd(ser, bytes([0xD4, 0x40, 0x01]) + payload, timeout)
    if not r or len(r) < 3 or r[0] != 0xD5 or r[1] != 0x41:
        return None, b""
    status = r[2]
    return status, r[3:]


def read_page(ser, page, count=1):
    out = b""
    for i in range(count):
        st, d = data_exchange(ser, bytes([0x30, page + i]))
        if st != 0 or len(d) < 16:
            return None
        out += d[:16]
        # 一次 READ 返回 4 页(16字节)，偏移用 4 页为单位
        page += 3
    return out


def write_page(ser, page, data4):
    assert len(data4) == 4
    st, _ = data_exchange(ser, bytes([0xA2, page]) + data4)
    return st == 0


# ---------------- NDEF ----------------
URI_PREFIX = {
    0x00: "", 0x01: "http://www.", 0x02: "https://www.", 0x03: "http://",
    0x04: "https://", 0x05: "tel:", 0x06: "mailto:",
}


def rec_uri(uri, mb=1, me=1):
    """URI 记录。TNF=1(well-known) type='U'"""
    payload = bytes([0x00]) + uri.encode("utf-8")   # 0x00 = 无前缀压缩
    n = len(payload)
    hdr = (0x80 if mb else 0) | (0x40 if me else 0) | 0x10 | 0x01
    if n > 255:
        return bytes([hdr | 0x00, 0x01, n >> 8, n & 0xFF, 0x55]) + payload
    return bytes([hdr, 0x01, n, 0x55]) + payload


def rec_aar(pkg, mb=1, me=1):
    """Android Application Record
       TNF=4(external) type='android.com:pkg' payload=包名
       —— 系统识别到 AAR 才会直接拉起对应 App；
       写成 URI 记录 android://xxx 会被交给浏览器（打不开 App）。"""
    t = b"android.com:pkg"
    p = pkg.encode("utf-8")
    hdr = (0x80 if mb else 0) | (0x40 if me else 0) | 0x10 | 0x04
    if len(p) > 255:
        return bytes([hdr | 0x00, len(t), len(p) >> 8, len(p) & 0xFF]) + t + p
    return bytes([hdr, len(t), len(p)]) + t + p


def build_ndef_aar(pkg):
    """单条 AAR"""
    rec = rec_aar(pkg, mb=1, me=1)
    total = len(rec)
    if total > 254:
        return bytes([0x03, 0xFF, total >> 8, total & 0xFF]) + rec + bytes([0xFE])
    return bytes([0x03, total]) + rec + bytes([0xFE])


def build_ndef_uri_aar(uri, pkg):
    """URI 在前 + AAR 在后（官方推荐顺序）
       URI 负责带参数，AAR 负责锁定用哪个 App 打开。"""
    rec = rec_uri(uri, mb=1, me=0) + rec_aar(pkg, mb=0, me=1)
    total = len(rec)
    if total > 254:
        return bytes([0x03, 0xFF, total >> 8, total & 0xFF]) + rec + bytes([0xFE])
    return bytes([0x03, total]) + rec + bytes([0xFE])


def build_ndef_uri(uri):
    payload = bytes([0x00]) + uri.encode("utf-8")   # 0x00 = 无前缀压缩
    n = len(payload)
    if n > 255:
        rec = bytes([0xC1, 0x01, n >> 8, n & 0xFF, 0x55]) + payload
    else:
        rec = bytes([0xD1, 0x01, n, 0x55]) + payload
    total = len(rec)
    if total > 254:
        msg = bytes([0x03, 0xFF, total >> 8, total & 0xFF]) + rec + bytes([0xFE])
    else:
        msg = bytes([0x03, total]) + rec + bytes([0xFE])
    return msg


def parse_ndef(raw):
    i = 0
    while i < len(raw):
        t = raw[i]
        if t == 0x00:
            i += 1
            continue
        if t == 0xFE:
            break
        if t == 0x03:
            ln = raw[i + 1]
            i += 2
            if ln == 0xFF:
                ln = (raw[i] << 8) | raw[i + 1]
                i += 2
            rec = raw[i:i + ln]
            if len(rec) >= 5 and rec[3] == 0x55:
                pre = URI_PREFIX.get(rec[4], "")
                return pre + rec[5:].decode("utf-8", "replace")
            # AAR: TNF=4, type='android.com:pkg'
            if len(rec) >= 3 and (rec[0] & 0x07) == 0x04:   # TNF 占低 3 位
                # rec = [hdr, type_len, payload_len, type..., payload...]
                tl = rec[1]
                pl = rec[2]
                t = rec[3:3 + tl]
                if t == b"android.com:pkg":
                    return "AAR:" + rec[3 + tl:3 + tl + pl].decode("utf-8", "replace")
                return "EXT:" + t.decode("utf-8", "replace")
            return "<非URI记录> " + rec.hex()
        i += 1
    return None


def erase_user_area(ser, page_start=4, page_end=40):
    """清空用户区，避免旧的 NDEF 残留"""
    for i in range(page_start, page_end):
        write_page(ser, i, b"\x00\x00\x00\x00")


def write_ndef(ser, msg, page_start=4, clean=True):
    """msg: 已构造好的 NDEF 字节（由 build_ndef_* 生成）"""
    if clean:
        erase_user_area(ser, page_start)
    pad = (-len(msg)) % 4
    msg += b"\x00" * pad
    pages = len(msg) // 4
    if page_start + pages > 40:
        sys.exit("内容太长：%d 字节，NTAG213 只有 144 字节" % len(msg))
    for k in range(pages):
        if not write_page(ser, page_start + k, msg[k * 4:k * 4 + 4]):
            sys.exit("写页 %d 失败" % (page_start + k))
    return len(msg)


def read_ndef(ser, page_start=4, size=144):
    data = b""
    page = page_start
    while page < page_start + size // 4:
        st, d = data_exchange(ser, bytes([0x30, page]))
        if st != 0 or len(d) < 16:
            break
        data += d
        page += 4
        if b"\xfe" in data:
            break
    return data


# ---------------- 入口 ----------------
def connect(port, baud):
    ser = serial.Serial(port, baud, timeout=0.2, write_timeout=1)
    ser.write(WAKEUP)
    time.sleep(0.3)
    ser.reset_input_buffer()
    v = None
    for _ in range(3):
        v = fw_version(ser)
        if v:
            break
        time.sleep(0.4)
    if not v:
        ser.close()
        return None, None
    sam_config(ser)
    return ser, v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="列出串口")
    ap.add_argument("--port", help="串口，如 COM3")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--uri", help="要写入的 URI")
    ap.add_argument("--aar", help="要写入的 AAR 包名，如 com.example.app（与 --uri 同用则写 URI+AAR 两条）")
    ap.add_argument("--read", action="store_true", help="读回 NDEF")
    ap.add_argument("--erase", action="store_true", help="清空 NDEF")
    ap.add_argument("--gen", help="只生成 NDEF 字节并打印（不连硬件）")
    a = ap.parse_args()

    if a.list:
        for p in serial.tools.list_ports.comports():
            print(p.device, "-", p.description)
        return

    if a.gen:
        if a.aar:
            msg = build_ndef_uri_aar(a.gen, a.aar)
            print("URI :", a.gen)
            print("AAR :", a.aar)
        else:
            msg = build_ndef_uri(a.gen)
            print("URI :", a.gen)
        print("长度:", len(msg), "字节 / 上限 144")
        print("HEX :", msg.hex())
        return

    if not a.port:
        sys.exit("需要 --port（先用 --list 看串口）")

    ser, ver = connect(a.port, a.baud)
    if not ser:
        sys.exit("没识别到 PN532，检查串口/波特率/接线（HSU 模式）")
    print("设备:", ver)

    uid = list_target(ser)
    if not uid:
        sys.exit("没找到卡片，把标签放到天线上了吗？")
    print("卡片 UID:", uid.hex().upper())

    # 检查 CC
    cc = read_page(ser, 3)
    if cc and cc[:4] != b"\xe1\x10\x12\x00":
        print("⚠ CC =", cc[:4].hex(), "（NTAG213 正常应为 e1101200）")

    if a.erase:
        for i in range(4, 40):
            write_page(ser, i, b"\x00\x00\x00\x00")
        print("已清空用户区")
        return

    if a.read:
        raw = read_ndef(ser)
        print("原始:", raw[:64].hex())
        print("内容:", parse_ndef(raw))
        return

    if not a.uri and not a.aar:
        sys.exit("需要 --uri 或 --aar")

    if a.uri and a.aar:
        print("写入: URI + AAR")
        print("  URI:", a.uri)
        print("  AAR:", a.aar)
        n = write_ndef(ser, build_ndef_uri_aar(a.uri, a.aar))
    elif a.aar:
        print("写入: AAR ->", a.aar)
        n = write_ndef(ser, build_ndef_aar(a.aar))
    else:
        print("写入:", a.uri)
        n = write_ndef(ser, build_ndef_uri(a.uri))
    print("已写 %d 字节，正在读回验证…" % n)
    raw = read_ndef(ser)
    got = parse_ndef(raw)
    if a.aar and a.uri:
        ok = (a.uri in got) and (a.aar in got)
    elif a.aar:
        ok = got == "AAR:" + a.aar
    else:
        ok = got == a.uri
    print(("✅ 验证通过: " if ok else "❌ 读回不一致: ") + str(got))
    ser.close()


if __name__ == "__main__":
    main()
