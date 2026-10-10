"""Türkçe ürün adı araması. Sözlük tools/gtip_sozluk.py ile resmi tarife cetvelinden üretilir."""

import functools
import json
import math
import re
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "urunler.json"
_FOLD = str.maketrans("ışğüöçâîû", "isguocaiu")
# Tanımlarda çok geçen, ürün belirtmeyen kelimeler ("halı" araması "halinde" ile eşleşmesin).
_STOP = {"halinde", "halindeki", "hali", "olan", "olanlar", "diğer", "diğerleri", "veya", "ve", "ile", "için"}
# Kısa kelimeler yalnızca bu eklerle eşleşir: "bal" -> "balı" olur, "balık" olmaz.
_SHORT_SUFFIXES = {"", "i", "u", "lar", "ler", "lari", "leri", "li", "lu", "dan", "den", "tan", "ten",
                   "nin", "nun", "in", "un", "si", "su", "yi", "yu"}

# Günlük dildeki adlar -> tarife cetvelinin kullandığı ifade. Arama her iki haliyle de yapılır.
ALIASES = {
    "kombi": "merkezi ısıtma kazanları",
    "araba": "binek otomobilleri",
    "cep telefonu": "akıllı telefonlar",
    "telefon": "akıllı telefonlar",
    "laptop": "portatif otomatik bilgi işlem makinaları",
    "dizüstü bilgisayar": "portatif otomatik bilgi işlem makinaları",
    "bilgisayar": "otomatik bilgi işlem makinaları",
    "makine": "makina",
    "makinesi": "makinaları",
    "makineleri": "makinaları",
    "kot": "denim",
    "jean": "denim",
    "fayans": "seramik karolar",
    "deterjan": "yıkama müstahzarları",
    "kozmetik": "makyaj müstahzarları",
    "takı": "mücevherci eşyası",
    "mücevher": "mücevherci eşyası",
    "akü": "elektrik akümülatörleri",
    "jeneratör": "elektrojen grupları",
    "kumaş": "mensucat",
    "narenciye": "turunçgiller",
    "inşaat demiri": "demir çelik çubuklar",
    "salça": "domatesler",
    "ampul": "elektrik ampulleri",
    "oto yedek parça": "motorlu taşıtların aksam",
    "yedek parça": "motorlu taşıtların aksam",
}

# Yaygın ürünlerin günlük adları -> doğrudan kod. Bu kodlar sonuçların en üstüne sabitlenir.
PINS = {
    "zeytin": ["200570", "071120", "070992"],
    "şeker": ["170199", "170114"],
    "koltuk": ["940161", "940171"],
    "kahve": ["090121", "090111"],
    "cam": ["700529", "700510"],
    "kağıt": ["480256", "481019"],
    "gömlek": ["620520", "620530", "620630", "610510"],
    "ayakkabı": ["640399", "640419", "640299", "640391"],
    "televizyon": ["852872"],
    "lastik": ["401110", "401120"],
    "inşaat demiri": ["721420", "721310"],
    "ampul": ["853952", "853922"],
    "havlu": ["630260"],
    "deterjan": ["340250", "340290"],
    "jeneratör": ["850213", "850212", "850211"],
    "süt": ["040120", "040210", "040221"],
    "kot pantolon": ["620342", "620462"],
    "kot": ["620342", "620462"],
    "jean": ["620342", "620462"],
    "salça": ["200290"],
    "bulgur": ["190430"],
    "kuru üzüm": ["080620"],
    "kuru kayısı": ["081310"],
    "kuru incir": ["080420"],
    "çamaşır makinesi": ["845011"],
    "bulaşık makinesi": ["842211"],
    "buzdolabı": ["841810", "841821"],
    "fırın": ["851660"],
    "klima": ["841510"],
    "cep telefonu": ["851713"],
    "telefon": ["851713"],
    "laptop": ["847130"],
    "dizüstü bilgisayar": ["847130"],
    "kombi": ["840310"],
    "akü": ["850710"],
    "oto yedek parça": ["870899", "870829"],
    "yedek parça": ["870899", "870829"],
    "takı": ["711319"],
    "mücevher": ["711319"],
    "tavuk eti": ["020714", "020712"],
    "tavuk": ["020714", "020712"],
    "yumurta": ["040721"],
    "limon": ["080550"],
    "portakal": ["080510"],
    "mandalina": ["080521"],
    "kiraz": ["080929"],
    "üzüm": ["080610", "080620"],
    "elma": ["080810"],
    "biber": ["070960"],
    "salatalık": ["070700"],
    "bisküvi": ["190531"],
    "çikolata": ["180690"],
    "antep fıstığı": ["080252", "080251"],
    "halı": ["570242"],
    "çimento": ["252329"],
    "ceviz": ["080232", "080231"],
    "gübre": ["310520", "310210"],
    "et": ["020230", "020130"],
    "kırmızı et": ["020230", "020130"],
    "balık": ["030284", "030285"],
    "levrek": ["030284"],
    "çipura": ["030285"],
    "kumaş": ["520942", "540752", "600622"],
    "boya": ["320890", "320910"],
}


def _fold(text):
    return " ".join(word for _, word in _words(text, keep_stop=True))


