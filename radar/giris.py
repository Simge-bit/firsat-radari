"""Pazara giriş verisi: Ticaret Müşavirlikleri, destek kapsamındaki yurt dışı fuarlar ve uzaklık.

Müşavirlik ve fuar verisi tools/pazara_giris.py ile Ticaret Bakanlığı'nın resmi listelerinden,
ülke konumları tools/dunya.py ile, ithalat kısıtlamaları tools/kisitlamalar.py ile DTÖ'den üretilir.
"""

import datetime
import functools
import json
import math
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
_FOLD = str.maketrans("ÇĞİIÖŞÜÂÎÛ", "CGIIOSUAIU")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
WIDE_SCOPE = 40                            # bundan fazla ürün kodunu kapsayan kısıtlama "geniş kapsamlı" sayılır

# Ürün kodu ön eki -> fuarın konusunda ve adında aranacak kelimeler, özelden genele sıralı.
# En uzun eşleşen ön ek kullanılır. Fuar listesinde konu serbest metindir; eşleşme bu yüzden
# "ilgili olabilir" düzeyindedir. Kelimeler büyük harf ve ASCII yazılır, kelime başından aranır;
# kısa kelimeler başka kelimelerin içinde eşleşmesin diye \\b ile bitirilir ("HALI", "HALINDE" ile eşleşmez).
_FOOD = ["GIDA", "FOOD", "HELAL", "ORGANIK"]
_KEYWORDS = {
    "01": ["HAYVANCILIK", "TARIM"], "02": ["ET VE", "ET URUN", "HELAL", *_FOOD], "03": ["SU URUN", "SEAFOOD", "BALIK", *_FOOD],
    "04": [r"SUT\b", "DAIRY", *_FOOD], "05": ["HAYVANCILIK", "TARIM"],
    "06": ["CICEK", "BAHCE", "PEYZAJ", "FLORAL", "TARIM"],
    "07": ["SEBZE", "MEYVE", "FRUIT", "PRODUCE", "YAS MEYVE", *_FOOD, "TARIM"],
    "08": ["MEYVE", "FRUIT", "KURUYEMIS", "KURU MEYVE", "PRODUCE", *_FOOD, "TARIM"],
    "0801": ["KURUYEMIS", "KURU MEYVE", "SEKERLEME", "CIKOLATA", "SNACK", *_FOOD],
    "0802": ["KURUYEMIS", "KURU MEYVE", "SEKERLEME", "CIKOLATA", "SNACK", *_FOOD],
    "09": [r"CAY\b", "KAHVE", "BAHARAT", "COFFEE", *_FOOD], "10": ["HUBUBAT", "TAHIL", *_FOOD, "TARIM"],
    "11": ["UNLU MAMUL", "DEGIRMEN", *_FOOD], "12": ["TOHUM", *_FOOD, "TARIM"], "13": _FOOD, "14": ["TARIM"],
    "15": ["ZEYTIN", "BITKISEL YAG", *_FOOD], "16": _FOOD, "17": ["SEKERLEME", "SEKER", "SWEETS", *_FOOD],
    "18": ["CIKOLATA", "SEKERLEME", "SWEETS", *_FOOD], "19": ["UNLU MAMUL", "BISKUVI", "SEKERLEME", *_FOOD],
    "20": _FOOD, "21": _FOOD, "22": ["ICECEK", "SARAP", "WINE", "DRINK", *_FOOD], "23": [r"YEM\b", "EVCIL HAYVAN", "HAYVANCILIK"],
    "24": ["TUTUN"],
    "25": ["MADEN", "INSAAT", "YAPI"], "2515": ["DOGAL TAS", "DOGALTAS", "MERMER", "STONE", "MARMO", "ZEMIN", "YAPI", "INSAAT"],
    "2516": ["DOGAL TAS", "DOGALTAS", "MERMER", "STONE", "MARMO", "ZEMIN", "YAPI", "INSAAT"],
    "2523": ["CIMENTO", "BETON", "YAPI", "INSAAT"], "26": ["MADEN"], "27": ["ENERJI", "PETROL", "DOGAL GAZ"],
    "28": ["KIMYA"], "29": ["KIMYA"], "30": ["ILAC", "ECZA", "PHARMA", "SAGLIK", "MEDIKAL"], "31": ["GUBRE", "TARIM", "KIMYA"],
    "32": ["BOYA", "KAPLAMA", "COATING", "KIMYA"],
    "33": ["KOZMETIK", "GUZELLIK", "BEAUTY", "KISISEL BAKIM", "PARFUM", "PERFUME", "COSMO", "DERMA"],
    "34": ["TEMIZLIK", "DETERJAN", "KOZMETIK", "KIMYA"], "35": ["KIMYA"], "36": ["KIMYA"], "37": ["KIMYA"], "38": ["KIMYA"],
    "39": ["PLASTIK", "AMBALAJ", "PACK", "KAUCUK"], "40": ["KAUCUK", "LASTIK", "PLASTIK", "OTOMOTIV"],
    "41": ["DERI"], "42": ["SARACIYE", "CANTA", "DERI", "MODA"], "43": ["KURK", "DERI", "MODA"],
    "44": ["AHSAP", "AGAC", "ORMAN", "MOBILYA", "YAPI", "INSAAT"], "45": ["AHSAP", "AGAC"], "46": ["HEDIYELIK", "DEKORASYON"],
    "47": ["KAGIT"], "48": ["KAGIT", "AMBALAJ", "PACK", "KIRTASIYE"], "49": ["BASKI", "MATBAA", "KITAP", "PRINT"],
    **{chapter: ["IPLIK", "KUMAS", "TEKSTIL", "TEXTIL"] for chapter in ("50", "51", "52", "53", "54", "55", "56", "58", "59", "60")},
    "57": [r"HALI\b", "YER DOSEME", "ZEMIN KAPLAMA", "DOMOTEX", "EV TEKSTIL", "DEKORASYON"],
    "61": ["KONFEKSIYON", "HAZIR GIYIM", "GIYIM", "MODA", "FASHION", "TEKSTIL", "TEXTIL"],
    "62": ["KONFEKSIYON", "HAZIR GIYIM", "GIYIM", "MODA", "FASHION", "TEKSTIL", "TEXTIL"],
    "63": ["EV TEKSTIL", "HOME TEXTILE", "HEIMTEXTIL", "TEKSTIL"],
    "64": ["AYAKKABI", "SHOE", "SARACIYE", "DERI", "MODA"], "65": ["MODA", "KONFEKSIYON"], "66": ["HEDIYELIK"], "67": ["MODA", "HEDIYELIK"],
    "68": ["DOGAL TAS", "DOGALTAS", "MERMER", "STONE", "ZEMIN", "YAPI", "INSAAT"],
    "69": ["SERAMIK", "BANYO", "YAPI", "INSAAT", "EV ESYA"], "70": ["CAM ENDUSTRI", "CAM VE", "GLASS", "ZUCCACIYE", "EV ESYA", "YAPI"],
    "71": ["MUCEVHER", "KUYUM", "TAKI", "JEWEL", "DEGERLI MADEN", "SAAT"],
    "72": ["DEMIR", "CELIK", "STEEL", "METAL", "DOKUM", "YAPI", "INSAAT"],
    "73": ["DEMIR", "CELIK", "HIRDAVAT", "METAL", "DOKUM", "YAPI", "INSAAT"],
    "74": ["METAL", "DOKUM"], "75": ["METAL"], "76": ["ALUMINYUM", "METAL", "YAPI", "INSAAT"], "78": ["METAL"], "79": ["METAL"],
    "80": ["METAL"], "81": ["METAL"], "82": ["HIRDAVAT", "EL ALET", "MUTFAK", "METAL"], "83": ["HIRDAVAT", "METAL", "YAPI"],
    "84": ["MAKINE", "ENDUSTRI", "OTOMASYON"],
    "8415": ["IKLIMLENDIRME", "ISITMA", "SOGUTMA", "HVAC", "KLIMA"],
    "8418": ["SOGUTMA", "IKLIMLENDIRME", "BEYAZ ESYA", "EV ALET", "EV ESYA", "HVAC"],
    "8422": ["AMBALAJ", "PAKETLEME", "PACK", "BEYAZ ESYA", "MAKINE"], "8450": ["BEYAZ ESYA", "EV ALET", "EV ESYA"],
    "85": ["ELEKTRIK", "ELEKTRONIK", "ENERJI"], "8516": ["BEYAZ ESYA", "EV ALET", "EV ESYA", "ELEKTRIK"],
    "8539": ["AYDINLATMA", "LIGHT", "ELEKTRIK"], "8544": ["KABLO", "ELEKTRIK", "ENERJI"],
    "86": ["DEMIRYOLU", "RAYLI", "ULASIM"], "87": ["OTOMOTIV", "TASIT", "AUTOMECHANIKA"],
    "88": ["HAVACILIK", "SAVUNMA"], "89": ["DENIZCILIK", r"YAT\b", "GEMI"],
    "90": ["MEDIKAL", "SAGLIK", "OPTIK", "LABORATUVAR"], "91": ["SAAT", "MUCEVHER"], "92": ["MUZIK"], "93": ["SAVUNMA", "AVCILIK"],
    "94": ["MOBILYA", "FURNITURE", "DEKORASYON"], "9405": ["AYDINLATMA", "LIGHT", "DEKORASYON", "MOBILYA"],
    "95": ["OYUNCAK", r"TOYS?\b", "SPOR"], "96": ["KIRTASIYE", "HEDIYELIK", "PROMOSYON"], "97": ["SANAT", "ANTIKA"],
}


