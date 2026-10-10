"""Veri dosyalarının bütünlüğü ve arama isabeti. Çalıştırma: python3 -m unittest discover tests"""

import json
import re
import unittest
from pathlib import Path

from radar import urunler

DATA = Path(__file__).resolve().parent.parent / "data"
load = lambda name: json.loads((DATA / name).read_text(encoding="utf-8"))  # noqa: E731

# Günlük ürün adı -> beklenen 4 haneli pozisyonlar.
SEARCHES = {
    "fındık": ["0802"], "ceviz": ["0802"], "antep fıstığı": ["0802"], "zeytinyağı": ["1509"], "halı": ["5701", "5702", "5703"],
    "mermer": ["2515", "6802"], "bal": ["0409"], "domates": ["0702"], "limon": ["0805"], "portakal": ["0805"], "elma": ["0808"],
    "kuru kayısı": ["0813"], "kuru üzüm": ["0806"], "kuru incir": ["0804"], "nohut": ["0713"], "mercimek": ["0713"],
    "makarna": ["1902"], "bisküvi": ["1905"], "çikolata": ["1806"], "buğday unu": ["1101"], "ayçiçek yağı": ["1512"],
    "salça": ["2002"], "zeytin": ["2005", "0711", "0709"], "meyve suyu": ["2009"], "çay": ["0902"], "kahve": ["0901"],
    "şeker": ["1701"], "tavuk eti": ["0207"], "yumurta": ["0407"], "peynir": ["0406"], "çimento": ["2523"],
    "inşaat demiri": ["7214", "7213"], "alüminyum profil": ["7604"], "seramik karo": ["6907"], "buzdolabı": ["8418"],
    "çamaşır makinesi": ["8450"], "televizyon": ["8528"], "otomobil": ["8703"], "lastik": ["4011"], "tişört": ["6109"],
    "kot pantolon": ["6203", "6204"], "çorap": ["6115"], "havlu": ["6302"], "pamuk ipliği": ["5205", "5206", "5207"],
    "ayakkabı": ["6401", "6402", "6403", "6404", "6405"], "mobilya": ["9403"], "koltuk": ["9401"], "oyuncak": ["9503"],
    "sabun": ["3401"], "deterjan": ["3402"], "şampuan": ["3305"], "parfüm": ["3303"], "ilaç": ["3004", "3003"],
    "plastik boru": ["3917"], "kablo": ["8544"], "traktör": ["8701"], "gübre": ["3102", "3103", "3104", "3105"],
    "altın takı": ["7113"], "cam": ["7003", "7004", "7005", "7007", "7013", "7010"], "kağıt": ["4801", "4802", "4810", "4818"],
}


class Dosyalar(unittest.TestCase):
    def test_urun_sozlugu_tam(self):
        self.assertGreater(len(load("urunler.json")), 5800)

    def test_musavirlik_epostalari_kurumsal(self):
        offices = load("musavirlikler.json")
        self.assertGreater(len(offices), 90)
        for iso2, items in offices.items():
            self.assertRegex(iso2, r"^[A-Z]{2}$")
            for office in items:
                self.assertRegex(office["eposta"], r"^[\w.\-]+@ticaret\.gov\.tr$")
                self.assertTrue(office["sehir"])

    def test_buyuk_pazarlarda_musavirlik_var(self):
        offices = load("musavirlikler.json")
        for iso2 in ("DE", "FR", "GB", "US", "IT", "NL", "RU", "CN", "SA", "AE"):
            self.assertIn(iso2, offices)

    def test_fuar_tarihleri_gecerli(self):
        fairs = [fair for items in load("fuarlar.json").values() for fair in items]
        self.assertGreater(len(fairs), 1500)
        dated = [fair for fair in fairs if re.fullmatch(r"\d{4}-\d{2}-\d{2}", fair["baslangic"])]
        self.assertGreater(len(dated) / len(fairs), 0.99)
        self.assertTrue(all(fair["bitis"] >= fair["baslangic"] for fair in dated))

    def test_eski_ulke_kodu_kalmamis(self):
        for name in ("fuarlar.json", "musavirlikler.json"):
            self.assertFalse(set(load(name)) & {"FX", "YU", "SU", "DY", "HV", "UK", "DD"})

    def test_kisitlamalarin_hepsi_cevrilmis(self):
        entries = load("kisitlamalar.json")
        self.assertGreater(len(entries), 500)
        for entry in entries:
            self.assertTrue(entry["metin_tr"] and entry["kodlar"] and entry["tur"])
            self.assertNotIn("—", entry["metin_tr"])

    def test_konumlar(self):
        points = load("konumlar.json")
        self.assertGreater(len(points), 200)
        self.assertIn("TR", points)
        self.assertTrue(all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in points.values()))


class Arama(unittest.TestCase):
    def hits(self, depth):
        return [name for name, headings in SEARCHES.items()
                if any(result["hs6"][:4] in headings for result in urunler.search(name, limit=8)[:depth])]

    def test_ilk_sonuc_isabeti(self):
        found = self.hits(1)
        self.assertGreaterEqual(len(found) / len(SEARCHES), 0.80, sorted(set(SEARCHES) - set(found)))

    def test_ilk_uc_sonuc_isabeti(self):
        found = self.hits(3)
        self.assertGreaterEqual(len(found) / len(SEARCHES), 0.90, sorted(set(SEARCHES) - set(found)))

    def test_yazim_hatasi_tolere_edilir(self):
        for typo, heading in (("findik", "0802"),("zeytinyagi", "1509"), ("buzdolabi", "8418"), ("çikolta", "1806")):
            self.assertTrue(any(result["hs6"][:4] == heading for result in urunler.search(typo, limit=8)[:3]), typo)

    def test_anlamsiz_sorgu_hata_vermez(self):
        for query in ("", "   ", "xqzw", "123", "!!!", "a" * 300):
            self.assertIsInstance(urunler.search(query), list)


if __name__ == "__main__":
    unittest.main()
