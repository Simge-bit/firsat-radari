"""Ticaret Bakanlığı'nın Türk Gümrük Tarife Cetveli'nden 6 haneli Türkçe ürün sözlüğü üretir.

Kullanım: python3 tools/gtip_sozluk.py   ->  data/urunler.json
Gerekli paket: python-calamine (yalnızca bu betik için; site çalışırken gerekmez).
"""

import io
import json
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from python_calamine import CalamineWorkbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from radar import comtrade  # noqa: E402

SOURCE = "https://ticaret.gov.tr/data/5dee4b8813b876e93804be6f/2026 TGTC.zip"
EXPORT_YEAR = 2024
OUT_FILE = Path(__file__).resolve().parent.parent / "data" / "urunler.json"

HEADING = re.compile(r"^\d\d\.\d\d$")
SUBCODE = re.compile(r"^\d{4}\.\d[\d.]*$")
DASHES = re.compile(r"^((?:-\s*)+)")


def clean(text):
    return re.sub(r"\s+", " ", text).strip(" :")


def parse_chapter(workbook):
    """Satırları (kod, seviye, tanım) öğelerine çevirir; alt satıra taşan tanımları birleştirir."""
    items = []
    for sheet in range(len(workbook.sheet_names)):
        for row in workbook.get_sheet_by_index(sheet).to_python():
            code = str(row[0]).strip() if row else ""
            text = str(row[1]).strip() if len(row) > 1 else ""
            if not text or text in ("EŞYANIN TANIMI", "2"):
                continue
            dashes = DASHES.match(text)
            if HEADING.match(code):
                items.append([code, 0, text])
            elif SUBCODE.match(code) or (not code and dashes):
                # Tiresiz kodlu satır (ör. 0702.00) pozisyonun kendisidir.
                level = dashes.group(1).count("-") if dashes else 0
                items.append([code, level, text[dashes.end():] if dashes else text])
            elif not code and items:
                # Devam satırı: satır sonu tiresiyle bölünmüş kelimeler bitiştirilir.
                previous = items[-1][2].rstrip()
                items[-1][2] = previous.rstrip("- ") + text if previous.endswith("-") else previous + " " + text
    return items


def build():
    quoted = urllib.parse.quote(SOURCE, safe=":/")
    request = urllib.request.Request(quoted, headers={"User-Agent": "Mozilla/5.0"})
    archive = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(request, timeout=120).read()))
    chapters = sorted(name for name in archive.namelist() if name.endswith(".xls") and "NOTLARI" not in name)

    products = {}
    for name in chapters:
        stack = []  # (seviye, tanım)
        current = None
        for code, level, text in parse_chapter(CalamineWorkbook.from_filelike(io.BytesIO(archive.read(name)))):
            text = clean(text)
            while stack and stack[-1][0] >= level:
                stack.pop()
            digits = code.replace(".", "")
            if len(digits) >= 6 and not HEADING.match(code):
                hs6 = digits[:6]
                if hs6 not in products:
                    # Kodun kendi satırıysa tanımı yola eklenir; daha derin bir alt kırılımsa eklenmez.
                    own = len(digits) == 6 or set(digits[6:]) == {"0"}
                    path = [t for _, t in stack] + ([text] if own else [])
                    products[hs6] = {"path": path, "children": []}
                    current = hs6 if own else None
                elif hs6 == current:
                    products[hs6]["children"].append(text)
            stack.append((level, text))

    # Comtrade'de karşılığı olmayan kodlar (ulusal özel kodlar vb.) aramada çıkmasın: rapor üretilemez.
    known = comtrade.product_codes()
    products = {hs6: entry for hs6, entry in products.items() if hs6 in known}

    # Türkiye'nin ihracat değeri: aramada aynı kelimeyle eşleşen ürünlerden yaygın olanı öne almak için.
    exports = comtrade.exports_by_product(comtrade.TURKIYE, EXPORT_YEAR)
    for hs6, entry in products.items():
        entry["export"] = round(exports.get(hs6, 0))

    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(products, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return products


if __name__ == "__main__":
    result = build()
    print(f"{len(result)} ürün kodu yazıldı: {OUT_FILE}")
