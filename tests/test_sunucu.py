"""Erişim kilidi ve üyelik: belirteç, kilitli veri, satın alma ve giriş. Çalıştırma: python3 -m unittest discover tests"""

import base64
import json
import os
import tempfile
import time
import unittest

os.environ["IHRACBUL_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["IHRACBUL_SECRET"] = "test-anahtari"

import server  # noqa: E402
import uyelik  # noqa: E402

ROW = {"code": 528, "country": "Netherlands", "iso2": "NL", "year": 2025, "imports": 100.0, "G_raw": 0.1, "tr_share": 0.25, "score": 90.0,
       "kappa": 1.0, "series": [[2024, 90], [2025, 100]], "reexport": 0.1, "blocked": False, "z": {"A": 1}, "rivals": [{"country": "X"}],
       "offices": [{"eposta": "a@ticaret.gov.tr"}], "tariff": {"mfn": 8}, "fairs": [], "requirements": [], "unit_price": 4.2, "restrictions": [{"tur": ["yasak"]}]}
FULL = json.dumps({"hs6": "570242", "t0": 2025, "rows": [ROW, {**ROW, "country": "Denmark", "iso2": "DK", "imports": 50.0, "tr_share": 0.1}]}).encode()


class Belirtec(unittest.TestCase):
    def test_imzali_belirtec_okunur(self):
        grant = server.read_token(server.sign({"email": "a@b.com", "pro": True, "pro_until": time.time() + 60, "reports": ["570242"]}))
        self.assertEqual((grant["email"], grant["pro"], grant["reports"]), ("a@b.com", True, ["570242"]))

    def test_belirtecsiz_haksiz(self):
        for token in ("", "abc", "abc.def", None):
            self.assertEqual(server.read_token(token)["pro"], False)
            self.assertEqual(server.read_token(token)["reports"], [])

    def test_oynanmis_belirtec_reddedilir(self):
        body, mark = server.sign({"email": "a@b.com", "pro": False, "pro_until": 0, "reports": []}).split(".")
        forged = base64.urlsafe_b64encode(json.dumps({"email": "a@b.com", "pro": True, "pro_until": 9e12, "reports": ["570242"]}).encode()).decode().rstrip("=")
        grant = server.read_token(forged + "." + mark)
        self.assertFalse(grant["pro"])
        self.assertEqual(grant["reports"], [])

    def test_suresi_dolan_pro_gecersiz(self):
        self.assertFalse(server.read_token(server.sign({"email": "a@b.com", "pro": True, "pro_until": time.time() - 1, "reports": []}))["pro"])

    def test_baska_anahtarla_imzalanan_reddedilir(self):
        token = server.sign({"email": "a@b.com", "pro": True, "pro_until": time.time() + 60, "reports": []})
        os.environ["IHRACBUL_SECRET"] = "baska"
        try:
            self.assertFalse(server.read_token(token)["pro"])
        finally:
            os.environ["IHRACBUL_SECRET"] = "test-anahtari"


class KilitliVeri(unittest.TestCase):
    def setUp(self):
        self.locked = json.loads(server.locked(FULL))

    def test_yalnizca_birinci_pazar_gider(self):
        self.assertEqual(len(self.locked["rows"]), 1)
        self.assertEqual(self.locked["pazar_sayisi"], 2)
        self.assertNotIn("Denmark", json.dumps(self.locked))

    def test_ulke_detayi_gitmez(self):
        for field in ("rivals", "offices", "tariff", "fairs", "requirements", "unit_price"):
            self.assertNotIn(field, self.locked["rows"][0])
        self.assertEqual(self.locked["rows"][0]["restrictions"], [])

    def test_toplamlar_sunucuda_hesaplanir(self):
        self.assertAlmostEqual(self.locked["ozet"]["toplam"], 150.0)
        self.assertAlmostEqual(self.locked["ozet"]["turkiye"], 30.0)
        self.assertTrue(self.locked["kilitli"])


class Uyelik(unittest.TestCase):
    def test_eposta_dogrulama(self):
        self.assertEqual(uyelik.normalize("  Ad.Soyad@Firma.COM "), "ad.soyad@firma.com")
        for bad in ("", "ad", "ad@", "@firma.com", "ad@firma", "ad soyad@firma.com", None, "a" * 300 + "@b.com"):
            self.assertIsNone(uyelik.normalize(bad))

    def test_tek_rapor_yalnizca_o_urunu_acar(self):
        grant = uyelik.record_purchase("tek@ornek.com", "single", "570242", 490, "demo")
        self.assertEqual((grant["pro"], grant["reports"]), (False, ["570242"]))

    def test_yillik_pro_bir_yil_surer(self):
        grant = uyelik.record_purchase("yil@ornek.com", "yearly", None, 9000, "demo")
        self.assertTrue(grant["pro"])
        self.assertAlmostEqual((grant["pro_until"] - time.time()) / 86400, 366, delta=0.01)

    def test_yenileme_kalan_sureye_eklenir(self):
        uyelik.record_purchase("ay@ornek.com", "pro", None, 999, "demo")
        grant = uyelik.record_purchase("ay@ornek.com", "pro", None, 999, "demo")
        self.assertAlmostEqual((grant["pro_until"] - time.time()) / 86400, 62, delta=0.01)

    def test_giris_kodu_tek_kullanimlik(self):
        code = uyelik.login_code("giris@ornek.com")
        self.assertEqual(uyelik.redeem(code), "giris@ornek.com")
        self.assertIsNone(uyelik.redeem(code))
        self.assertIsNone(uyelik.redeem("uydurma"))

    def test_oturum_belirteci_haklari_tasir(self):
        uyelik.record_purchase("oturum@ornek.com", "single", "080222", 490, "demo")
        grant = server.read_token(server.session("oturum@ornek.com")["token"])
        self.assertEqual((grant["email"], grant["reports"]), ("oturum@ornek.com", ["080222"]))

    def test_giris_istegi_sinirlanir(self):
        key = ("eposta", "sinir@ornek.com")
        results = [server.throttled(key) for _ in range(server.LOGIN_PER_HOUR["eposta"] + 1)]
        self.assertEqual(results, [False] * server.LOGIN_PER_HOUR["eposta"] + [True])

    def test_fiyatlar_sayfayla_ayni(self):
        script = (server.WEB / "app.js").read_text(encoding="utf-8")
        for kind, amount in server.PRICES.items():
            self.assertIn(f"{kind}: {amount}", script)


class Hesap(unittest.TestCase):
    def test_kayit_ve_sifreyle_giris(self):
        self.assertEqual(uyelik.register("yeni@firma.com", "Ayşe Yılmaz", "Yılmaz Tekstil", "gizli-sifre-1"), "tamam")
        self.assertTrue(uyelik.check_password("yeni@firma.com", "gizli-sifre-1"))
        self.assertFalse(uyelik.check_password("yeni@firma.com", "yanlis-sifre"))
        self.assertEqual(uyelik.profile("yeni@firma.com"), {"ad": "Ayşe Yılmaz", "firma": "Yılmaz Tekstil", "sifre_var": True})

    def test_sifre_acik_saklanmaz(self):
        uyelik.register("sakli@firma.com", "A B", "", "cok-gizli-sifre")
        with uyelik._db() as db:
            stored = db.execute("SELECT sifre FROM uyeler WHERE eposta = ?", ("sakli@firma.com",)).fetchone()[0]
        self.assertNotIn("cok-gizli-sifre", stored)

    def test_kayitli_adrese_yeniden_kayit_olunamaz(self):
        uyelik.register("tek@firma.com", "A B", "", "ilk-sifre-123")
        self.assertEqual(uyelik.register("tek@firma.com", "Başkası", "", "ikinci-sifre"), "var")
        self.assertTrue(uyelik.check_password("tek@firma.com", "ilk-sifre-123"))

    def test_paket_almis_adres_sifreyle_ele_gecirilemez(self):
        uyelik.record_purchase("alici@firma.com", "yearly", None, 9000, "demo")
        self.assertEqual(uyelik.register("alici@firma.com", "Saldırgan", "", "ele-gecirme-1"), "var")
        self.assertFalse(uyelik.check_password("alici@firma.com", "ele-gecirme-1"))
        self.assertFalse(uyelik.check_password("alici@firma.com", ""))

    def test_giris_yapan_sifre_belirleyebilir(self):
        uyelik.record_purchase("sonra@firma.com", "single", "570242", 490, "demo")
        uyelik.update_profile("sonra@firma.com", password="yeni-sifre-99")
        self.assertTrue(uyelik.check_password("sonra@firma.com", "yeni-sifre-99"))
        self.assertEqual(uyelik.grants("sonra@firma.com")["reports"], ["570242"])

    def test_oturum_ad_ve_firma_tasir(self):
        uyelik.register("oturum@firma.com", "Can Demir", "Demir Gıda", "sifre-12345")
        self.assertEqual((server.session("oturum@firma.com")["ad"], server.session("oturum@firma.com")["firma"]), ("Can Demir", "Demir Gıda"))




class Yonetim(unittest.TestCase):
    def setUp(self):
        os.environ["ADMIN_PASSWORD"] = "yonetim-sifresi"

    def tearDown(self):
        os.environ.pop("ADMIN_PASSWORD", None)

    def test_yonetim_belirteci_gecerli(self):
        self.assertTrue(server.is_admin(server.admin_token()))

    def test_uye_belirteci_yonetici_sayilmaz(self):
        self.assertFalse(server.is_admin(server.sign({"email": "a@b.com", "pro": True, "pro_until": time.time() + 60, "reports": []})))
        self.assertFalse(server.is_admin(""))
        self.assertFalse(server.is_admin("uydurma.belirtec"))

    def test_suresi_dolan_oturum_kapanir(self):
        self.assertFalse(server.is_admin(server.sign({"yonetici": True, "bitis": time.time() - 1})))

    def test_sifre_tanimli_degilse_panel_kapali(self):
        token = server.admin_token()
        del os.environ["ADMIN_PASSWORD"]
        self.assertFalse(server.is_admin(token))

    def test_ozet_sifre_ozeti_icermez(self):
        uyelik.register("panel@firma.com", "Panel Üyesi", "", "panel-sifre-1")
        view = server.admin_view()
        member = next(item for item in view["uyeler"] if item["eposta"] == "panel@firma.com")
        self.assertEqual(set(member), {"eposta", "ad", "firma", "kayit", "pro_bitis", "raporlar", "sifre_var"})
        self.assertNotIn("$", json.dumps(view["uyeler"]))

    def test_pro_bitirme_ve_silme(self):
        uyelik.record_purchase("biten@firma.com", "yearly", None, 0, "yonetim")
        uyelik.end_pro("biten@firma.com")
        self.assertFalse(uyelik.grants("biten@firma.com")["pro"])
        uyelik.delete_member("biten@firma.com")
        self.assertNotIn("biten@firma.com", [item["eposta"] for item in uyelik.overview()["uyeler"]])



class AcikOrnek(unittest.TestCase):
    """Tam raporu herkese açık örnek ürün: belirteçsiz istek de tam veriyi alır, diğer ürünler kilitli kalır."""

    @classmethod
    def setUpClass(cls):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        cls.site = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.get = staticmethod(lambda code: json.loads(urllib.request.urlopen(f"http://127.0.0.1:{cls.site.server_port}/api/rapor?gtip={code}").read()))

    @classmethod
    def tearDownClass(cls):
        cls.site.shutdown()

    def test_acik_ornek_tam_gelir(self):
        report = self.get("080222")
        self.assertNotIn("kilitli", report)
        self.assertGreater(len(report["rows"]), 5)
        self.assertIn("rivals", report["rows"][1])

    def test_diger_ornek_kilitli_kalir(self):
        report = self.get("570242")
        self.assertTrue(report["kilitli"])
        self.assertEqual(len(report["rows"]), 1)

    def post(self, path, body):
        import urllib.error
        import urllib.request
        request = urllib.request.Request(f"http://127.0.0.1:{self.site.server_port}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_profil_ad_ve_sifre_degisir(self):
        uyelik.register("profil@firma.com", "Eski Ad", "Eski Firma", "eski-sifre-12")
        token = server.session("profil@firma.com")["token"]
        status, body = self.post("/api/profil", {"t": token, "ad": "Yeni Ad", "firma": "Yeni Firma"})
        self.assertEqual((status, body["ad"], body["firma"]), (200, "Yeni Ad", "Yeni Firma"))
        self.assertEqual(self.post("/api/profil", {"t": token, "ad": "Yeni Ad", "sifre": "yeni-sifre-12"})[0], 403)
        self.assertEqual(self.post("/api/profil", {"t": token, "ad": "Yeni Ad", "sifre": "yeni-sifre-12", "eski": "yanlis"})[0], 403)
        self.assertTrue(uyelik.check_password("profil@firma.com", "eski-sifre-12"))
        self.assertEqual(self.post("/api/profil", {"t": token, "ad": "Yeni Ad", "sifre": "yeni-sifre-12", "eski": "eski-sifre-12"})[0], 200)
        self.assertTrue(uyelik.check_password("profil@firma.com", "yeni-sifre-12"))
        self.assertEqual(self.post("/api/profil", {"t": token, "ad": "  "})[0], 400)
        self.assertEqual(self.post("/api/profil", {"t": "sahte.belirtec", "ad": "X"})[0], 401)

    def test_acik_ornegin_kesiti_gelir(self):
        import urllib.request
        get = lambda code: json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.site.server_port}/api/ornek?gtip={code}").read())
        self.assertEqual(set(get("080222")["kesit"]), {"pay", "vergi", "rakipler"})
        self.assertNotIn("kesit", get("570242"))

    def test_her_sayfa_acilir(self):
        import urllib.request
        for path in server.PAGES + ["/yonetim", "/giris", "/rapor/080222", "/static/app.css", "/static/yonetim.js", "/robots.txt", "/sitemap.xml"]:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.site.server_port}{path}") as response:
                self.assertEqual(response.status, 200, path)
                self.assertGreater(len(response.read()), 50, path)

    def test_acik_ornekler_sayfayla_ayni(self):
        script = (server.WEB / "app.js").read_text(encoding="utf-8")
        for code in server.OPEN_SAMPLES:
            self.assertRegex(script, r'hs6: "%s"[^}]*open: true' % code)


if __name__ == "__main__":
    unittest.main()
