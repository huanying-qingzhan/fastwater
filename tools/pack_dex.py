#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 classes.dex 打入 aapt2 产出的 base.apk（保持 STORED/DEFLATED 合理）"""
import sys
import zipfile

src, dex, dst = sys.argv[1], sys.argv[2], sys.argv[3]

with zipfile.ZipFile(src, "r") as zin:
    items = [(i, zin.read(i.filename)) for i in zin.infolist()]

with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
    for info, data in items:
        zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
        zi.compress_type = info.compress_type
        zi.external_attr = info.external_attr
        zout.writestr(zi, data)
    with open(dex, "rb") as f:
        zout.writestr("classes.dex", f.read())

print("  已写入 classes.dex ->", dst)
