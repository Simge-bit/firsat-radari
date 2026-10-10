"""Hesapların doğruluğu: sonucu elle bilinen örnekler. Çalıştırma: python3 -m unittest discover tests"""

import math
import unittest

from radar import giris, model, sartlar, tarife


class Buyume(unittest.TestCase):
    def test_sabit_oranli_seri_orani_verir(self):
        series = {2021 + i: 100 * 1.10 ** i for i in range(5)}
        self.assertAlmostEqual(model.growth(series), 0.10, places=9)

    def test_azalan_seri_negatif_oran_verir(self):
        series = {2021 + i: 200 * 0.80 ** i for i in range(5)}
        self.assertAlmostEqual(model.growth(series), -0.20, places=9)

    def test_duz_seri_sifir_verir(self):
        self.assertAlmostEqual(model.growth({year: 50 for year in range(2021, 2026)}), 0.0, places=9)

    def test_uc_yildan_az_veri_hesaplanmaz(self):
        self.assertIsNone(model.growth({2024: 10, 2025: 20}))

    def test_sifir_degerli_yillar_atlanir(self):
        self.assertAlmostEqual(model.growth({2021: 100, 2022: 0, 2023: 121, 2024: 0, 2025: 146.41}), 0.10, places=6)

    def test_tek_yillik_sicrama_egilimi_ele_gecirmez(self):
        steady = model.growth({2021: 100, 2022: 100, 2023: 100, 2024: 100, 2025: 100})
        spike = model.growth({2021: 100, 2022: 100, 2023: 300, 2024: 100, 2025: 100})
        self.assertAlmostEqual(spike, steady, places=9)      # ortadaki sıçrama eğimi değiştirmez


class Guven(unittest.TestCase):
    def test_tam_ve_guncel_veri_bir_verir(self):
        self.assertAlmostEqual(model.confidence({year: 1 for year in range(2021, 2026)}, 2025), 1.0)

    def test_eksik_yil_guveni_orantili_dusurur(self):
        self.assertAlmostEqual(model.confidence({2023: 1, 2024: 1, 2025: 1}, 2025), 0.6)

    def test_eski_veri_guveni_dusurur(self):
        self.assertAlmostEqual(model.confidence({2021: 1, 2022: 1, 2023: 1}, 2025), 0.6 * math.exp(-0.5))

    def test_veri_yoksa_sifir(self):
        self.assertEqual(model.confidence({}, 2025), 0.0)


class Yogunlasma(unittest.TestCase):
    def test_tek_tedarikci_bir(self):
        self.assertAlmostEqual(model.hhi([1.0]), 1.0)

    def test_dort_esit_tedarikci_ceyrek(self):
        self.assertAlmostEqual(model.hhi([0.25] * 4), 0.25)


class Olcekleme(unittest.TestCase):
    def test_sonuc_sifir_bir_arasinda(self):
        values = model.normalize([3, 9, 1, 7, 5, 100, -50])
        self.assertTrue(all(0 <= value <= 1 for value in values))

    def test_sira_korunur(self):
        raw = [5, 1, 9, 3, 7]
        scaled = model.normalize(raw)
        self.assertEqual(sorted(range(5), key=raw.__getitem__), sorted(range(5), key=scaled.__getitem__))

    def test_uc_deger_sonucu_ele_gecirmez(self):
        normal = list(range(1, 21))
        with_outlier = normal[:-1] + [10_000]
        self.assertAlmostEqual(model.normalize(normal)[9], model.normalize(with_outlier)[9], places=9)

    def test_hepsi_ayni_ise_orta_deger(self):
        self.assertEqual(model.normalize([4, 4, 4]), [0.5, 0.5, 0.5])


class Skor(unittest.TestCase):
    def rows(self):
        return [{"G": g, "A": a, "H": h, "F": f} for g, a, h, f in
                [(0.30, 20, 0.9, 0.8), (0.05, 18, 0.5, 0.6), (-0.10, 15, 0.2, 0.3), (0.10, 17, 0.7, 0.5)]]

    def test_her_olcude_en_iyi_olan_yuz_alir(self):
        best = model.score(self.rows())[0]
        self.assertAlmostEqual(best["score"], 100.0, places=6)
        self.assertEqual(best["G"], 0.30)

    def test_her_olcude_en_kotu_olan_sifir_alir(self):
        worst = model.score(self.rows())[-1]
        self.assertAlmostEqual(worst["score"], 0.0, places=6)

    def test_sirali_doner(self):
        scores = [row["score"] for row in model.score(self.rows())]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_agirliklar_bire_tamamlanir(self):
        self.assertAlmostEqual(sum(model.WEIGHTS.values()), 1.0)

    def test_eksik_olcunun_agirligi_dagitilir(self):
        rows = model.score([{"G": 1, "A": 1}, {"G": 0, "A": 0}])
        self.assertAlmostEqual(rows[0]["score"], 100.0)
        self.assertEqual(set(rows[0]["z"]), {"G", "A"})

    def test_bos_liste(self):
        self.assertEqual(model.score([]), [])


