"""Pazara giriş verisi: Ticaret Müşavirlikleri ve destek kapsamındaki yurt dışı fuarlar.

Veri tools/pazara_giris.py ile Ticaret Bakanlığı'nın resmi listelerinden üretilir.
"""

import datetime
import functools
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
_FOLD = str.maketrans("ÇĞİIÖŞÜÂÎÛ", "CGIIOSUAIU")

# Ürün fasılı (kodun ilk iki hanesi) -> fuar konusunda aranacak kelimeler.
# Fuar listesinde konu serbest metindir; eşleşme bu yüzden "ilgili olabilir" düzeyindedir.
_SECTORS = [
    (range(1, 6), ["GIDA", "HAYVANCILIK", "TARIM", "SU URUNLERI", "HELAL"]),
    (range(6, 7), ["CICEK", "BAHCE", "PEYZAJ", "TARIM"]),
    (range(7, 9), ["GIDA", "TARIM", "MEYVE", "SEBZE"]),
    (range(9, 25), ["GIDA", "ICECEK", "TARIM", "HELAL", "UNLU MAMUL", "SEKERLEME"]),
    (range(25, 28), ["MADEN", "DOGAL TAS", "MERMER", "ENERJI", "INSAAT", "YAPI"]),
    (range(28, 30), ["KIMYA"]),
    (range(30, 31), ["ILAC", "ECZA", "SAGLIK", "MEDIKAL"]),
    (range(31, 32), ["GUBRE", "TARIM", "KIMYA"]),
    (range(32, 33), ["BOYA", "KIMYA", "KAPLAMA"]),
    (range(33, 35), ["KOZMETIK", "GUZELLIK", "KISISEL BAKIM", "TEMIZLIK", "KIMYA"]),
    (range(35, 39), ["KIMYA"]),
    (range(39, 41), ["PLASTIK", "KAUCUK", "AMBALAJ"]),
    (range(41, 44), ["DERI", "SARACIYE", "AYAKKABI"]),
    (range(44, 47), ["AHSAP", "ORMAN", "MOBILYA", "INSAAT", "YAPI"]),
    (range(47, 50), ["KAGIT", "AMBALAJ", "BASKI", "MATBAA", "KIRTASIYE"]),
    (range(50, 57), ["TEKSTIL", "IPLIK", "KUMAS"]),
    (range(57, 58), ["HALI", "EV TEKSTIL", "ZEMIN", "TEKSTIL"]),
    (range(58, 61), ["TEKSTIL", "IPLIK", "KUMAS"]),
    (range(61, 63), ["KONFEKSIYON", "HAZIR GIYIM", "TEKSTIL", "MODA"]),
    (range(63, 64), ["EV TEKSTIL", "TEKSTIL"]),
    (range(64, 68), ["AYAKKABI", "SARACIYE", "DERI"]),
    (range(68, 71), ["DOGAL TAS", "MERMER", "SERAMIK", "CAM", "INSAAT", "YAPI"]),
    (range(71, 72), ["MUCEVHER", "KUYUM", "DEGERLI MADEN", "SAAT"]),
    (range(72, 84), ["METAL", "DEMIR", "CELIK", "HIRDAVAT", "INSAAT", "YAPI", "DOKUM"]),
    (range(84, 85), ["MAKINE", "ENDUSTRI", "OTOMASYON", "IKLIMLENDIRME"]),
    (range(85, 86), ["ELEKTRIK", "ELEKTRONIK", "ENERJI", "BEYAZ ESYA", "AYDINLATMA"]),
    (range(86, 90), ["OTOMOTIV", "TASIT", "DENIZCILIK", "HAVACILIK", "SAVUNMA", "ULASIM"]),
    (range(90, 93), ["MEDIKAL", "SAGLIK", "OPTIK", "LABORATUVAR", "MUZIK"]),
    (range(93, 94), ["SAVUNMA", "AVCILIK"]),
    (range(94, 95), ["MOBILYA", "DEKORASYON", "AYDINLATMA"]),
    (range(95, 96), ["OYUNCAK", "SPOR", "HEDIYELIK"]),
    (range(96, 97), ["KIRTASIYE", "HEDIYELIK", "PROMOSYON"]),
    (range(97, 98), ["SANAT", "ANTIKA"]),
]


def _fold(text):
    return text.replace("i", "İ").upper().translate(_FOLD)


@functools.cache
def _load(name):
    file = DATA / f"{name}.json"
    return json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}


def offices(iso2):
    """Ülkedeki Ticaret Müşavirlikleri ve Ataşelikleri: [{"sehir", "eposta"}]."""
    return _load("musavirlikler").get(iso2, [])


def fairs(iso2, hs6, limit=6):
    """Ülkede destek kapsamındaki, ürünün sektörüyle ilgili olabilecek fuarlar."""
    chapter = int(hs6[:2])
    keywords = next((words for chapters, words in _SECTORS if chapter in chapters), [])
    def specificity(fair):
        # Kelimeler özelden genele sıralıdır: "HALI" eşleşmesi "TEKSTIL" eşleşmesinden önce gelir.
        subject = _fold(fair["konu"])
        return next((index for index, word in enumerate(keywords) if word in subject), None)

    today = datetime.date.today().isoformat()
    related = [(fair["bitis"] < today, specificity(fair), fair) for fair in _load("fuarlar").get(iso2, [])]
    related = [item for item in related if item[1] is not None]
    # Önce yaklaşanlar, sonra geçmiştekiler; her grupta konusu ürüne en yakın olan başta.
    related.sort(key=lambda item: (item[0], item[1], item[2]["baslangic"] if not item[0] else "~" + item[2]["baslangic"]))
    return [fair for _, _, fair in related[:limit]]
