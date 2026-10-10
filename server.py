"""Yerel prototip sunucusu. Kullanım: python3 server.py  ->  http://localhost:8765"""

import base64
import datetime
import functools
import hashlib
import hmac
import json
import os
import secrets
import re
import threading
import time
import traceback
import urllib.parse
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import odeme
import rapor
import uyelik
from radar import comtrade, doviz, urunler

BRAND = "İhraçbul"

PORT = 8765
WEB = Path(__file__).resolve().parent / "web"
READY = Path(__file__).resolve().parent / "data" / "hazir"
ROBOTS = "User-agent: *\nDisallow: /api/\n"      # tarayıcı robotlar veri kotasını tüketmesin
PAGES = ["/", "/paketler", "/ekip", "/kayit", "/gizlilik", "/kosullar", "/mesafeli-satis", "/iade"]
OPEN_SAMPLES = {"080222"}                  # tam raporu herkese açık örnek ürünler (web/app.js içindeki SAMPLES ile aynı olmalı)
PRICES = {"single": 490, "pro": 999, "yearly": 9000}       # TL; web/app.js içindeki PRICES ile aynı olmalı
# Gösterim modu: iyzico anahtarları girilene kadar ödeme para almadan onaylanır.
DEMO = not odeme.configured()
# iyzico bağlanana kadar ücretli paketler "yakında" olarak görünür ve satılmaz. Yerelde ödeme akışını para almadan
# denemek için IHRACBUL_DEMO=1 verilir; o zaman ödeme onaylanmış sayılır ve paket açılır.
FREE_GRANTS = DEMO and bool(os.environ.get("IHRACBUL_DEMO"))
SOON = DEMO and not FREE_GRANTS
LOGIN_PER_HOUR = {"eposta": 5, "ip": 30, "sifre": 10, "kayit": 10, "yonetim": 8}
ADMIN_HOURS = 12                            # yönetim oturumu bu kadar saat sonra kapanır
PASSWORD_MIN = 8     # bir e-postaya ve bir internet adresinden saatte en çok bu kadar giriş bağlantısı
_login_tries = {}


def product_title(hs6):
    """Ürünün kısa Türkçe adı (web/app.js içindeki productLabels ile aynı kural); bilinmiyorsa None."""
    path = urunler.path(hs6)
    if not path:
        return None
    heading, rest = path[0].split(" (")[0], " › ".join(path[1:])
    if len(path) == 1:
        return path[0].split(" (")[0]
    if len(path) == 2:
        return heading + " › " + path[1]
    return heading if any(part.startswith("Diğer") for part in path[1:]) else rest
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
                ".png": "image/png", ".jpg": "image/jpeg", ".ttf": "font/ttf", ".json": "application/json; charset=utf-8"}
_build_lock = threading.Lock()
# Stil ve betiklerin sürüm etiketi: dosyalar değişince etiket değişir, tarayıcı yenisini indirir; değişmedikçe önbellekten açar.
ASSETS = ("app.css", "app.js", "belge.js", "yonetim.js")
VERSION = hashlib.sha256(b"".join((WEB / name).read_bytes() for name in ASSETS)).hexdigest()[:10]


def versioned(html):
    for name in ASSETS:
        html = html.replace(f'/static/{name}"', f'/static/{name}?v={VERSION}"')
    return html


DAILY_NEW = {"free": 1, "pro": 10}          # ziyaretçi başına günde açılabilen, önbellekte olmayan ürün sayısı
DAILY_FREE = 1                              # ücretsiz planda günde açılabilen farklı ürün sayısı (hazır örnekler sayılmaz)
_seen = {}                                  # (gün, ziyaretçi) -> bugün açtığı ürün kodları
_opened = {}                                # (gün, ziyaretçi) -> bugün açtığı yeni ürün sayısı
READY_DAYS = 45                             # hazır rapor bu kadar günden eskiyse canlı veriyle yeniden kurulur


@functools.lru_cache(maxsize=200)
def _report(hs6, week):
    """Raporun JSON gövdesi. Depoyla gelen güncel bir hazır rapor varsa o, yoksa Comtrade'den kurulur."""
    ready = READY / f"{hs6}.json"
    if ready.is_file() and time.time() - ready.stat().st_mtime < READY_DAYS * 86400:
        return ready.read_bytes()
    # Aynı anda tek rapor kurulur: istekler üst üste binip çağrı kotasını boşa harcamasın.
    with _build_lock:
        return json.dumps(rapor.build(rapor.hs6_from(hs6))).encode("utf-8")


