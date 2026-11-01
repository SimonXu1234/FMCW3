#!/usr/bin/env python3
"""
Post-process the LibreOffice-converted report:

  1. LibreOffice imports <img> as a *linked* picture (r:link + TargetMode=External),
     which shows up as a broken image on any other machine -> convert to an
     embedded picture (r:embed + word/media/*.png).
  2. LibreOffice keeps the pixel width of the picture (34.9 cm!), which runs off
     the page -> rescale to a printable width.
  3. Page size comes out as US Letter with asymmetric margins -> set A4 + 2 cm.

Usage:  .venv/bin/python pc/fix_docx.py
"""

import os
import re
import shutil
import zipfile

SRC = "/home/simon/myProjects/ISAC/FMCW3/report_source.docx"
DST = "/home/simon/myProjects/ISAC/FMCW3/FMCW3_进展报告_2026-11-01.docx"
MEDIA_DIR = "/home/simon/myProjects/ISAC/FMCW3/pc"

A4_W, A4_H = 11906, 16838          # twips
MARGIN = 1134                      # 2 cm
IMG_CX = 5_760_000                 # 16 cm in EMU
ASPECT = 1210.0 / 1320.0           # both figures are 1320x1210 px
IMG_CY = int(IMG_CX * ASPECT)

zin = zipfile.ZipFile(SRC)
doc = zin.read("word/document.xml").decode("utf-8")
rels = zin.read("word/_rels/document.xml.rels").decode("utf-8")

# ---- 1. page size / margins -------------------------------------------------
doc = doc.replace('<w:pgSz w:w="12240" w:h="15840"/>',
                  f'<w:pgSz w:w="{A4_W}" w:h="{A4_H}"/>')
doc = re.sub(r'<w:pgMar [^/]*/>',
             f'<w:pgMar w:left="{MARGIN}" w:right="{MARGIN}" '
             f'w:top="{MARGIN}" w:bottom="{MARGIN}" w:gutter="0" '
             'w:header="567" w:footer="567"/>', doc)

# ---- 2. embed the linked pictures ------------------------------------------
# find external image relationships
ext = re.findall(
    r'<Relationship Id="(rId\d+)" Type="[^"]*/image" Target="file://([^"]+)" TargetMode="External"/>',
    rels)
print(f"linked images found: {len(ext)}")

for i, (rid, path) in enumerate(ext, start=1):
    if not os.path.isfile(path):
        raise SystemExit(f"missing image file: {path}")
    media_name = f"media/image{i}.png"
    rels = rels.replace(
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
        f'officeDocument/2006/relationships/image" Target="file://{path}" '
        f'TargetMode="External"/>',
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
        f'officeDocument/2006/relationships/image" Target="{media_name}"/>')
    doc = doc.replace(f'<a:blip r:link="{rid}">', f'<a:blip r:embed="{rid}">')
    print(f"  {rid} <- {os.path.basename(path)} -> word/{media_name}")

# ---- 3. rescale pictures ----------------------------------------------------
doc = doc.replace('cx="12573000" cy="11525250"', f'cx="{IMG_CX}" cy="{IMG_CY}"')
doc = doc.replace('cx="12573000"', f'cx="{IMG_CX}"')
doc = doc.replace('cy="11525250"', f'cy="{IMG_CY}"')

# ---- 4. repack --------------------------------------------------------------
tmp = DST + ".tmp"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        if item.filename == "word/document.xml":
            zout.writestr(item, doc.encode("utf-8"))
        elif item.filename == "word/_rels/document.xml.rels":
            zout.writestr(item, rels.encode("utf-8"))
        else:
            zout.writestr(item, zin.read(item.filename))
    for i, (rid, path) in enumerate(ext, start=1):
        zout.writestr(f"word/media/image{i}.png", open(path, "rb").read())

zin.close()
shutil.move(tmp, DST)
print(f"\nwritten: {DST}  ({os.path.getsize(DST)} bytes)")

# ---- 5. verify --------------------------------------------------------------
z = zipfile.ZipFile(DST)
names = z.namelist()
d = z.read("word/document.xml").decode("utf-8")
r = z.read("word/_rels/document.xml.rels").decode("utf-8")
print("media parts      :", [n for n in names if n.startswith("word/media/")])
print("r:embed count    :", d.count('r:embed='))
print("r:link count     :", d.count('r:link='))
print("external rels    :", r.count('TargetMode="External"'))
print("tables           :", d.count('<w:tbl>'))
print("A4 page          :", f'w:w="{A4_W}" w:h="{A4_H}"' in d)
print("has chinese text :", "阶段进展报告" in d)
