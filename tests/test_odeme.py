"""iyzico ödeme akışı, iyzico'yu taklit eden yerel bir sunucuya karşı. Çalıştırma: python3 -m unittest discover tests"""

import base64
import hashlib
import hmac
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("IHRACBUL_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("IHRACBUL_SECRET", "test-anahtari")

import odeme  # noqa: E402
import server  # noqa: E402
import uyelik  # noqa: E402

API_KEY, SECRET = "sandbox-deneme", "sandbox-gizli"
payments = {}            # belirteç -> {"basket", "price", "status"}; testler durumu buradan değiştirir
subs = {}                # abonelik belirteci -> {"ref", "status", "orders", "request"}; iyzico'nun abonelik tarafı
tamper = {"signature": False}


def signed(*parts):
    return hmac.new(SECRET.encode(), ":".join(parts).encode(), hashlib.sha256).hexdigest()


class FakeIyzico(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"])).decode()
        body, nonce = json.loads(raw), self.headers["x-iyzi-rnd"]
        mark = hmac.new(SECRET.encode(), (nonce + self.path + raw).encode(), hashlib.sha256).hexdigest()
        expected = "IYZWSv2 " + base64.b64encode(f"apiKey:{API_KEY}&randomKey:{nonce}&signature:{mark}".encode()).decode()
        if self.headers["Authorization"] != expected:
            reply = {"status": "failure", "errorMessage": "Geçersiz imza"}
        elif self.path == "/v2/subscription/checkoutform/initialize":
            token = "sub-" + body["conversationId"]
            now = int(__import__("time").time() * 1000)
            subs[token] = {"ref": "abn-" + body["conversationId"], "status": "ACTIVE", "request": body,
                           "orders": [{"referenceCode": "donem-1-" + body["conversationId"], "orderStatus": "SUCCESS", "startPeriod": now, "endPeriod": now + 30 * 86400000}]}
            reply = {"status": "success", "token": token, "checkoutFormContent": "<script>/* iyzico formu */</script>", "tokenExpireTime": 1800}
        elif self.path.startswith("/v2/subscription/checkoutform/"):
            sub = subs.get(self.path.rsplit("/", 1)[1])
            reply = {"status": "success", "data": {"referenceCode": sub["ref"], "subscriptionStatus": sub["status"]}} if sub else {"status": "failure", "errorMessage": "yok"}
        elif self.path.endswith("/cancel"):
            sub = next((item for item in subs.values() if item["ref"] == self.path.split("/")[-2]), None)
            if sub:
                sub["status"] = "CANCELED"
            reply = {"status": "success" if sub else "failure"}
        elif self.path.startswith("/v2/subscription/subscriptions/"):
            sub = next((item for item in subs.values() if item["ref"] == self.path.rsplit("/", 1)[1]), None)
            reply = ({"status": "success", "data": {"items": [{"referenceCode": sub["ref"], "subscriptionStatus": sub["status"], "orders": sub["orders"]}]}}
                     if sub else {"status": "failure", "errorMessage": "yok"})
        elif self.path.endswith("/initialize/auth/ecom"):
            token = "tok-" + body["basketId"]
            payments[token] = {"basket": body["basketId"], "price": float(body["paidPrice"]), "status": "SUCCESS", "request": body}
            reply = {"status": "success", "conversationId": body["conversationId"], "token": token,
                     "paymentPageUrl": "https://sandbox-cpp.iyzipay.com?token=" + token, "signature": signed(body["conversationId"], token)}
        else:
            payment = payments[body["token"]]
            price = payment["price"]
            reply = {"status": "success", "paymentStatus": payment["status"], "paymentId": "777", "currency": "TRY", "basketId": payment["basket"],
                     "conversationId": body["conversationId"], "paidPrice": price, "price": price, "token": body["token"]}
            reply["signature"] = signed(payment["status"], "777", "TRY", payment["basket"], body["conversationId"],
                                        odeme._amount(price), odeme._amount(price), body["token"])
            if tamper["signature"]:
                reply["paymentStatus"] = "SUCCESS"            # imzalandıktan sonra değiştirilmiş yanıt
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


FakeIyzico.do_GET = FakeIyzico.do_POST      # iyzico'nun sorgu uçları GET'tir; imza ve gövde aynı biçimde gelir


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Odeme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = ThreadingHTTPServer(("127.0.0.1", 0), FakeIyzico)
        cls.site = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        for service in (cls.bank, cls.site):
            threading.Thread(target=service.serve_forever, daemon=True).start()
        os.environ.update(IYZICO_API_KEY=API_KEY, IYZICO_SECRET_KEY=SECRET, IYZICO_BASE=f"http://127.0.0.1:{cls.bank.server_port}", IYZICO_PLAN_MONTHLY="plan-aylik")
        server.DEMO = False
        cls.url = f"http://127.0.0.1:{cls.site.server_port}"

    @classmethod
    def tearDownClass(cls):
        server.DEMO = True
        for name in ("IYZICO_API_KEY", "IYZICO_SECRET_KEY", "IYZICO_BASE", "IYZICO_PLAN_MONTHLY"):
            del os.environ[name]
        cls.bank.shutdown()
        cls.site.shutdown()

    def setUp(self):
        tamper["signature"] = False

    def buy(self, email, kind="single", **extra):
        body = {"tur": kind, "gtip": "570242", "eposta": email, "onay": True, "ad": "Ayşe", "soyad": "Yılmaz", "adres": "Atatürk Cad. 1", "sehir": "Yalova", **extra}
        request = urllib.request.Request(self.url + "/api/odeme", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            return json.loads(urllib.request.urlopen(request).read())
        except urllib.error.HTTPError as error:
            return {"status": error.code, **json.loads(error.read())}

    def come_back(self, token):
        """Alıcının iyzico'dan dönüşü: yönlendirildiği adres."""
        request = urllib.request.Request(self.url + "/odeme-sonuc", data=urllib.parse.urlencode({"token": token}).encode())
        try:
            urllib.request.build_opener(NoRedirect).open(request)
        except urllib.error.HTTPError as error:
            return error.headers["Location"]

    def token_of(self, reply):
        return reply["odeme_url"].split("token=")[1]

    def test_odeme_sayfasi_acilir_ama_hak_yazilmaz(self):
        reply = self.buy("once@firma.com")
        self.assertIn("iyzipay.com", reply["odeme_url"])
        self.assertNotIn("token", {key for key in reply if key != "odeme_url"})
        self.assertEqual(uyelik.grants("once@firma.com")["reports"], [])

    def test_iyzicoya_dogru_tutar_gider(self):
        sent = payments[self.token_of(self.buy("tutar@firma.com", "yearly"))]["request"]
        self.assertEqual((sent["price"], sent["paidPrice"], sent["currency"]), ("9000.0", "9000.0", "TRY"))
        self.assertEqual(sent["basketItems"][0]["itemType"], "VIRTUAL")
        self.assertTrue(sent["callbackUrl"].endswith("/odeme-sonuc"))

    def test_odenince_hak_yazilir_ve_oturum_acilir(self):
        target = self.come_back(self.token_of(self.buy("odedi@firma.com")))
        self.assertTrue(target.startswith("/giris?k="))
        self.assertIn(urllib.parse.quote("/rapor/570242", safe=""), target)
        self.assertEqual(uyelik.grants("odedi@firma.com")["reports"], ["570242"])
        code = urllib.parse.parse_qs(target.split("?")[1])["k"][0]
        self.assertEqual(uyelik.redeem(code), "odedi@firma.com")

    def test_ayni_donus_iki_kez_hak_yazmaz(self):
        token = self.token_of(self.buy("iki@firma.com", "yearly"))
        self.come_back(token)
        until = uyelik.grants("iki@firma.com")["pro_until"]
        self.assertEqual(self.come_back(token), "/paketler?odeme=tamam")
        self.assertEqual(uyelik.grants("iki@firma.com")["pro_until"], until)

    def test_basarisiz_odeme_hak_yazmaz(self):
        token = self.token_of(self.buy("red@firma.com", "yearly"))
        payments[token]["status"] = "FAILURE"
        self.assertEqual(self.come_back(token), "/paketler?odeme=basarisiz")
        self.assertFalse(uyelik.grants("red@firma.com")["pro"])

    def test_eksik_tutar_hak_yazmaz(self):
        token = self.token_of(self.buy("eksik@firma.com", "yearly"))
        payments[token]["price"] = 1.0
        self.assertEqual(self.come_back(token), "/paketler?odeme=basarisiz")
        self.assertFalse(uyelik.grants("eksik@firma.com")["pro"])

    def test_oynanmis_yanit_reddedilir(self):
        token = self.token_of(self.buy("sahte@firma.com", "yearly"))
        payments[token]["status"] = "FAILURE"
        tamper["signature"] = True
        self.assertEqual(self.come_back(token), "/paketler?odeme=belirsiz")
        self.assertFalse(uyelik.grants("sahte@firma.com")["pro"])

    def test_uydurma_belirtec_reddedilir(self):
        self.assertEqual(self.come_back("tok-uydurma"), "/paketler?odeme=basarisiz")
        self.assertEqual(self.come_back(""), "/paketler?odeme=basarisiz")

    # ---------- Aylık abonelik ----------

    def subscribe(self, email):
        reply = self.buy(email, "pro", telefon="0532 111 22 33")
        token = urllib.parse.unquote(reply["odeme_url"].split("t=")[1])
        return reply, token

    def post(self, path, body):
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            return json.loads(urllib.request.urlopen(request).read())
        except urllib.error.HTTPError as error:
            return {"status": error.code, **json.loads(error.read())}

    def test_aylik_paket_abonelik_formu_acar(self):
        reply, token = self.subscribe("abone1@firma.com")
        self.assertTrue(reply["odeme_url"].startswith("/odeme-form?t="))
        sent = subs[token]["request"]
        self.assertEqual((sent["pricingPlanReferenceCode"], sent["subscriptionInitialStatus"], sent["customer"]["gsmNumber"]), ("plan-aylik", "ACTIVE", "+905321112233"))
        page = urllib.request.urlopen(self.url + reply["odeme_url"]).read().decode()
        self.assertIn("iyzico formu", page)
        self.assertIn('id="iyzipay-checkout-form"', page)
        self.assertFalse(uyelik.grants("abone1@firma.com")["pro"])

    def test_aylik_paket_telefonsuz_alinmaz(self):
        self.assertEqual(self.buy("abone2@firma.com", "pro")["status"], 400)
        self.assertEqual(self.buy("abone2@firma.com", "pro", telefon="123")["status"], 400)

    def test_abonelik_baslar_ve_hak_yazilir(self):
        _, token = self.subscribe("abone3@firma.com")
        self.assertTrue(self.come_back(token).startswith("/giris?k="))
        self.assertTrue(uyelik.grants("abone3@firma.com")["pro"])
        self.assertEqual(uyelik.subscription("abone3@firma.com")["durum"], "aktif")
        self.assertEqual(self.come_back(token), "/paketler?odeme=tamam")
        self.assertEqual(self.buy("abone3@firma.com", "pro", telefon="05321112233")["status"], 409)

    def test_baslamayan_abonelik_hak_yazmaz(self):
        _, token = self.subscribe("abone4@firma.com")
        subs[token]["status"] = "PENDING"
        self.assertEqual(self.come_back(token), "/paketler?odeme=basarisiz")
        self.assertFalse(uyelik.grants("abone4@firma.com")["pro"])

    def test_yenilenen_donem_sureyi_uzatir(self):
        import time
        _, token = self.subscribe("abone5@firma.com")
        self.come_back(token)
        first = uyelik.grants("abone5@firma.com")["pro_until"]
        # Bir ay geçmiş, iyzico ikinci dönemi tahsil etmiş olsun: süre bitmek üzere ve son sorgu eski.
        with uyelik._db() as db:
            db.execute("UPDATE uyeler SET pro_bitis = ?, abonelik_bakildi = 0 WHERE eposta = ?", (time.time() + 3600, "abone5@firma.com"))
        end = int((time.time() + 30 * 86400) * 1000)
        subs[token]["orders"].append({"referenceCode": "donem-2-abone5", "orderStatus": "SUCCESS", "startPeriod": end - 30 * 86400000, "endPeriod": end})
        self.assertEqual(server.session("abone5@firma.com")["abonelik"], "aktif")
        self.assertGreater(uyelik.grants("abone5@firma.com")["pro_until"], time.time() + 29 * 86400)
        purchases = [item for item in uyelik.overview()["satin_almalar"] if item["eposta"] == "abone5@firma.com"]
        self.assertEqual(len(purchases), 2)
        self.assertIsNotNone(first)

    def test_odenmeyen_abonelik_biter(self):
        import time
        _, token = self.subscribe("abone6@firma.com")
        self.come_back(token)
        with uyelik._db() as db:
            db.execute("UPDATE uyeler SET pro_bitis = ?, abonelik_bakildi = 0 WHERE eposta = ?", (time.time() - 3 * 86400, "abone6@firma.com"))
        subs[token]["status"] = "UNPAID"
        subs[token]["orders"] = [{"referenceCode": "eski", "orderStatus": "SUCCESS", "startPeriod": 0, "endPeriod": int((time.time() - 4 * 86400) * 1000)},
                                 {"referenceCode": "yeni", "orderStatus": "FAILED", "startPeriod": 0, "endPeriod": int((time.time() + 26 * 86400) * 1000)}]
        self.assertEqual(server.session("abone6@firma.com")["abonelik"], "bitti")
        self.assertFalse(uyelik.grants("abone6@firma.com")["pro"])

    def test_iptal_edilen_abonelik_donem_sonuna_kadar_surer(self):
        _, token = self.subscribe("abone7@firma.com")
        self.come_back(token)
        session = server.session("abone7@firma.com")
        self.assertEqual(self.post("/api/abonelik-iptal", {"t": "sahte.belirtec"})["status"], 401)
        reply = self.post("/api/abonelik-iptal", {"t": session["token"]})
        self.assertEqual(reply["abonelik"], "iptal")
        self.assertEqual(subs[token]["status"], "CANCELED")
        self.assertTrue(uyelik.grants("abone7@firma.com")["pro"])
        self.assertEqual(self.post("/api/abonelik-iptal", {"t": session["token"]})["status"], 400)

    def test_telefon_bicimi(self):
        self.assertEqual(odeme.phone("0532 111 22 33"), "+905321112233")
        self.assertEqual(odeme.phone("+90 532 111 22 33"), "+905321112233")
        self.assertEqual(odeme.phone("5321112233"), "+905321112233")
        self.assertIsNone(odeme.phone("0212 111 22 33"))
        self.assertIsNone(odeme.phone(""))

    def test_fatura_bilgisi_zorunlu(self):
        reply = self.buy("eksik-fatura@firma.com", adres=" ")
        self.assertEqual(reply["status"], 400)

    def test_sayfa_gercek_odeme_modunu_bildirir(self):
        self.assertIn('data-odeme="gercek"', urllib.request.urlopen(self.url + "/paketler").read().decode())
        self.assertEqual(urllib.request.urlopen(self.url + "/ekip").status, 200)


if __name__ == "__main__":
    unittest.main()
