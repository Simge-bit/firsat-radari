"""Döviz kurları: anlık serbest piyasa kuru, yoksa TCMB'nin günlük resmi kuru.

Piyasa kuru resmi bir kaynak değildir (finans.truncgil.com; piyasa verisini derleyen ücretsiz bir servis) ve birkaç
dakikada bir güncellenir. Servis yanıt vermezse ya da bir kur TCMB kurundan çok saparsa o kur için TCMB değeri kullanılır.
TCMB kurları iş günlerinde günde bir kez yayımlanır.
"""

import datetime
import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

TODAY_URL = "https://www.tcmb.gov.tr/kurlar/today.xml"
ARCHIVE_URL = "https://www.tcmb.gov.tr/kurlar/{yearmonth}/{day}.xml"
CODES = ["USD", "EUR", "GBP", "CHF", "CNY", "RUB", "SAR", "AED", "CAD", "JPY"]
MARKET_URL = "https://finans.truncgil.com/v4/today.json"
CACHE_SECONDS = 30 * 60
MARKET_SECONDS = 120
MAX_DEVIATION = 0.10                       # piyasa kuru TCMB kurundan bundan fazla saparsa hatalı sayılır

_cache = {"at": 0.0, "data": None}
_market = {"at": 0.0, "data": None}


def _bulletin(url):
    """Bir bültenin tarihi ve döviz alış kurları: (tarih, {kod: 1 birimin TL karşılığı})."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    root = ET.fromstring(urllib.request.urlopen(request, timeout=20).read())
    rates = {}
    for currency in root.iter("Currency"):
        buying, unit = currency.findtext("ForexBuying"), currency.findtext("Unit")
        if buying:
            rates[currency.get("Kod")] = float(buying) / float(unit or 1)
    return datetime.datetime.strptime(root.get("Tarih"), "%d.%m.%Y").date(), rates


def _previous(date):
    """Verilen tarihten önceki son bülten (hafta sonu ve tatiller atlanır)."""
    for back in range(1, 10):
        day = date - datetime.timedelta(days=back)
        try:
            return _bulletin(ARCHIVE_URL.format(yearmonth=day.strftime("%Y%m"), day=day.strftime("%d%m%Y")))[1]
        except urllib.error.HTTPError:
            continue
    return {}


def _official():
    """{"tarih": "2026-10-07", "kurlar": [{"kod", "alis", "degisim"}]}; degisim bir önceki bültene göre orandır."""
    if _cache["data"] and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]
    date, current = _bulletin(TODAY_URL)
    before = _previous(date)
    data = {"tarih": date.isoformat(), "kurlar": [
        {"kod": code, "alis": current[code], "degisim": current[code] / before[code] - 1 if before.get(code) else None}
        for code in CODES if code in current]}
    _cache.update(at=time.time(), data=data)
    return data


def rates():
    """Şeritte gösterilecek kurlar: {"kaynak": "piyasa" | "tcmb", "tarih", "saat", "kurlar": [{"kod", "alis", "degisim"}]}.

    Piyasa kuru alınabildiyse o (degisim: gün içi değişim oranı), alınamadıysa TCMB bülteni döner.
    """
    official = _official()
    if _market["data"] and time.time() - _market["at"] < MARKET_SECONDS:
        return _market["data"]
    try:
        request = urllib.request.Request(MARKET_URL, headers={"User-Agent": "Mozilla/5.0"})
        feed = json.loads(urllib.request.urlopen(request, timeout=8).read().decode("utf-8"))
        updated = datetime.datetime.strptime(feed["Update_Date"], "%Y-%m-%d %H:%M:%S")
        quotes = []
        for reference in official["kurlar"]:
            quote = feed.get(reference["kod"]) or {}
            price = quote.get("Buying")
            if isinstance(price, (int, float)) and abs(price / reference["alis"] - 1) <= MAX_DEVIATION:
                quotes.append({"kod": reference["kod"], "alis": float(price), "degisim": (quote.get("Change") or 0) / 100})
            else:
                quotes.append(reference)          # servis bu kuru vermedi ya da değer tutarsız: resmi kur
        data = {"kaynak": "piyasa", "tarih": updated.date().isoformat(), "saat": updated.strftime("%H:%M"), "kurlar": quotes}
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError):
        data = {"kaynak": "tcmb", "saat": None, **official}
    _market.update(at=time.time(), data=data)
    return data