class LimitReached(Exception):
    pass


# ---------- Erişim: imzalı belirteç ----------
# Tam rapor yalnızca geçerli bir belirteçle verilir; kilitli veri tarayıcıya hiç gönderilmez. Belirteç sunucunun gizli
# anahtarıyla imzalanır, bu yüzden tarayıcıda değiştirilemez. Ödeme şimdilik gösterimdir: /api/demo-odeme belirteci
# para almadan verir. Gerçek ödeme bağlandığında yalnızca o uç noktanın yerini ödeme kuruluşunun onayı alacak.

def _secret():
    """İmza anahtarı: ortam değişkeninden, yoksa proje kökünde saklanan (depoya girmeyen) dosyadan; ilk açılışta üretilir."""
    if os.environ.get("IHRACBUL_SECRET"):
        return os.environ["IHRACBUL_SECRET"].encode()
    file = WEB.parent / ".gizli"
    if not file.exists():
        file.write_text(secrets.token_hex(32))
    return file.read_text().strip().encode()


def sign(grant):
    body = base64.urlsafe_b64encode(json.dumps(grant, separators=(",", ":")).encode()).decode().rstrip("=")
    mark = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return body + "." + mark


def read_token(token):
    """Belirteçteki haklar: {"pro": bool, "reports": [hs6...]}. İmza tutmuyorsa ya da süresi dolduysa haksız."""
    empty = {"email": "", "pro": False, "pro_until": 0, "reports": []}
    body, _, mark = (token or "").partition(".")
    if not body or not hmac.compare_digest(mark, hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()):
        return empty
    try:
        grant = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return empty
    pro = bool(grant.get("pro")) and grant.get("pro_until", 0) > time.time()
    return {"email": grant.get("email") or "", "pro": pro, "pro_until": grant.get("pro_until", 0) if pro else 0,
            "reports": [code for code in grant.get("reports", []) if re.fullmatch(r"\d{6}", str(code))]}


def session(email):
    """Üyenin güncel haklarını taşıyan imzalı belirteç ve tarayıcıya gösterilecek özet."""
    state = sync_subscription(email)
    grant = uyelik.grants(email)
    return {"token": sign(grant), **grant, **uyelik.profile(email), "abonelik": state}


SUBSCRIPTION = "abonelik"                  # sipariş kaydında aylık aboneliği tek seferlik ödemeden ayıran işaret
RENEW_WINDOW = 2 * 86400                   # Pro bitimine bu kadar kala iyzico'ya yenilendi mi diye sorulur
RECHECK = 3 * 3600                         # aynı üye için iki sorgu arasındaki en kısa süre
GRACE = 86400                              # tahsilat gecikirse erişim hemen kesilmesin
_forms = {}                                # belirteç -> (ödeme formu betiği, son geçerlilik); abonelik formu sayfaya gömülür


def sync_subscription(email):
    """Aboneliğin durumunu döner ("aktif" | "iptal" | "bitti" | ""); süresi dolmak üzereyse iyzico'ya sorup yeniler.

    iyzico her ay kartı kendisi çeker. Site, üye geldiğinde ödenmiş son dönemin bitişini öğrenir ve Pro süresini ona göre uzatır.
    """
    current = uyelik.subscription(email)
    now = time.time()
    if DEMO or current["durum"] != "aktif" or current["pro_bitis"] - now > RENEW_WINDOW or now - current["bakildi"] < RECHECK:
        return current["durum"]
    try:
        period = odeme.subscription_period(current["ref"])
    except odeme.PaymentError:
        traceback.print_exc()
        return current["durum"]                # iyzico'ya ulaşılamadı: eldeki süreyle devam, sonra yeniden denenir
    if period["bitis"]:
        uyelik.renew(email, period["bitis"] + GRACE, period["donem"], PRICES["pro"])
    if period["durum"] not in ("ACTIVE", "PENDING", "UPGRADED"):
        uyelik.set_subscription(email, current["ref"], "bitti")
        return "bitti"
    uyelik.set_subscription(email, current["ref"], "aktif")
    return "aktif"


def admin_token():
    return sign({"yonetici": True, "bitis": time.time() + ADMIN_HOURS * 3600})


