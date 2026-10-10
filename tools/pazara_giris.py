"""Ticaret Bakanlığı'nın iki resmi listesinden pazara giriş verisi üretir.

Kullanım: python3 tools/pazara_giris.py
  -> data/musavirlikler.json  {ISO2: [{"sehir", "eposta"}]}
  -> data/fuarlar.json        {ISO2: [{"ad", "baslangic", "bitis", "konu", "sehir"}]}

Gerekli paketler (yalnızca bu betik için): pymupdf, openpyxl. Ülke adları için node gerekir.
Müşavir ve ataşelerin kişisel adları bilerek alınmaz; yalnızca ofisin şehri ve kurumsal e-postası saklanır.
"""

import io
import json
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

import fitz
import openpyxl

DATA = Path(__file__).resolve().parent.parent / "data"
OFFICES_PDF = "https://ticaret.gov.tr/data/6412c89b13b87628d4049302/Ticaret_Musavirliklerimiz_ve_Ataseliklerimiz.pdf"
FAIRS_XLSX = "https://ticaret.gov.tr/data/68d6439c13b876c2509a564c/2026_bireysel.xlsx"

# Listelerde resmi addan farklı yazılan ülkeler.
ALIASES = {
    "ABD": "US", "A.B.D.": "US", "BAE": "AE", "B.A.E.": "AE", "INGILTERE": "GB", "BIRLESIK KRALLIK": "GB",
    "RUSYA FEDERASYONU": "RU", "S. ARABISTAN": "SA", "S.ARABISTAN": "SA", "GUNEY AFRIKA CMH.": "ZA",
    "GUNEY AFRIKA CUMHURIYETI": "ZA", "GUNEY KORE CUMHURIYETI": "KR", "KORE CUMHURIYETI": "KR", "G. KORE": "KR",
    "CIN HALK CUMHURIYETI": "CN", "CEK CUMHURIYETI": "CZ", "IRAN ISLAM CUMHURIYETI": "IR",
    "MAKEDONYA": "MK", "BOSNA HERSEK": "BA", "BOSNA-HERSEK": "BA", "KONGO DEMOKRATIK CUMHURIYETI": "CD",
    "FILDISI SAHILLERI": "CI", "HONG KONG": "HK", "TAYVAN": "TW", "MYANMAR": "MM", "BELARUS": "BY",
    "DOMINIK CUMHURIYETI": "DO", "KIRGIZ CUMHURIYETI": "KG", "HOLLANDA KRALLIGI": "NL",
    "DEMOKRATIK KONGO CUMHURIYETI": "CD", "KONGO DEM.CMH.": "CD", "EKVATOR": "EC", "EKVATOR CUMHURIYETI": "EC",
    "FILDISI SAHILI": "CI", "FILISTIN": "PS", "GUNEY SUDAN CUMHURIYETI": "SS", "NIJER CUMHURIYETI": "NE",
    "SURIYE ARAP CUMHURIYETI": "SY", "Y.ZELLANDA": "NZ", "ZAMBIYA CUMHURIYETI": "ZM",
}
# Artık kullanılmayan kodlar; güncel kodla aynı Türkçe adı taşıdıkları için eşleşmeyi bozarlar (FX ve FR: "Fransa").
RETIRED = {"AN", "BU", "CS", "DD", "DY", "FX", "HV", "NH", "RH", "SU", "TP", "UK", "VD", "YD", "YU", "ZR"}
# Ticaret verisinde karşılığı olmadığı için bilerek atlananlar.
SKIPPED = {"KUZEY KIBRIS TURK CUMHURIYETI"}
_FOLD = str.maketrans("ÇĞİIÖŞÜÂÎÛ", "CGIIOSUAIU")


def fold(text):
    return re.sub(r"\s+", " ", str(text).replace("i", "İ").upper().translate(_FOLD)).strip()


def tr_title(text):
    """Türkçe harf kurallarıyla baş harfleri büyütür (BERLİN -> Berlin, IRAK -> Irak)."""
    def word(match):
        w = match.group(0)
        return w[0] + w[1:].replace("İ", "i").replace("I", "ı").lower()
    return re.sub(r"[^\W\d_]+", word, re.sub(r"\s+", " ", str(text)).strip())