def _keywords(hs6):
    """Ürün koduna uyan en uzun ön ekin kelimeleri."""
    return next((_KEYWORDS[hs6[:size]] for size in (4, 2) if hs6[:size] in _KEYWORDS), [])


def _fold(text):
    return text.replace("i", "İ").upper().translate(_FOLD)


@functools.cache
def _load(name):
    file = DATA / f"{name}.json"
    return json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}


def distance_km(iso2, home="TR"):
    """Türkiye'nin merkezinden ülkenin merkezine kuş uçuşu uzaklık; konum bilinmiyorsa None."""
    points = _load("konumlar")
    if iso2 not in points or home not in points:
        return None
    (lon1, lat1), (lon2, lat2) = (map(math.radians, points[code]) for code in (home, iso2))
    half = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(half))


@functools.cache
def _restrictions():
    by_country = {}
    for entry in _load("kisitlamalar") or []:
        by_country.setdefault(entry["ulke"], []).append(entry)
    return by_country


def restrictions(iso2, hs6):
    """Ülkenin DTÖ'ye bildirdiği, bu ürün kodunu kapsayan ithalat yasak ve kısıtlamaları.

    [{"tur", "metin", "metin_tr", "baslangic", "belge", "genis"}]; metin ülkenin bildirimindeki özgün ifadedir
    (İngilizce, Fransızca ya da İspanyolca), metin_tr elle yapılmış Türkçe çevirisidir. "genis", önlemin
    çok sayıda ürün kodunu kapsadığını, yani ürüne özgü olmayabileceğini gösterir.
    """
    found = [{**{key: entry.get(key) for key in ("tur", "metin", "metin_tr", "baslangic", "belge")}, "genis": len(entry["kodlar"]) > WIDE_SCOPE}
             for entry in _restrictions().get(iso2, []) if any(hs6.startswith(code) for code in entry["kodlar"])]
    return sorted(found, key=lambda item: item["genis"])      # ürüne özgü olanlar başta


