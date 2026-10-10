"""iyzico ile ödeme: ödeme sayfasını açar ve sonucu iyzico'dan doğrular.

Kart bilgisi bu siteye hiç gelmez; alıcı iyzico'nun kendi ödeme sayfasında öder.
Akış: start() ödeme sayfasının adresini verir -> alıcı öder -> iyzico alıcıyı belirteçle geri gönderir
-> result() o belirteci iyzico'ya sorar. Hak yalnızca bu yanıt "ödendi" derse yazılır.

Ayarlar ortam değişkenlerindedir: IYZICO_API_KEY, IYZICO_SECRET_KEY ve IYZICO_BASE
(deneme: https://sandbox-api.iyzipay.com, gerçek: https://api.iyzipay.com).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import urllib.error
import urllib.request

SANDBOX = "https://sandbox-api.iyzipay.com"
NAMES = {"single": "Tek rapor", "pro": "Pro, aylık", "yearly": "Pro, yıllık"}
# iyzico her alıcı için kimlik numarası ister; site bunu toplamaz, iyzico'nun bu durum için kabul ettiği değer gönderilir.
NO_IDENTITY = "11111111111"


class PaymentError(Exception):
    """iyzico'ya ulaşılamadı ya da yanıtı güvenilir değil."""


def configured():
    return bool(os.environ.get("IYZICO_API_KEY") and os.environ.get("IYZICO_SECRET_KEY"))


def _base():
    return (os.environ.get("IYZICO_BASE") or SANDBOX).rstrip("/")


def _signature(*parts):
    """iyzico yanıtlarındaki imza: alanlar ":" ile birleştirilip gizli anahtarla imzalanır."""
    return hmac.new(os.environ["IYZICO_SECRET_KEY"].encode(), ":".join(parts).encode(), hashlib.sha256).hexdigest()


def _amount(value):
    """iyzico imzada tutarı sondaki ".0" olmadan kullanır: 490.0 -> "490", 490.5 -> "490.5"."""
    text = str(value)
    return text[:-2] if text.endswith(".0") else text