def is_admin(token):
    """Belirteç geçerli bir yönetim oturumu mu? Panel, ADMIN_PASSWORD ortam değişkeni verilmemişse tümüyle kapalıdır."""
    body, _, mark = (token or "").partition(".")
    if not os.environ.get("ADMIN_PASSWORD") or not body or not hmac.compare_digest(mark, hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()):
        return False
    try:
        grant = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return False
    return grant.get("yonetici") is True and grant.get("bitis", 0) > time.time()


def admin_view():
    """Yönetim panelinin gösterdiği her şey: üyeler, satın almalar ve sitenin durumu."""
    return {**uyelik.overview(), "durum": {
        "odeme": "yakinda" if SOON else "deneme" if DEMO else "gercek", "kalici": uyelik.persistent(), "eposta": uyelik.mail_configured(),
        "veri_istegi": comtrade.calls_today(), "veri_siniri": comtrade.DAILY_BUDGET}}


def throttled(*keys):
    """Giriş bağlantısı isteği sınırı aşıldı mı? Aşılmadıysa isteği sayar."""
    now = time.time()
    for key in keys:
        recent = [moment for moment in _login_tries.get(key, []) if now - moment < 3600]
        if len(recent) >= LOGIN_PER_HOUR[key[0]]:
            return True
        _login_tries[key] = recent + [now]
    return False


LOCKED_ROW = ("code", "country", "iso2", "year", "imports", "G_raw", "tr_share", "score", "kappa", "series", "reexport", "blocked", "z")
SAMPLE_ROW = ("code", "country", "iso2", "imports", "G_raw", "score")


def locked(body):
    """Ücretsiz görünümün verisi: toplamlar ve yalnızca birinci pazarın özeti. Diğer pazarlar ve ülke detayı yer almaz."""
    full = json.loads(body)
    rows = full["rows"]
    first = {key: rows[0][key] for key in LOCKED_ROW}
    first.update(restrictions=[])
    # Toplamlar yalnızca aday pazarları sayar; Türkiye'nin ticareti durdurduğu ülkeler listede durur ama toplama girmez.
    open_rows = [row for row in rows if not row.get("blocked")]
    return json.dumps({**{key: value for key, value in full.items() if key != "rows"}, "kilitli": True, "pazar_sayisi": len(rows),
                       "ozet": {"toplam": sum(row["imports"] for row in open_rows), "turkiye": sum(row["imports"] * row["tr_share"] for row in open_rows),
                                "aday": len(open_rows)},
                       "rows": [first]}).encode("utf-8")


def sample(hs6):
    """Ana sayfadaki vitrin: yalnızca depoyla gelen örnek ürünlerin ilk yedi pazarı, ad ve skor düzeyinde."""
    ready = READY / f"{hs6}.json"
    if not re.fullmatch(r"\d{6}", hs6) or not ready.is_file():
        return None
    rows = json.loads(_report(hs6, datetime.date.today().isocalendar()[:2]))["rows"]
    found = {"hs6": hs6, "rows": [{key: row[key] for key in SAMPLE_ROW} for row in rows[:7]]}
    if hs6 in OPEN_SAMPLES:
        # Ana sayfadaki rapor kesiti: tam raporu zaten herkese açık olan örneğin birinci pazarından birkaç rakam.
        top, duty = rows[0], rows[0].get("tariff")
        found["kesit"] = {"pay": top["tr_share"], "vergi": None if not duty else duty["mfn"] if duty["tr"] is None else duty["tr"],
                          "rakipler": [{"country": rival["country"], "iso2": rival["iso2"], "share": rival["share"]} for rival in top["rivals"][:2]]}
    return found


