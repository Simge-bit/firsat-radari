"""Kalıcı uzak veritabanı (Turso), protokolünü taklit eden yerel bir sunucuya karşı. Çalıştırma: python3 -m unittest discover tests"""

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("IHRACBUL_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

import uyelik  # noqa: E402

TOKEN = "deneme-belirteci"
store = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
lock = threading.Lock()
seen = {"requests": 0}


class FakeTurso(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen["requests"] += 1
        results = []
        if self.path != "/v2/pipeline" or self.headers.get("Authorization") != "Bearer " + TOKEN:
            self.send_response(401)
            self.end_headers()
            return
        for request in body["requests"]:
            if request["type"] == "close":
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            args = [None if arg["type"] == "null" else int(arg["value"]) if arg["type"] == "integer" else arg["value"] for arg in request["stmt"]["args"]]
            try:
                with lock:
                    cursor = store.execute(request["stmt"]["sql"], args)
                    rows = cursor.fetchall()
                cell = lambda value: ({"type": "null"} if value is None else {"type": "integer", "value": str(value)} if isinstance(value, int)
                                      else {"type": "float", "value": value} if isinstance(value, float) else {"type": "text", "value": value})
                results.append({"type": "ok", "response": {"type": "execute", "result": {
                    "cols": [], "rows": [[cell(value) for value in row] for row in rows], "affected_row_count": max(cursor.rowcount, 0)}}})
            except sqlite3.Error as error:
                results.append({"type": "error", "error": {"message": str(error)}})
        data = json.dumps({"baton": None, "results": results}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class UzakVeritabani(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = ThreadingHTTPServer(("127.0.0.1", 0), FakeTurso)
        threading.Thread(target=cls.service.serve_forever, daemon=True).start()
        os.environ.update(TURSO_URL=f"http://127.0.0.1:{cls.service.server_port}", TURSO_TOKEN=TOKEN)

    @classmethod
    def tearDownClass(cls):
        del os.environ["TURSO_URL"], os.environ["TURSO_TOKEN"]
        cls.service.shutdown()

    def test_kalici_sayilir(self):
        self.assertTrue(uyelik.persistent())

    def test_kayit_giris_ve_profil(self):
        self.assertEqual(uyelik.register("uzak@firma.com", "Ayşe Yılmaz", "Yılmaz Gıda", "uzak-sifre-1"), "tamam")
        self.assertEqual(uyelik.register("uzak@firma.com", "Başkası", "", "baska-sifre-1"), "var")
        self.assertTrue(uyelik.check_password("uzak@firma.com", "uzak-sifre-1"))
        self.assertFalse(uyelik.check_password("uzak@firma.com", "baska-sifre-1"))
        self.assertEqual(uyelik.profile("uzak@firma.com"), {"ad": "Ayşe Yılmaz", "firma": "Yılmaz Gıda", "sifre_var": True})

    def test_satin_alma_ve_haklar(self):
        uyelik.record_purchase("alan@firma.com", "single", "570242", 490, "demo")
        uyelik.record_purchase("alan@firma.com", "yearly", None, 9000, "demo")
        grant = uyelik.grants("alan@firma.com")
        self.assertEqual(grant["reports"], ["570242"])
        self.assertTrue(grant["pro"])
        self.assertIsInstance(grant["pro_until"], float)

    def test_giris_kodu_tek_kullanimlik(self):
        code = uyelik.login_code("kod@firma.com")
        self.assertEqual(uyelik.redeem(code), "kod@firma.com")
        self.assertIsNone(uyelik.redeem(code))
        self.assertIsNone(uyelik.redeem("uydurma"))

    def test_siparis_bir_kez_kapanir(self):
        order = uyelik.open_order("siparis@firma.com", "pro", None, 999)
        uyelik.tag_order(order, "tok-1")
        self.assertEqual(uyelik.find_order("tok-1")["email"], "siparis@firma.com")
        self.assertTrue(uyelik.close_order(order, "iyzico", "777"))
        self.assertFalse(uyelik.close_order(order, "iyzico", "777"))

    def test_yerel_dosyaya_yazilmaz(self):
        uyelik.register("yalniz-uzak@firma.com", "A B", "", "sifre-123456")
        local = sqlite3.connect(os.environ["IHRACBUL_DB"])
        tables = {row[0] for row in local.execute("SELECT name FROM sqlite_master")}
        found = local.execute("SELECT 1 FROM uyeler WHERE eposta = 'yalniz-uzak@firma.com'").fetchone() if "uyeler" in tables else None
        self.assertIsNone(found)

    def test_yanlis_belirtec_hata_verir(self):
        os.environ["TURSO_TOKEN"] = "yanlis"
        try:
            with self.assertRaises(RuntimeError):
                uyelik.grants("kim@firma.com")
        finally:
            os.environ["TURSO_TOKEN"] = TOKEN


if __name__ == "__main__":
    unittest.main()