def _words(text, keep_stop=False):
    """Metni (Türkçe küçük harf, ASCII'ye indirgenmiş) kelime çiftlerine ayırır."""
    lowered = text.replace("İ", "i").replace("I", "ı").lower()
    pairs = [(word, word.translate(_FOLD)) for word in re.findall(r"[a-zışğüöçâîû0-9]+", lowered)]
    return [pair for pair in pairs if keep_stop or pair[0] not in _STOP]


def _one_edit(a, b):
    """İki kelime en fazla bir harf farkıyla (ekleme, silme, değişme) aynı mı?"""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    for i in range(len(a)):
        if a[i] != b[i]:
            return a[i + 1:] == b[i + 1:] if len(a) == len(b) else a[i:] == b[i + 1:]
    return True


def _match(word, token, fuzzy=False):
    """2: yazıldığı gibi kelime başı, 1: Türkçe karaktersiz, ek farkıyla ya da (fuzzy) tek harf hatasıyla, 0: yok."""
    raw, folded = token
    if len(folded) <= 3:
        if word[1].startswith(folded) and word[1][len(folded):] in _SHORT_SUFFIXES:
            return 2 if word[0].startswith(raw) else 1
        return 0
    if word[0].startswith(raw):
        return 2
    if word[1].startswith(folded):
        return 1
    if len(folded) < 5:
        return 0
    # Ünsüz yumuşaması gibi ek farkları: buzdolabı ~ buzdolapları.
    need = max(4, len(folded) - 2)
    if word[1][:need] == folded[:need]:
        return 1
    if fuzzy and any(_one_edit(word[1][:size], folded) for size in (len(folded) - 1, len(folded), len(folded) + 1)):
        return 1
    return 0


@functools.cache
def _index():
    products = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {}
    return {hs6: {"path": entry["path"],
                  # Türkiye'nin ihracatı büyük olan ürün, benzer güçte eşleşenler arasında öne geçer.
                  # Çarpan olduğu için zayıf (yalnızca alt kırılımda geçen) eşleşmeyi öne taşımaz.
                  "prior": 1 + 0.25 * math.log10(1 + entry.get("export", 0) / 1e6),
                  "path_words": [_words(part) for part in entry["path"]],
                  "child_words": [word for child in entry["children"] for word in _words(child)]}
            for hs6, entry in products.items()}


def path(hs6):
    """Ürünün Türkçe tanım yolu (pozisyon başlığından 6 haneye); bilinmiyorsa None."""
    entry = _index().get(hs6)
    return entry["path"] if entry else None


def _variants(query):
    """Sorgunun kendisi ve günlük adların tarife karşılıklarıyla yazılmış halleri."""
    folded = _fold(query)
    variants = [query]
    for alias, official in sorted(ALIASES.items(), key=lambda item: -len(item[0])):
        key = _fold(alias)
        replaced = re.sub(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", official, folded)
        if replaced != folded:
            variants.append(replaced)
    return variants


def _score(tokens, fuzzy):
    """{kod: (puan, tanım uzunluğu)}: her kelimesi bir yerde eşleşen ürünler."""
    scores = {}
    for hs6, entry in _index().items():
        total = 0
        last = len(entry["path_words"]) - 1
        for token in tokens:
            found = 0
            for depth, part in enumerate(entry["path_words"]):
                # Kelime başlığın ya da ürünün kendi tanımının başındaysa güçlü, ortalardaysa zayıf işarettir.
                strong = (6 if depth == 0 else 0) + (4 if depth == last else 0) or 3
                best = 0
                for position, word in enumerate(part):
                    quality = _match(word, token, fuzzy)
                    if quality:
                        best = max(best, (strong if position < 2 else 1) * quality / 2)
                found += best
            if not found and any(_match(word, token, fuzzy) for word in entry["child_words"]):
                found = 0.5
            if not found:
                break
            total += found
        else:
            scores[hs6] = (total * entry["prior"], sum(len(part) for part in entry["path_words"]))
    return scores


def search(query, limit=8):
    """Ürün adına göre arama; rakam yazılırsa kod önekine göre. Sonuç yoksa tek harf hatasına izin verir."""
    digits = re.sub(r"[\s.]", "", query)
    if digits.isdigit():
        codes = sorted(hs6 for hs6 in _index() if hs6.startswith(digits[:6]))[:limit]
        return [{"hs6": hs6, "path": _index()[hs6]["path"]} for hs6 in codes]

    folded = _fold(query)
    pinned = next((codes for name, codes in sorted(PINS.items(), key=lambda item: -len(item[0]))
                   if re.search(rf"(?<![a-z0-9]){re.escape(_fold(name))}(?![a-z0-9])", folded)), [])
    pinned = [hs6 for hs6 in pinned if hs6 in _index()]

    for fuzzy in (False, True):
        merged = {}
        for variant in _variants(query):
            tokens = _words(variant, keep_stop=True)
            for hs6, (total, length) in (_score(tokens, fuzzy) if tokens else {}).items():
                if hs6 not in merged or total > merged[hs6][0]:
                    merged[hs6] = (total, length)
        if merged or pinned:
            ranked = sorted(merged, key=lambda hs6: (-merged[hs6][0], merged[hs6][1], hs6))
            ranked = (pinned + [hs6 for hs6 in ranked if hs6 not in pinned])[:limit]
            return [{"hs6": hs6, "path": _index()[hs6]["path"]} for hs6 in ranked]
    return []
