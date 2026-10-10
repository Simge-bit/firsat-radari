"""Üyeler, satın almalar ve e-postayla giriş.

Hesap bir e-posta adresidir; şifre yoktur. Giriş için adrese tek kullanımlık bir bağlantı gönderilir.
Veriler SQLite dosyasında durur (IHRACBUL_DB ortam değişkeni ya da proje kökünde veri/uyeler.db).
Barındırma ortamında bu dosyanın kalıcı bir diskte olması gerekir; yoksa sunucu yeniden başladığında hesaplar silinir.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGIN_MINUTES = 20
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


def _db():
    path = Path(os.environ.get("IHRACBUL_DB") or ROOT / "veri" / "uyeler.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS uyeler (eposta TEXT PRIMARY KEY, pro_bitis REAL NOT NULL DEFAULT 0, raporlar TEXT NOT NULL DEFAULT '[]', kayit REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS giris_kodlari (kod TEXT PRIMARY KEY, eposta TEXT NOT NULL, bitis REAL NOT NULL, kullanildi INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS satin_almalar (id INTEGER PRIMARY KEY, eposta TEXT NOT NULL, tur TEXT NOT NULL, urun TEXT, tutar INTEGER NOT NULL,
                                                 zaman REAL NOT NULL, saglayici TEXT NOT NULL, referans TEXT);
        CREATE TABLE IF NOT EXISTS siparisler (id TEXT PRIMARY KEY, eposta TEXT NOT NULL, tur TEXT NOT NULL, urun TEXT, tutar INTEGER NOT NULL,
                                              zaman REAL NOT NULL, belirtec TEXT, odendi INTEGER NOT NULL DEFAULT 0);
    """)
    # Sonradan eklenen sütunlar: eski veritabanı dosyası açılışta tamamlanır.
    columns = {row[1] for row in connection.execute("PRAGMA table_info(uyeler)")}
    for name in ("ad", "firma", "sifre"):
        if name not in columns:
            connection.execute(f"ALTER TABLE uyeler ADD COLUMN {name} TEXT")
    return connection


def normalize(email):
    """Geçerli e-postanın küçük harfli hali, değilse None."""
    email = (email or "").strip().lower()
    return email if len(email) <= 254 and EMAIL.fullmatch(email) else None


def grants(email):
    """Üyenin hakları: {"email", "pro", "pro_until", "reports"}. Üye yoksa boş haklar."""
    with _db() as db:
        row = db.execute("SELECT pro_bitis, raporlar FROM uyeler WHERE eposta = ?", (email,)).fetchone()
    until, reports = (row[0], json.loads(row[1])) if row else (0, [])
    return {"email": email, "pro": until > time.time(), "pro_until": until if until > time.time() else 0, "reports": reports}