class BuyumeDuzeltmesi(unittest.TestCase):
    def test_buyuk_ve_ic_talepli_pazar_ham_orana_yakin_kalir(self):
        rows = [{"G_raw": 0.20, "imports": 1e9, "reexport": 0.0}, {"G_raw": 0.0, "imports": 1e9, "reexport": 0.0},
                {"G_raw": 0.05, "imports": 1e9, "reexport": 0.0}]
        model.adjust_growth(rows, 1e6)
        self.assertAlmostEqual(rows[0]["G"], 0.20, delta=0.002)

    def test_kucuk_pazarin_sicramasi_ortancaya_cekilir(self):
        rows = [{"G_raw": 3.0, "imports": 1e6, "reexport": 0.0}, {"G_raw": 0.0, "imports": 1e9, "reexport": 0.0},
                {"G_raw": 0.05, "imports": 1e9, "reexport": 0.0}]
        model.adjust_growth(rows, 1e6)
        self.assertLess(rows[0]["G"], 0.12)                  # ham oran %300, tavan %40, güven 1/6

    def test_aktarma_merkezinde_buyume_sayilmaz(self):
        rows = [{"G_raw": 0.30, "imports": 1e9, "reexport": 1.0}, {"G_raw": 0.02, "imports": 1e9, "reexport": 0.0},
                {"G_raw": 0.04, "imports": 1e9, "reexport": 0.0}]
        model.adjust_growth(rows, 1e6)
        self.assertAlmostEqual(rows[0]["G"], 0.04, places=6)  # tamamen ortancaya çekilir

    def test_oran_tavan_ve_tabana_kirpilir(self):
        rows = [{"G_raw": 5.0, "imports": 1e12, "reexport": 0.0}, {"G_raw": -0.9, "imports": 1e12, "reexport": 0.0},
                {"G_raw": 0.0, "imports": 1e12, "reexport": 0.0}]
        model.adjust_growth(rows, 1e6)
        self.assertAlmostEqual(rows[0]["G"], model.G_CAP[1], delta=1e-4)
        self.assertAlmostEqual(rows[1]["G"], model.G_CAP[0], delta=1e-4)


class Uzaklik(unittest.TestCase):
    def test_bilinen_uzakliklar(self):
        for iso2, km in (("DE", 2300), ("GB", 3200), ("US", 10000), ("BG", 850)):
            self.assertAlmostEqual(giris.distance_km(iso2), km, delta=km * 0.08)

    def test_turkiye_kendine_sifir(self):
        self.assertAlmostEqual(giris.distance_km("TR"), 0, delta=1)

    def test_bilinmeyen_ulke(self):
        self.assertIsNone(giris.distance_km("XX"))


class Vergi(unittest.TestCase):
    def test_anlasmali_oran_varsa_o_gecerli(self):
        self.assertEqual(tarife.applied({"mfn": 8.0, "tr": 0.0}), 0.0)

    def test_anlasma_yoksa_genel_oran(self):
        self.assertEqual(tarife.applied({"mfn": 8.0, "tr": None}), 8.0)


    def test_vergi_puani_mutlak_olcekte(self):
        self.assertEqual(model.tariff_score(0), 1.0)
        self.assertAlmostEqual(model.tariff_score(3), 0.9)
        self.assertEqual(model.tariff_score(30), 0.0)
        self.assertEqual(model.tariff_score(60), 0.0)

    def test_dusuk_vergi_cogunluk_ayni_orandayken_sifir_puan_almaz(self):
        rows = [{"T": model.tariff_score(3.0), "A": i} for i in range(25)] + [{"T": model.tariff_score(0.0), "A": 30}, {"T": model.tariff_score(40.0), "A": 31}]
        scored = model.score(rows)
        self.assertTrue(all(row["z"]["T"] == 0.9 for row in scored if row["A"] < 25))


class Sartlar(unittest.TestCase):
    def test_israil_ticaret_durdu_listesinde(self):
        self.assertIn("IL", sartlar.TICARET_DURDU)

    def test_gida_disi_urune_gida_kurali_cikmaz(self):
        titles = " ".join(rule["baslik"] for rule in sartlar.checklist("570242", "DE")).lower()
        self.assertNotIn("bitki sağlık", titles)

    def test_her_kuralin_kaynagi_var(self):
        for hs6, iso2 in (("080222", "DE"), ("570242", "US"), ("330499", "SA"), ("870899", "GB")):
            for rule in sartlar.checklist(hs6, iso2):
                self.assertTrue(rule["url"].startswith("http") and rule["kurum"] and rule["metin"])


if __name__ == "__main__":
    unittest.main()
