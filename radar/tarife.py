"""Gümrük vergisi: Dünya Ticaret Örgütü'nün (DTÖ) Timeseries API'sinden ürün bazında oranlar.

Her ülke için iki oran alınır:
  mfn : herkese uygulanan oran (en çok kayrılan ülke, MFN), 6 haneli koddaki tarife satırlarının ortalaması
  tr  : Türkiye'ye uygulanan tercihli oran (anlaşma varsa ve DTÖ'ye bildirilmişse)
Yalnızca yüzde olarak ifade edilen (ad valorem) vergiler kapsanır; kilo başına vergiler ve ek vergiler,
damping önlemleri, kotalar bu veride yoktur. Anahtar .env dosyasındaki WTO_KEY değişkeninden okunur.
"""

import functools
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import comtrade, sartlar

DATA_URL = "https://api.wto.org/timeseries/v1/data"
REPORTERS_URL = "https://api.wto.org/timeseries/v1/reporters?lang=1"
MFN, PREFERENTIAL = "HS_A_0010", "HS_P_0070"
YEARS = "2019-2025"                        # her ülkenin bu aralıktaki en son bildirimi kullanılır
FRESH_DAYS = 90                            # vergi oranları yılda bir iki kez güncellenir
TURKIYE = "792"
EU = "EEC"                                 # DTÖ, AB'yi tek ekonomi olarak raporlar


def _key():
    key = os.environ.get("WTO_KEY")
    env_file = comtrade.CACHE_DIR.parent / ".env"
    if not key and env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "WTO_KEY":
                key = value.strip().strip("\"'")
    return key or None


def _get(url):
    request = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": _key()})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    # Veri yoksa API boş gövdeyle 204 döner. Metinler Latin-1 kodludur.
    return json.loads(body.decode("latin-1")) if body.strip() else {}


@functools.cache
def _iso2_by_wto_code():
    """DTÖ ekonomi kodu -> ISO2 (ISO3 üzerinden; AB "EU" olarak döner)."""
    iso2 = {}
    for ref, prefix in (("Reporters", "reporter"), ("partnerAreas", "Partner")):
        for row in comtrade._fetch_json(comtrade.REFERENCE_URL.format(name=ref))["results"]:
            if row.get(prefix + "CodeIsoAlpha3") and row.get(prefix + "CodeIsoAlpha2"):
                iso2.setdefault(row[prefix + "CodeIsoAlpha3"], row[prefix + "CodeIsoAlpha2"])
    iso2[EU] = "EU"
    return {row["code"]: iso2[row["iso3A"]] for row in _get(REPORTERS_URL) if row.get("iso3A") in iso2}


def _latest(indicator, hs6, **extra):
    """Her ekonominin değeri dolu olan en son yılı: {ISO2: (oran, yıl, açıklama)}."""
    query = urllib.parse.urlencode({"i": indicator, "r": "all", "pc": hs6, "ps": YEARS, "fmt": "json", "mode": "full",
                                    "lang": 1, "meta": "false", "max": 100000, **extra})
    latest = {}
    for row in _get(DATA_URL + "?" + query).get("Dataset", []):
        iso2 = _iso2_by_wto_code().get(row["ReportingEconomyCode"])
        if iso2 and row["Value"] is not None and row["Year"] > latest.get(iso2, (0, 0))[1]:
            latest[iso2] = (row["Value"], row["Year"], row.get("TextValue"))
    return latest


def rates(hs6):
    """{ISO2: {"mfn", "tr", "yil", "tur"}}; oranlar yüzde. Anahtar yoksa ya da DTÖ yanıt vermezse None.

    "tur", tercihli oranın dayanağıdır: "anlasma" (ikili ticaret anlaşması) ya da "gsp" (gelişmekte olan
    ülkelere tek taraflı indirim). AB'nin oranı üye ülkelerin her birine yazılır. Sonuç önbelleğe alınır.
    """
    cache_file = comtrade.CACHE_DIR / f"tarife-{hs6}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < FRESH_DAYS * 86400:
        return json.loads(cache_file.read_text())
    stale = json.loads(cache_file.read_text()) if cache_file.exists() else None
    if not _key():
        return stale
    try:
        mfn, preferential = _latest(MFN, hs6), _latest(PREFERENTIAL, hs6, p=TURKIYE)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        return stale                          # yenilenemedi: eski oranlar hiç yoktan iyidir
    result = {}
    for iso2, (value, year, _) in mfn.items():
        special = preferential.get(iso2)
        kind = None
        if special:
            kind = "gsp" if "GSP" in (special[2] or "") else "anlasma"
            # Anlaşmalar kalıcıdır, eski yılın bildirimi de geçerli sayılır. Tek taraflı indirimler geri
            # alınabildiği için (ABD 2019'da Türkiye'yi kapsamdan çıkardı) yalnızca güncel bildirim kabul edilir.
            if kind == "gsp" and special[1] < year - 1:
                special = kind = None
        # Tercihli oran MFN'den yüksek olamaz; eski yıldan kalmış bir bildirim öyle görünürse MFN geçerlidir.
        result[iso2] = {"mfn": value, "yil": year, "tr": min(special[0], value) if special else None, "tur": kind}
    if "EU" in result:
        result.update({member: result["EU"] for member in sartlar.AB})
    comtrade.CACHE_DIR.mkdir(exist_ok=True)
    cache_file.write_text(json.dumps(result))
    return result


def applied(rate):
    """Türkiye menşeli ürüne uygulanan oran: tercihli oran varsa o, yoksa herkese uygulanan."""
    return rate["mfn"] if rate["tr"] is None else rate["tr"]
