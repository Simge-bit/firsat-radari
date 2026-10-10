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


def _call(path, body):
    api_key, secret = os.environ["IYZICO_API_KEY"], os.environ["IYZICO_SECRET_KEY"]
    payload, nonce = json.dumps(body), secrets.token_hex(8)
    signed = hmac.new(secret.encode(), (nonce + path + payload).encode(), hashlib.sha256).hexdigest()
    token = base64.b64encode(f"apiKey:{api_key}&randomKey:{nonce}&signature:{signed}".encode()).decode()
    request = urllib.request.Request(_base() + path, data=payload.encode(), headers={
        "Accept": "application/json", "Content-Type": "application/json", "x-iyzi-rnd": nonce, "Authorization": "IYZWSv2 " + token})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=20).read().decode("utf-8"))
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
