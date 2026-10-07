"""UN Comtrade istemcisi: anahtarsız önizleme uç noktası, disk önbelleği, hız limiti için bekleme."""

import functools
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PREVIEW_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
KEYED_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
REFERENCE_URL = "https://comtradeapi.un.org/files/v1/app/reference/{name}.json"

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
PREVIEW_ROW_LIMIT = 500
TURKIYE = 792
WORLD = 0

_last_call = 0.0


def _fetch_json(url, headers=None, pause=1.5, retries=5):
    """Önbellekte varsa oradan okur; yoksa çeker, başarısız olursa artan aralıklarla yeniden dener."""
    global _last_call
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    wait = 5
    for attempt in range(retries):
        time.sleep(max(0.0, pause - (time.time() - _last_call)))
        _last_call = time.time()
        try:
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            payload = None
        # Hız limitine takılınca API "data" alanı olmayan bir gövde döndürüyor.
        if payload is not None and ("data" in payload or "results" in payload):
            cache_file.write_text(json.dumps(payload))
            return payload
        if attempt < retries - 1:
            time.sleep(wait)
            wait *= 2
    raise RuntimeError(f"Comtrade yanıt vermedi: {url}")


def api_key():
    """Anahtarı ortam değişkeninden, yoksa proje kökündeki .env dosyasından okur."""
    key = os.environ.get("COMTRADE_KEY")
    env_file = CACHE_DIR.parent / ".env"
    if not key and env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "COMTRADE_KEY":
                key = value.strip().strip("\"'")
    return key or None


def _query(**params):
    key = api_key()
    base = KEYED_URL if key else PREVIEW_URL
    headers = {"Ocp-Apim-Subscription-Key": key} if key else None
    params = {"flowCode": "M", "partner2Code": 0, "customsCode": "C00", "motCode": 0, **params}
    rows = _fetch_json(base + "?" + urllib.parse.urlencode(params), headers)["data"]
    if not key and len(rows) >= PREVIEW_ROW_LIMIT:
        raise RuntimeError("Anahtarsız erişimin 500 kayıt sınırına takıldı, sonuç eksik olabilir.")
    return rows


def countries():
    """Kod -> (ülke adı, ISO2). Ülke grupları (AB, ASEAN vb.) hariç."""
    names = {}
    for ref, prefix in (("Reporters", "reporter"), ("partnerAreas", "Partner")):
        for row in _fetch_json(REFERENCE_URL.format(name=ref))["results"]:
            if not row.get("isGroup"):
                names.setdefault(row[prefix + "Code"], (row[prefix + "Desc"], row.get(prefix + "CodeIsoAlpha2")))
    return names


def product_codes():
    """Comtrade'in tanıdığı 6 haneli ürün kodları."""
    return {row["id"] for row in _fetch_json(REFERENCE_URL.format(name="HS"))["results"] if len(row["id"]) == 6}


def product_name(hs6):
    """Ürün kodunun Comtrade'deki (İngilizce) tanımı; kod bilinmiyorsa None."""
    for row in _fetch_json(REFERENCE_URL.format(name="HS"))["results"]:
        if row["id"] == hs6:
            return row["text"].partition(" - ")[2]
    return None


@functools.cache
def _matrix(hs6, year):
    """Anahtarlı erişimde tek sorguyla tüm ülkeler ve tedarikçiler: {ülke: {tedarikçi: (USD, net kg)}}."""
    matrix = {}
    for row in _query(cmdCode=hs6, period=year):
        value = row.get("primaryValue") or 0
        partners = matrix.setdefault(row["reporterCode"], {})
        if value > partners.get(row["partnerCode"], (0, 0))[0]:
            partners[row["partnerCode"]] = (value, row.get("netWgt") or 0)
    return matrix


def imports_by_reporter(hs6, year):
    """Bir yılda her ülkenin dünyadan toplam ithalatı: {ülke kodu: (USD, net kg)}."""
    if api_key():
        return {code: partners[WORLD] for code, partners in _matrix(hs6, year).items() if WORLD in partners}
    totals = {}
    for row in _query(cmdCode=hs6, period=year, partnerCode=WORLD):
        value = row.get("primaryValue") or 0
        if value > totals.get(row["reporterCode"], (0, 0))[0]:
            totals[row["reporterCode"]] = (value, row.get("netWgt") or 0)
    return totals


def imports_by_partner(hs6, year, reporter):
    """Bir ülkenin ithalatının tedarikçi ülkelere dağılımı: {tedarikçi kodu: (USD, net kg)}."""
    if api_key():
        rows = _matrix(hs6, year).get(reporter, {}).items()
    else:
        rows = ((row["partnerCode"], (row.get("primaryValue") or 0, row.get("netWgt") or 0))
                for row in _query(cmdCode=hs6, period=year, reporterCode=reporter))
    return {code: pair for code, pair in rows if code != WORLD and pair[0] > 0}


def exports_by_product(reporter, year):
    """Bir ülkenin dünyaya ihracatı, 6 haneli ürün koduna göre: {kod: USD}. Anahtar gerektirir."""
    rows = _query(reporterCode=reporter, period=year, cmdCode="AG6", flowCode="X", partnerCode=WORLD)
    return {row["cmdCode"]: row.get("primaryValue") or 0 for row in rows}


def exports_by_reporter(hs6, year):
    """Bir yılda her ülkenin dünyaya toplam ihracatı: {ülke kodu: USD}."""
    totals = {}
    for row in _query(cmdCode=hs6, period=year, flowCode="X", partnerCode=WORLD):
        totals[row["reporterCode"]] = max(totals.get(row["reporterCode"], 0), row.get("primaryValue") or 0)
    return totals