def report(hs6, visitor, plan, owned=False):
    """Raporu verir. Ziyaretçi günlük yeni ürün sınırını doldurduysa yalnızca önbellekteki ürünleri görebilir.

    Veri kaynağının günlük çağrı sınırı tüm site için ortaktır; tek bir ziyaretçi onu tüketmesin diye sınır konur.
    Önceden açılmış (önbellekteki) ürünler sayılmaz.
    """
    # Bellekteki rapor haftada bir yenilenir; uzun süre açık kalan sunucu eski veriyi göstermeye devam etmesin.
    week, key = datetime.date.today().isocalendar()[:2], (datetime.date.today(), visitor)
    for stale in [old for old in list(_seen) + list(_opened) if old[0] != key[0]]:      # dünün sayaçları atılır
        _seen.pop(stale, None)
        _opened.pop(stale, None)
    # Ücretsiz planda günde bir ürün: aynı ürüne yeniden bakmak serbest, ikinci bir ürün ertesi güne kalır.
    # Hazır örnekler ve üyenin satın aldığı raporlar sayılmaz.
    counted = plan == "free" and not owned and not (READY / f"{hs6}.json").is_file()
    seen = _seen.setdefault(key, set())
    if counted and hs6 not in seen and len(seen) >= DAILY_FREE:
        raise LimitReached
    if _opened.get(key, 0) >= DAILY_NEW[plan] and not (counted and hs6 not in seen):
        try:
            with comtrade.offline():
                return _report(hs6, week)
        except comtrade.CacheMiss:
            raise LimitReached from None
    before = comtrade.calls_today()
    body = _report(hs6, week)
    if comtrade.calls_today() > before:
        _opened[key] = _opened.get(key, 0) + 1
    if counted:
        seen.add(hs6)                       # yalnızca rapor gerçekten açıldıysa sayılır; hatalı kod hakkı tüketmez
    return body


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, content_type, body, cache="no-cache"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")      # giriş bağlantısındaki kod başka sitelere sızmasın
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _visitor(self):
        """Ziyaretçinin adresi; vekil sunucu arkasında gerçek adres başlıkta gelir."""
        forwarded = self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        return forwarded or self.client_address[0]

    def _origin(self):
        host = self.headers.get("Host", "")
        return ("http://" if host.startswith(("localhost", "127.0.0.1")) else "https://") + host

    def _page(self, status):
        # Paylaşım görseli tam adres ister; alan adı istekten alınır, böylece her adreste doğru çıkar.
        origin = self._origin()
        html = versioned((WEB / "index.html").read_text(encoding="utf-8")).replace('content="/static/og.png"', f'content="{origin}/static/og.png"')
        if not DEMO or SOON:                  # ödeme penceresi gerçek ödemede fatura alanlarını, "yakında"da haber listesi gösterir
            html = html.replace("<body", f'<body data-odeme="{"yakinda" if DEMO else "gercek"}"', 1)
        # Rapor bağlantısı paylaşıldığında önizlemede ürünün adı görünsün.
        match = re.fullmatch(r"/rapor/(\d{6})/?", urllib.parse.urlparse(self.path).path)
        name = product_title(match.group(1)) if match else None
        if name:
            name = escape(name if len(name) <= 70 else name[:69].rstrip() + "…", quote=True)
            text = f"{name} ürününü hangi ülkelere satabileceğini, Türkiye'nin payını ve rakiplerini resmi ticaret verileriyle gösteren pazar raporu."
            html = re.sub(r"<title>.*?</title>", f"<title>{name} · {BRAND}</title>", html, count=1)
            html = re.sub(r'(<meta property="og:title" content=")[^"]*', rf"\g<1>{name} ihracat pazarları · {BRAND}", html, count=1)
            html = re.sub(r'(<meta (?:name="description"|property="og:description") content=")[^"]*', lambda m: m.group(1) + text, html)
        self._send(status, "text/html; charset=utf-8", html.encode("utf-8"))

    def _json(self, status, payload):
        self._send(status, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8"))

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        # Rapor adresleri de aynı sayfayı döndürür; hangi raporun açılacağına tarayıcıdaki kod karar verir.
        if url.path in PAGES or url.path.startswith("/rapor/"):
            self._page(200)
        elif url.path == "/robots.txt":
            self._send(200, "text/plain; charset=utf-8", (ROBOTS + f"Sitemap: {self._origin()}/sitemap.xml\n").encode("utf-8"))
        elif url.path == "/sitemap.xml":
            links = PAGES + [f"/rapor/{file.stem}" for file in sorted(READY.glob("*.json"))]
            body = "".join(f"<url><loc>{self._origin()}{link}</loc></url>" for link in links)
            self._send(200, "application/xml; charset=utf-8",
                       f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'.encode("utf-8"))
        elif url.path.startswith("/static/"):
            file = (WEB / url.path[len("/static/"):]).resolve()
            if file.is_file() and WEB in file.parents and file.suffix in STATIC_TYPES:
                # Sürüm etiketiyle istenen dosya hiç değişmez sayılır; etiketsiz stil ve betik her seferinde sorulur.
                tagged = "v" in urllib.parse.parse_qs(url.query)
                cache = "public, max-age=31536000, immutable" if tagged else "no-cache" if file.suffix in (".css", ".js") else "public, max-age=86400"
                self._send(200, STATIC_TYPES[file.suffix], file.read_bytes(), cache)
            else:
                self._send(404, "text/plain; charset=utf-8", "Bulunamadı".encode("utf-8"))
        elif url.path == "/api/ornek":
            found = sample(urllib.parse.parse_qs(url.query).get("gtip", [""])[0])
            self._json(200 if found else 404, found or {"error": "Bulunamadı"})
        elif url.path == "/api/hesap":
            # Tarayıcıdaki belirteci tazeler: başka cihazda alınan paket ya da biten üyelik buraya da yansır.
            grant = read_token(urllib.parse.parse_qs(url.query).get("t", [""])[0])
            try:
                self._json(200, session(grant["email"]) if grant["email"] else {"token": "", **read_token("")})
            except RuntimeError:              # üye veritabanına ulaşılamadı: tarayıcı eldeki oturumla devam eder
                traceback.print_exc()
                self._json(503, {"error": "Hesap bilgilerine şu an ulaşılamıyor."})
        elif url.path == "/api/doviz":
            try:
                self._json(200, doviz.rates())
            except Exception:
                traceback.print_exc()
                self._json(502, {"error": "Döviz kurları alınamadı."})
        elif url.path == "/api/ara":
            self._json(200, urunler.search(urllib.parse.parse_qs(url.query).get("q", [""])[0]))
        elif url.path == "/api/rapor":
            query = urllib.parse.parse_qs(url.query)
            gtip = re.sub(r"\D", "", query.get("gtip", [""])[0])
            grant = read_token(query.get("t", [""])[0])
            plan = "pro" if grant["pro"] else "free"
            try:
                # Günlük sınır Pro üyede hesaba, diğerlerinde internet adresine göre tutulur; böylece yeni hesap açmak sınırı sıfırlamaz.
                body = report(gtip[:6], grant["email"] if grant["pro"] else self._visitor(), plan, gtip[:6] in grant["reports"])
                # Lansman dönemi: ücretli paketler henüz satışta değilken üyeler günlük ürününün tam raporunu görür.
                launch = SOON and DEMO and bool(grant["email"])
                opened = grant["pro"] or gtip[:6] in grant["reports"] or gtip[:6] in OPEN_SAMPLES or launch
                self._send(200, "application/json; charset=utf-8", body if opened else locked(body))
            except LimitReached:
                if plan == "pro":
                    message = f"Bugünlük {DAILY_NEW['pro']} yeni ürün sınırına ulaştın. Daha önce açtığın ürünlere bakmaya devam edebilirsin. Yarın yeniden deneyebilirsin."
                else:
                    message = (f"Ücretsiz planda günde {DAILY_FREE} ürün raporu açabilirsin. Bugün açtığın ürüne ve örnek raporlara bakmaya devam edebilirsin. "
                               + ("Yarın yeni bir ürün arayabilirsin." if SOON else f"Pro pakette günlük sınır {DAILY_NEW['pro']} üründür."))
                self._json(429, {"error": message})
            except ValueError as error:
                self._json(400, {"error": str(error)})
            except RuntimeError:
                # Ayrıntı (istek adresi, kota) kullanıcıya değil günlüğe yazılır.
                traceback.print_exc()
                self._json(502, {"error": "Veri kaynağı şu an yanıt vermiyor. Birkaç dakika sonra tekrar dene."})
            except Exception:
                traceback.print_exc()
                self._json(500, {"error": "Rapor hazırlanırken beklenmeyen bir hata oluştu."})
        elif url.path == "/giris":
            self._page(200)
        elif url.path == "/odeme-form":
            # Abonelik ödeme formu: iyzico'nun betiği bu sayfaya gömülür, kart bilgisi doğrudan iyzico'ya gider.
            form, expires = _forms.get(urllib.parse.parse_qs(url.query).get("t", [""])[0], ("", 0))
            if not form or expires < time.time():
                return self._redirect("/paketler?odeme=basarisiz")
            html = (WEB / "odeme-form.html").read_text(encoding="utf-8").replace("<!--FORM-->", form)
            self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
        elif url.path == "/yonetim":
            # Panel ayrı bir sayfadır; verisi yalnızca yönetim şifresiyle açılan oturuma gelir.
            self._send(200, "text/html; charset=utf-8", versioned((WEB / "yonetim.html").read_text(encoding="utf-8")).encode("utf-8"))
        elif url.path.startswith("/api/"):
            self._json(404, {"error": "Bulunamadı"})
        else:
            self._page(404)                  # "sayfa bulunamadı" ekranını tarayıcıdaki kod gösterir

    do_HEAD = do_GET

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _payment_return(self, form):
        """iyzico alıcıyı ödeme sonrası buraya gönderir. Sonuç iyzico'ya sorulur; ödendiyse hak yazılır ve oturum açılır."""
        token = (urllib.parse.parse_qs(form).get("token") or [""])[0]
        order = uyelik.find_order(token) if not DEMO else None
        if not order:
            return self._redirect("/paketler?odeme=basarisiz")
        subscribing = order["hs6"] == SUBSCRIPTION
        try:
            outcome = odeme.subscribe_result(token) if subscribing else odeme.result(token, order["id"])
        except odeme.PaymentError:
            traceback.print_exc()
            return self._redirect("/paketler?odeme=belirsiz")
        _forms.pop(token, None)
        if subscribing:
            if not outcome["aktif"]:
                return self._redirect("/paketler?odeme=basarisiz")
            if not uyelik.close_order(order["id"], "iyzico", outcome["abonelik"]):
                return self._redirect("/paketler?odeme=tamam")
            uyelik.set_subscription(order["email"], outcome["abonelik"], "aktif")
            return self._redirect(f"/giris?k={uyelik.login_code(order['email'])}&d=%2F")
        if not outcome["odendi"] or outcome["tutar"] < order["amount"]:
            return self._redirect("/paketler?odeme=basarisiz")
        if not uyelik.close_order(order["id"], "iyzico", outcome["referans"]):
            return self._redirect("/paketler?odeme=tamam")        # sayfa yenilendi: hak zaten yazıldı, yeni oturum açılmaz
        target = f"/rapor/{order['hs6']}" if order["hs6"] else "/"
        self._redirect(f"/giris?k={uyelik.login_code(order['email'])}&d={urllib.parse.quote(target, safe='')}")

    def do_POST(self):
        try:
            self._post()
        except RuntimeError:                  # üye veritabanına ulaşılamadı
            traceback.print_exc()
            self._json(503, {"error": "Hesap bilgilerine şu an ulaşılamıyor. Biraz sonra tekrar dene."})

    def _post(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if path == "/odeme-sonuc":
                return self._payment_return(self.rfile.read(size).decode("utf-8", "replace") if 0 < size <= 4096 else "")
            data = json.loads(self.rfile.read(size).decode("utf-8")) if 0 < size <= 4096 else {}
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"error": "Geçersiz istek."})

        if path == "/api/giris":
            email = uyelik.normalize(data.get("eposta"))
            if not email:
                return self._json(400, {"error": "Geçerli bir e-posta adresi yaz."})
            if throttled(("ip", self._visitor()), ("eposta", email)):
                return self._json(429, {"error": "Çok fazla giriş isteği yapıldı. Bir saat sonra tekrar dene."})
            link = f"{self._origin()}/giris?k={uyelik.login_code(email)}"
            if uyelik.send_login(email, link):
                return self._json(200, {"gonderildi": True})
            if DEMO and not uyelik.mail_configured():      # posta henüz kurulmadıysa bağlantı ekranda verilir
                return self._json(200, {"gonderildi": False, "demo_baglanti": link})
            self._json(503, {"error": "Giriş e-postası gönderilemedi. Biraz sonra tekrar dene."})
        elif path == "/api/kayit":
            email, password = uyelik.normalize(data.get("eposta")), str(data.get("sifre") or "")
            name, company = (" ".join(str(data.get(key) or "").split())[:80] for key in ("ad", "firma"))
            if not email:
                return self._json(400, {"error": "Geçerli bir e-posta adresi yaz."})
            if not name:
                return self._json(400, {"error": "Adını ve soyadını yaz."})
            if not PASSWORD_MIN <= len(password) <= 200:
                return self._json(400, {"error": f"Şifren en az {PASSWORD_MIN} karakter olmalı."})
            if throttled(("kayit", self._visitor())):
                return self._json(429, {"error": "Çok fazla kayıt isteği yapıldı. Bir saat sonra tekrar dene."})
            if uyelik.register(email, name, company, password) == "var":
                return self._json(409, {"error": "Bu e-posta adresiyle açılmış bir hesap var. Giriş yapabilir ya da şifreni unuttuysan giriş bağlantısı isteyebilirsin."})
            self._json(200, session(email))
        elif path == "/api/giris-sifre":
            email, password = uyelik.normalize(data.get("eposta")), str(data.get("sifre") or "")
            if not email or not password:
                return self._json(400, {"error": "E-posta adresini ve şifreni yaz."})
            if throttled(("sifre", email)):
                return self._json(429, {"error": "Çok fazla deneme yapıldı. Bir saat sonra tekrar dene."})
            if not uyelik.check_password(email, password[:200]):
                return self._json(401, {"error": "E-posta adresi ya da şifre hatalı."})
            self._json(200, session(email))
        elif path == "/api/bekleme":
            email, kind = uyelik.normalize(data.get("eposta")), data.get("tur")
            if not email:
                return self._json(400, {"error": "Geçerli bir e-posta adresi yaz."})
            if kind not in PRICES:
                return self._json(400, {"error": "Geçersiz istek."})
            if throttled(("kayit", self._visitor())):
                return self._json(429, {"error": "Çok fazla istek yapıldı. Bir saat sonra tekrar dene."})
            uyelik.join_waitlist(email, kind)
            self._json(200, {"tamam": True})
        elif path == "/api/abonelik-iptal":
            email = read_token(str(data.get("t") or ""))["email"]
            current = uyelik.subscription(email) if email else {"durum": ""}
            if not email:
                return self._json(401, {"error": "Bu işlem için giriş yapman gerekir."})
            if current["durum"] != "aktif":
                return self._json(400, {"error": "Bu hesapta devam eden bir abonelik yok."})
            try:
                odeme.cancel_subscription(current["ref"])
            except odeme.PaymentError:
                traceback.print_exc()
                return self._json(502, {"error": "Abonelik şu an iptal edilemedi. Biraz sonra tekrar dene ya da bize yaz."})
            uyelik.set_subscription(email, current["ref"], "iptal")
            self._json(200, session(email))
        elif path == "/api/profil":
            email = read_token(str(data.get("t") or ""))["email"]
            password = str(data.get("sifre") or "")
            if not email:
                return self._json(401, {"error": "Bu işlem için giriş yapman gerekir."})
            if password and not PASSWORD_MIN <= len(password) <= 200:
                return self._json(400, {"error": f"Şifren en az {PASSWORD_MIN} karakter olmalı."})
            if password and uyelik.profile(email)["sifre_var"]:
                # Şifresi olan hesapta yeni şifre için mevcut şifre de istenir; oturumu ele geçiren biri şifreyi değiştiremesin.
                if throttled(("sifre", email)):
                    return self._json(429, {"error": "Çok fazla deneme yapıldı. Bir saat sonra tekrar dene."})
                if not uyelik.check_password(email, str(data.get("eski") or "")[:200]):
                    return self._json(403, {"error": "Mevcut şifren hatalı."})
            if "ad" in data and not " ".join(str(data["ad"] or "").split()):
                return self._json(400, {"error": "Adını ve soyadını yaz."})
            clean = lambda key: " ".join(str(data[key] or "").split())[:80] if key in data else None
            uyelik.update_profile(email, clean("ad"), clean("firma"), password or None)
            self._json(200, session(email))
        elif path == "/api/yonetim/giris":
            expected = os.environ.get("ADMIN_PASSWORD") or ""
            if not expected:
                return self._json(404, {"error": "Bulunamadı"})
            if throttled(("yonetim", self._visitor())):
                return self._json(429, {"error": "Çok fazla deneme yapıldı. Bir saat sonra tekrar dene."})
            if not hmac.compare_digest(str(data.get("sifre") or "").encode(), expected.encode()):
                return self._json(401, {"error": "Şifre hatalı."})
            self._json(200, {"t": admin_token(), **admin_view()})
        elif path == "/api/yonetim":
            if not is_admin(str(data.get("t") or "")):
                return self._json(401, {"error": "Yönetim oturumu kapalı. Yeniden giriş yap."})
            action, email = data.get("islem"), uyelik.normalize(data.get("eposta"))
            code = re.sub(r"\D", "", str(data.get("gtip") or ""))[:6]
            if action in ("pro-ay", "pro-yil", "pro-bitir", "rapor", "sil") and not email:
                return self._json(400, {"error": "Geçerli bir e-posta adresi yaz."})
            if action == "pro-ay":
                uyelik.record_purchase(email, "pro", None, 0, "yonetim")
            elif action == "pro-yil":
                uyelik.record_purchase(email, "yearly", None, 0, "yonetim")
            elif action == "pro-bitir":
                uyelik.end_pro(email)
            elif action == "rapor":
                if len(code) != 6:
                    return self._json(400, {"error": "Rapor açmak için 6 haneli ürün kodunu yaz."})
                uyelik.record_purchase(email, "single", code, 0, "yonetim")
            elif action == "sil":
                uyelik.delete_member(email)
            elif action != "liste":
                return self._json(400, {"error": "Geçersiz istek."})
            self._json(200, admin_view())
        elif path == "/api/giris-onay":
            email = uyelik.redeem(str(data.get("k") or ""))
            if not email:
                return self._json(400, {"error": "Bu giriş bağlantısının süresi dolmuş ya da daha önce kullanılmış. Yeni bir bağlantı iste."})
            self._json(200, session(email))
        elif path == "/api/odeme":
            kind, email = data.get("tur"), uyelik.normalize(data.get("eposta"))
            code = re.sub(r"\D", "", str(data.get("gtip") or ""))[:6]
            if kind not in PRICES or (kind == "single" and len(code) != 6):
                return self._json(400, {"error": "Geçersiz istek."})
            if not email:
                return self._json(400, {"error": "Paketin hesabına tanımlanması için geçerli bir e-posta adresi yaz."})
            if data.get("onay") is not True:
                return self._json(400, {"error": "Devam etmek için mesafeli satış sözleşmesini ve iade koşullarını onayla."})
            if not DEMO:
                # Gerçek ödeme: alıcı iyzico'nun sayfasına gider; hak, dönüşte ödeme doğrulanınca yazılır (_payment_return).
                buyer = {key: " ".join(str(data.get(key) or "").split())[:limit] for key, limit in (("ad", 60), ("soyad", 60), ("adres", 200), ("sehir", 40))}
                if not all(buyer.values()):
                    return self._json(400, {"error": "Fatura için ad, soyad, adres ve şehir alanlarını doldur."})
                if kind == "pro":
                    # Aylık paket iyzico aboneliğidir: kart saklanır ve her ay kendiliğinden tahsil edilir.
                    if not odeme.subscriptions_ready():
                        return self._json(503, {"error": "Aylık paket şu an satın alınamıyor. Yıllık paketi seçebilir ya da daha sonra tekrar deneyebilirsin."})
                    buyer["telefon"] = odeme.phone(data.get("telefon"))
                    if not buyer["telefon"]:
                        return self._json(400, {"error": "Aylık abonelik için geçerli bir cep telefonu numarası yaz."})
                    if uyelik.subscription(email)["durum"] == "aktif":
                        return self._json(409, {"error": "Bu hesapta devam eden bir aylık abonelik var."})
                order_id = uyelik.open_order(email, kind, code if kind == "single" else SUBSCRIPTION if kind == "pro" else None, PRICES[kind])
                try:
                    if kind == "pro":
                        token, form = odeme.subscribe_start(order_id, email, buyer, self._origin() + "/odeme-sonuc")
                        _forms[token] = (form, time.time() + 1800)
                        page = "/odeme-form?t=" + urllib.parse.quote(token, safe="")
                    else:
                        page, token = odeme.start(order_id, kind, PRICES[kind], email, buyer, self._visitor(), self._origin() + "/odeme-sonuc")
                except odeme.PaymentError:
                    traceback.print_exc()
                    return self._json(502, {"error": "Ödeme sayfası şu an açılamıyor. Biraz sonra tekrar dene."})
                uyelik.tag_order(order_id, token)
                return self._json(200, {"odeme_url": page})
            if not FREE_GRANTS:
                return self._json(409, {"error": "Ücretli paketler yakında açılacak."})
            uyelik.record_purchase(email, kind, code if kind == "single" else None, PRICES[kind], "demo")
            self._json(200, session(email))
        elif path == "/api/demo-sifirla":
            email = read_token(str(data.get("t") or ""))["email"]
            if DEMO and email:
                uyelik.clear_demo(email)
            self._json(200, {"token": "", **read_token("")})
        else:
            self._json(404, {"error": "Bulunamadı"})


if __name__ == "__main__":
    # Barındırma ortamı PORT değişkenini verir ve dışarıdan erişim ister; yerelde yalnızca bu bilgisayar.
    port = int(os.environ.get("PORT", PORT))
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    print(f"İhraçbul: http://localhost:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