def offices(iso2):
    """Ülkedeki Ticaret Müşavirlikleri ve Ataşelikleri: [{"sehir", "eposta"}]."""
    return _load("musavirlikler").get(iso2, [])


def fairs(iso2, hs6, limit=6):
    """Ülkede destek kapsamındaki, ürünle ilgili olabilecek fuarlar; ürüne en yakın konudakiler başta."""
    keywords = _keywords(hs6)

    def specificity(fair):
        # Kelimeler özelden genele sıralıdır: "HALI" eşleşmesi "TEKSTIL" eşleşmesinden önce gelir.
        text = _fold(fair["konu"] + " " + fair["ad"])
        return next((index for index, word in enumerate(keywords) if re.search(rf"(?<![A-Z]){word}", text)), None)

    today = datetime.date.today().isoformat()
    related = []
    for fair in _load("fuarlar").get(iso2, []):
        rank = specificity(fair)
        # Ertelenen fuarların tarihi yoktur; listeye alınmaz.
        if rank is not None and _DATE.fullmatch(fair["baslangic"]):
            past = fair["bitis"] < today
            # Önce konusu ürüne en yakın olanlar; eşit yakınlıkta yaklaşanlar geçmiştekilerden önce.
            related.append((rank, past, fair["baslangic"] if not past else "~" + fair["baslangic"], fair))
    related.sort(key=lambda item: item[:3])
    return [item[3] for item in related[:limit]]