def fetch(url):
    request = urllib.request.Request(urllib.parse.quote(url, safe=":/"), headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(request, timeout=120).read()


def country_codes():
    """Türkçe ülke adı (büyük harf, ASCII) -> ISO2. Adlar tarayıcıyla aynı kaynaktan (CLDR) alınır."""
    script = ('const n = new Intl.DisplayNames(["tr"], {type: "region"}); const o = {};'
              'for (let a = 65; a < 91; a++) for (let b = 65; b < 91; b++) { const c = String.fromCharCode(a, b);'
              'try { const t = n.of(c); if (t && t !== c) o[c] = t; } catch (e) {} } console.log(JSON.stringify(o));')
    names = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    codes = {fold(name): iso2 for iso2, name in names.items() if iso2 not in RETIRED}
    codes.update(ALIASES)
    return codes


def offices(codes, unmatched):
    result = {}
    country = ""
    for page in fitz.open(stream=fetch(OFFICES_PDF), filetype="pdf"):
        for table in page.find_tables().tables:
            for row in table.extract():
                cells = [(cell or "").replace("\n", " ").strip() for cell in row]
                emails = re.findall(r"[\w.\-]+@ticaret\.gov\.tr", " ".join(cells))
                if not emails:
                    continue
                country = cells[0] or country       # ülke hücresi yalnızca ilk şehirde doludur
                iso2 = codes.get(fold(country))
                if not iso2:
                    if fold(country) not in SKIPPED:
                        unmatched.add(country)
                    continue
                # Şehir hücresi boş olan ek ofis (ör. AB nezdindeki temsilcilik) bir önceki ofisin şehrindedir.
                city = tr_title(cells[1]) or (result.get(iso2) or [{"sehir": ""}])[-1]["sehir"]
                result.setdefault(iso2, []).append({"sehir": city, "eposta": emails[0].lower()})
    return result


def end_date(start, raw):
    """Bitiş tarihini düzeltir: listedeki metin biçimli ya da yılı hatalı tarihler başlangıç yılına göre okunur."""
    text = str(raw or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", text) and text[:10] >= start:
        return text[:10]
    found = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    day, month = (found.group(3), found.group(2)) if found else (None, None)
    if not found:
        found = re.match(r"(\d{1,2})\.(\d{1,2})\.", text)
        if found:
            day, month = found.group(1).zfill(2), found.group(2).zfill(2)
    candidate = f"{start[:4]}-{month}-{day}" if day else start
    return candidate if candidate >= start else start


def fairs(codes, unmatched):
    result = {}
    sheet = openpyxl.load_workbook(io.BytesIO(fetch(FAIRS_XLSX)), read_only=True).worksheets[0]
    for row in list(sheet.iter_rows(values_only=True))[1:]:
        _, name, start, end, subject, city, country = row[:7]
        if not (name and start and country):
            continue
        iso2 = codes.get(fold(country))
        if not iso2:
            if fold(country) not in SKIPPED:
                unmatched.add(str(country).strip())
            continue
        result.setdefault(iso2, []).append({
            "ad": re.sub(r"\s+", " ", str(name)).strip(), "baslangic": str(start)[:10], "bitis": end_date(str(start)[:10], end),
            "konu": re.sub(r"\s+", " ", str(subject or "")).strip(), "sehir": tr_title(city or "")})
    for items in result.values():
        items.sort(key=lambda fair: fair["baslangic"])
    return result


if __name__ == "__main__":
    codes, unmatched = country_codes(), set()
    for name, data in (("musavirlikler", offices(codes, unmatched)), ("fuarlar", fairs(codes, unmatched))):
        (DATA / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{name}: {len(data)} ülke, {sum(len(items) for items in data.values())} kayıt")
    if unmatched:
        print("Eşleşmeyen ülke adları (ALIASES'e eklenmeli):", sorted(unmatched))
