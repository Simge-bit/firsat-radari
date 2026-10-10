"""DTÖ'ye bildirilen ithalat yasak ve kısıtlamalarını indirir.

Kullanım: python3 tools/kisitlamalar.py  ->  data/kisitlamalar.json
  [{"ulke": ISO2, "tur": [..], "metin", "metin_tr", "baslangic", "belge", "kodlar": [ürün kodu ön ekleri]}]

Kaynak: DTÖ Kantitatif Kısıtlamalar (QR) veritabanı; anahtar .env dosyasındaki WTO_KEY.
Yalnızca yürürlükteki ithalat önlemleri alınır. Her ülkeden gelen her ürüne aynı biçimde uygulanmayan ya da
sıradan bir ihracatçıyı ilgilendirmeyen önlemler (belirli ülkelere yaptırım, tehlikeli atık, kültür varlığı,
nesli tehlikedeki türler, silah, uyuşturucu, kullanılmış mal) NOISE ile elenir.

Kalan metinler tek tek gözden geçirilip çevrilmiştir: data/kisitlama_ceviri.json her özgün ifadenin Türkçesini tutar.
Değeri null olan ifade ihracatçıyı ilgilendirmediği için alınmaz. Listede olmayan (yeni bildirilmiş) ifade
çevirisiz alınır ve betik bunları yazdırır; çevirisi eklenip betik yeniden çalıştırılır.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from radar import sartlar, tarife  # noqa: E402

URL = "https://api.wto.org/qrs/qrs?page={page}"
OUT_FILE = Path(__file__).resolve().parent.parent / "data" / "kisitlamalar.json"
TRANSLATIONS_FILE = OUT_FILE.with_name("kisitlama_ceviri.json")
NOISE = re.compile(
    r"north korea|democratic people|russia|iran|iraq|somalia|liberia|syria|libya|belarus|crimea|sanction|embargo|"
    r"hazardous|waste|déchet|desecho|residuo|cultural|endangered|espèces|especies|cites|ozone|ozono|narcotic|drug|"
    r"estupefac|stupéfiant|weapon|arms|firearm|armes|armas|ammunition|explosiv|nuclear|radioactiv|diamond|kimberley|"
    r"torture|used |usad|second-hand|occasion|counterfeit|pornograph|obscene|psychotrop", re.I)
# Tüm tarife cetvelini kapsayan önlemler ürüne özgü değildir.
MAX_CODES = 400
KINDS = {"P": "yasak", "CP": "kosullu_yasak", "NAL": "lisans"}      # diğer simgeler kotadır


def measures():
    page, last = 1, 1
    while page <= last:
        payload = tarife._get(URL.format(page=page))
        last = payload["meta"]["last_page"]
        yield from payload["data"]
        page += 1


def build():
    iso2_by_code = tarife._iso2_by_wto_code()
    translations = json.loads(TRANSLATIONS_FILE.read_text(encoding="utf-8"))
    result, untranslated = [], set()
    for item in measures():
        kinds = sorted({KINDS.get(measure["symbol"], "kota") for measure in item["measures"]
                        if isinstance(measure, dict) and measure["flow"] == "import"})
        codes = sorted({product["product_code"] for product in item["products"]})
        iso2 = iso2_by_code.get(item["reporter_member"]["code"].lstrip("C"))
        text = re.sub(r"\s+", " ", item["general_description"] or "").strip()
        if not kinds or item["termination_dt"] or not iso2 or not codes or len(codes) > MAX_CODES or NOISE.search(text):
            continue
        if text in translations and translations[text] is None:
            continue
        if text not in translations:
            untranslated.add(text)
        documents = [note for note in item["notified_in"] if note["document_symbol"] != "DRAFT"]
        entry = {"tur": kinds, "metin": text, "metin_tr": translations.get(text), "baslangic": item["in_force_from"],
                 "belge": documents[-1]["document_url"] if documents else "", "kodlar": codes}
        # AB'nin bildirimi her üye için geçerlidir.
        result += [{"ulke": member, **entry} for member in (sorted(sartlar.AB) if iso2 == "EU" else [iso2])]
    OUT_FILE.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for text in sorted(untranslated):
        print("Çevirisi yok:", text[:120])
    return len(result), len({entry["ulke"] for entry in result})


if __name__ == "__main__":
    count, countries = build()
    print(f"{count} kısıtlama, {countries} ülke yazıldı: {OUT_FILE}")