def _call(path, body, method="POST"):
    api_key, secret = os.environ["IYZICO_API_KEY"], os.environ["IYZICO_SECRET_KEY"]
    payload, nonce = json.dumps(body), secrets.token_hex(8)
    signed = hmac.new(secret.encode(), (nonce + path + payload).encode(), hashlib.sha256).hexdigest()
    token = base64.b64encode(f"apiKey:{api_key}&randomKey:{nonce}&signature:{signed}".encode()).decode()
    request = urllib.request.Request(_base() + path, data=payload.encode(), headers={
        "Accept": "application/json", "Content-Type": "application/json", "x-iyzi-rnd": nonce, "Authorization": "IYZWSv2 " + token}, method=method)
    try:
        return json.loads(urllib.request.urlopen(request, timeout=20).read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # iyzico hatalarını da JSON gövdeyle bildirir; okunabiliyorsa çağıran karar verir.
        try:
            return json.loads(error.read().decode("utf-8"))
        except ValueError:
            raise PaymentError(str(error)) from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise PaymentError(str(error)) from error


def start(order_id, kind, amount, email, buyer, ip, callback):
    """Ödeme sayfasını açar: (ödeme sayfasının adresi, belirteç).

    buyer: {"ad", "soyad", "adres", "sehir"}; fatura için alıcıdan alınır.
    """
    price = f"{amount}.0"
    address = {"contactName": f"{buyer['ad']} {buyer['soyad']}", "city": buyer["sehir"], "country": "Turkey", "address": buyer["adres"]}
    reply = _call("/payment/iyzipos/checkoutform/initialize/auth/ecom", {
        "locale": "tr", "conversationId": order_id, "price": price, "paidPrice": price, "currency": "TRY",
        "basketId": order_id, "paymentGroup": "PRODUCT", "callbackUrl": callback, "enabledInstallments": [1],
        "buyer": {"id": hashlib.sha256(email.encode()).hexdigest()[:20], "name": buyer["ad"], "surname": buyer["soyad"], "email": email,
                  "identityNumber": NO_IDENTITY, "registrationAddress": buyer["adres"], "city": buyer["sehir"], "country": "Turkey", "ip": ip},
        "billingAddress": address,
        "basketItems": [{"id": kind, "name": "İhraçbul " + NAMES[kind], "category1": "Dijital hizmet", "itemType": "VIRTUAL", "price": price}],
    })
    if reply.get("status") != "success" or not reply.get("token") or not reply.get("paymentPageUrl"):
        raise PaymentError(reply.get("errorMessage") or "Ödeme sayfası açılamadı.")
    if not hmac.compare_digest(str(reply.get("signature") or ""), _signature(order_id, reply["token"])):
        raise PaymentError("Yanıt imzası doğrulanamadı.")
    return reply["paymentPageUrl"], reply["token"]


def result(token, order_id):
    """Ödemenin sonucu: {"odendi": bool, "tutar": float, "referans": iyzico ödeme numarası, "neden": hata iletisi}."""
    reply = _call("/payment/iyzipos/checkoutform/auth/ecom/detail", {"locale": "tr", "conversationId": order_id, "token": token})
    if reply.get("status") != "success":
        return {"odendi": False, "tutar": 0, "referans": None, "neden": reply.get("errorMessage") or "Ödeme tamamlanmadı."}
    expected = _signature(str(reply.get("paymentStatus")), str(reply.get("paymentId")), str(reply.get("currency")), str(reply.get("basketId")),
                          str(reply.get("conversationId")), _amount(reply.get("paidPrice")), _amount(reply.get("price")), str(reply.get("token")))
    if not hmac.compare_digest(str(reply.get("signature") or ""), expected):
        raise PaymentError("Yanıt imzası doğrulanamadı.")
    paid = (reply.get("paymentStatus") == "SUCCESS" and reply.get("basketId") == order_id
            and reply.get("token") == token and reply.get("currency") == "TRY")
    return {"odendi": paid, "tutar": float(reply.get("paidPrice") or 0), "referans": str(reply.get("paymentId")),
            "neden": None if paid else "Ödeme onaylanmadı."}


# ---------- Aylık abonelik: iyzico kartı saklar ve her ay kendisi tahsil eder ----------
# Plan bir kez tools/iyzico_plan.py ile açılır; referans kodu IYZICO_PLAN_MONTHLY ortam değişkenine girilir.

def subscriptions_ready():
    return configured() and bool(os.environ.get("IYZICO_PLAN_MONTHLY"))


def phone(text):
    """Telefonu iyzico'nun istediği biçime çevirir: +905xxxxxxxxx. Geçerli bir cep numarası değilse None."""
    digits = "".join(char for char in str(text or "") if char.isdigit())
    digits = digits[2:] if digits.startswith("90") and len(digits) == 12 else digits[1:] if digits.startswith("0") and len(digits) == 11 else digits
    return "+90" + digits if len(digits) == 10 and digits.startswith("5") else None


def subscribe_start(order_id, email, buyer, callback):
    """Abonelik ödeme formunu açar: (belirteç, sayfaya gömülecek form betiği).

    buyer: {"ad", "soyad", "adres", "sehir", "telefon"}. Bu formda iyzico yönlendirme adresi vermez; form sitedeki
    ödeme sayfasına gömülür, kart bilgisi yine doğrudan iyzico'ya gider.
    """
    reply = _call("/v2/subscription/checkoutform/initialize", {
        "locale": "tr", "conversationId": order_id, "callbackUrl": callback,
        "pricingPlanReferenceCode": os.environ["IYZICO_PLAN_MONTHLY"], "subscriptionInitialStatus": "ACTIVE",
        "customer": {"name": buyer["ad"], "surname": buyer["soyad"], "email": email, "gsmNumber": buyer["telefon"], "identityNumber": NO_IDENTITY,
                     "billingAddress": {"contactName": f"{buyer['ad']} {buyer['soyad']}", "city": buyer["sehir"], "country": "Turkey", "address": buyer["adres"]}},
    })
    if reply.get("status") != "success" or not reply.get("token") or not reply.get("checkoutFormContent"):
        raise PaymentError(reply.get("errorMessage") or "Abonelik formu açılamadı.")
    return reply["token"], reply["checkoutFormContent"]


def subscribe_result(token):
    """Abonelik formunun sonucu: {"aktif": bool, "abonelik": referans kodu, "neden": hata iletisi}."""
    reply = _call(f"/v2/subscription/checkoutform/{token}", {"token": token}, "GET")
    data = reply.get("data") or {}
    active = reply.get("status") == "success" and data.get("subscriptionStatus") == "ACTIVE" and bool(data.get("referenceCode"))
    return {"aktif": active, "abonelik": data.get("referenceCode"), "neden": None if active else reply.get("errorMessage") or "Abonelik başlatılamadı."}


def subscription_period(reference):
    """Aboneliğin durumu ve ödenmiş son dönemin bitişi: {"durum": "ACTIVE" | "CANCELED" | ..., "bitis": saniye ya da None, "donem": dönem kodu}."""
    reply = _call(f"/v2/subscription/subscriptions/{reference}", {"subscriptionReferenceCode": reference}, "GET")
    if reply.get("status") != "success":
        raise PaymentError(reply.get("errorMessage") or "Abonelik durumu alınamadı.")
    data = reply.get("data") or {}
    item = (data.get("items") or [data])[0]
    paid = [order for order in item.get("orders") or [] if order.get("orderStatus") == "SUCCESS" and order.get("endPeriod")]
    last = max(paid, key=lambda order: order["endPeriod"]) if paid else None
    return {"durum": item.get("subscriptionStatus"), "bitis": last["endPeriod"] / 1000 if last else None, "donem": last.get("referenceCode") if last else None}


def cancel_subscription(reference):
    """Aboneliği iyzico'da iptal eder; sonraki ay tahsilat yapılmaz. Başarısızsa PaymentError."""
    reply = _call(f"/v2/subscription/subscriptions/{reference}/cancel", {"subscriptionReferenceCode": reference})
    if reply.get("status") != "success":
        raise PaymentError(reply.get("errorMessage") or "Abonelik iptal edilemedi.")