def _hash(password, salt=None):
    """Şifrenin saklanan hali: "tuz$özet". Şifrenin kendisi hiçbir yerde tutulmaz."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex()
    return salt + "$" + digest


def profile(email):
    """Üyenin görünen bilgileri: {"ad", "firma", "sifre_var"}. Üye yoksa boş."""
    with _db() as db:
        row = db.execute("SELECT ad, firma, sifre FROM uyeler WHERE eposta = ?", (email,)).fetchone()
    return {"ad": (row[0] or "") if row else "", "firma": (row[1] or "") if row else "", "sifre_var": bool(row and row[2])}


def register(email, name, company, password):
    """Yeni üye açar: "tamam". Adres kayıtlıysa "var" döner ve hiçbir şey değişmez.

    Şifresiz kayıt (yalnızca paket almış üye) da "var" sayılır: adresin sahibi olduğunu e-postadaki bağlantıyla
    kanıtlayıp şifresini hesabından belirler. Aksi halde başkası o adrese şifre koyup paketi ele geçirebilirdi.
    """
    with _db() as db:
        if db.execute("SELECT 1 FROM uyeler WHERE eposta = ?", (email,)).fetchone():
            return "var"
        db.execute("INSERT INTO uyeler (eposta, kayit, ad, firma, sifre) VALUES (?, ?, ?, ?, ?)", (email, time.time(), name, company, _hash(password)))
    return "tamam"


def check_password(email, password):
    with _db() as db:
        row = db.execute("SELECT sifre FROM uyeler WHERE eposta = ?", (email,)).fetchone()
    if not row or not row[0]:
        return False
    salt = row[0].split("$")[0]
    return hmac.compare_digest(row[0], _hash(password, salt))


def update_profile(email, name=None, company=None, password=None):
    """Giriş yapmış üyenin adını, firmasını ya da şifresini değiştirir; verilmeyen alan olduğu gibi kalır."""
    with _db() as db:
        db.execute("INSERT OR IGNORE INTO uyeler (eposta, kayit) VALUES (?, ?)", (email, time.time()))
        if name is not None:
            db.execute("UPDATE uyeler SET ad = ? WHERE eposta = ?", (name, email))
        if company is not None:
            db.execute("UPDATE uyeler SET firma = ? WHERE eposta = ?", (company, email))
        if password:
            db.execute("UPDATE uyeler SET sifre = ? WHERE eposta = ?", (_hash(password), email))


def record_purchase(email, kind, hs6, amount, provider, reference=None):
    """Satın almayı kaydeder ve hakkı üyeye yazar. kind: "single" | "pro" (aylık) | "yearly"."""
    now = time.time()
    with _db() as db:
        db.execute("INSERT OR IGNORE INTO uyeler (eposta, kayit) VALUES (?, ?)", (email, now))
        until, reports = db.execute("SELECT pro_bitis, raporlar FROM uyeler WHERE eposta = ?", (email,)).fetchone()
        reports = json.loads(reports)
        if kind == "single":
            reports = sorted(set(reports) | {hs6})
        else:
            # Süresi dolmamış üyelik varsa yeni dönem onun bitişine eklenir.
            until = max(until, now) + (366 if kind == "yearly" else 31) * 86400
        db.execute("UPDATE uyeler SET pro_bitis = ?, raporlar = ? WHERE eposta = ?", (until, json.dumps(reports), email))
        db.execute("INSERT INTO satin_almalar (eposta, tur, urun, tutar, zaman, saglayici, referans) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (email, kind, hs6, amount, now, provider, reference))
    return grants(email)


def open_order(email, kind, hs6, amount):
    """Ödeme bekleyen bir sipariş açar ve numarasını döner. Hak, ödeme onaylanınca close_order ile yazılır."""
    order_id = secrets.token_hex(12)
    with _db() as db:
        db.execute("INSERT INTO siparisler (id, eposta, tur, urun, tutar, zaman) VALUES (?, ?, ?, ?, ?, ?)", (order_id, email, kind, hs6, amount, time.time()))
    return order_id


def tag_order(order_id, token):
    """Ödeme kuruluşunun siparişe verdiği belirteci kaydeder; dönüşte sipariş bu belirteçle bulunur."""
    with _db() as db:
        db.execute("UPDATE siparisler SET belirtec = ? WHERE id = ?", (token, order_id))


def find_order(token):
    """Belirtece ait sipariş: {"id", "email", "kind", "hs6", "amount", "paid"}; yoksa None."""
    with _db() as db:
        row = db.execute("SELECT id, eposta, tur, urun, tutar, odendi FROM siparisler WHERE belirtec = ?", (token or "",)).fetchone()
    return dict(zip(("id", "email", "kind", "hs6", "amount", "paid"), row)) if row else None


def close_order(order_id, provider, reference):
    """Ödenmiş siparişin hakkını yazar. Aynı sipariş ikinci kez gelirse hak yeniden yazılmaz ve False döner."""
    with _db() as db:
        claimed = db.execute("UPDATE siparisler SET odendi = 1 WHERE id = ? AND odendi = 0", (order_id,)).rowcount
        row = db.execute("SELECT eposta, tur, urun, tutar FROM siparisler WHERE id = ?", (order_id,)).fetchone()
    if not claimed:
        return False
    record_purchase(row[0], row[1], row[2], row[3], provider, reference)
    return True


def clear_demo(email):
    """Gösterim ödemesiyle açılan hakları siler (yalnızca gösterim modunda çağrılır)."""
    with _db() as db:
        db.execute("UPDATE uyeler SET pro_bitis = 0, raporlar = '[]' WHERE eposta = ?", (email,))
        db.execute("DELETE FROM satin_almalar WHERE eposta = ? AND saglayici = 'demo'", (email,))


def login_code(email):
    """Tek kullanımlık giriş kodu üretir ve saklar."""
    code = secrets.token_urlsafe(32)
    with _db() as db:
        db.execute("DELETE FROM giris_kodlari WHERE bitis < ?", (time.time(),))
        db.execute("INSERT INTO giris_kodlari (kod, eposta, bitis) VALUES (?, ?, ?)", (code, email, time.time() + LOGIN_MINUTES * 60))
    return code


def redeem(code):
    """Giriş kodunu kullanır: geçerliyse e-postayı döner ve kodu bir daha kullanılmaz yapar; değilse None."""
    with _db() as db:
        row = db.execute("SELECT eposta FROM giris_kodlari WHERE kod = ? AND bitis > ? AND kullanildi = 0", (code or "", time.time())).fetchone()
        if not row:
            return None
        db.execute("UPDATE giris_kodlari SET kullanildi = 1 WHERE kod = ?", (code,))
    return row[0]


def mail_configured():
    return all(os.environ.get(name) for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS"))


def send_login(email, link):
    """Giriş bağlantısını e-postayla gönderir. Posta ayarlı değilse ya da gönderilemezse False."""
    if not mail_configured():
        return False
    message = EmailMessage()
    message["From"] = os.environ.get("MAIL_FROM") or os.environ["SMTP_USER"]
    message["To"] = email
    message["Subject"] = "İhraçbul giriş bağlantın"
    message.set_content(f"Merhaba,\n\nİhraçbul'a giriş yapmak için aşağıdaki bağlantıya tıkla. Bağlantı {LOGIN_MINUTES} dakika geçerlidir "
                        f"ve yalnızca bir kez kullanılabilir.\n\n{link}\n\nBu isteği sen yapmadıysan bu e-postayı yok sayabilirsin.\n\nİhraçbul")
    try:
        with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", 465)), context=ssl.create_default_context(), timeout=20) as server:
            server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
            server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        return False
