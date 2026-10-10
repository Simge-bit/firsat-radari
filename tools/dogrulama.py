"""Sitenin doğruluğunu ölçer ve sonucu cikti/dogrulama.json dosyasına yazar.

Kullanım: python3 tools/dogrulama.py [ayna] [sinama]      (parametresiz: ikisi de)

  ayna   : Raporlardaki "Türkiye'den ithalat" rakamı (alıcı ülkenin bildirimi) ile Türkiye'nin aynı ülkeye bildirdiği
           ihracat karşılaştırılır. İki bağımsız bildirim birbirini tutuyorsa rakamlar doğru okunuyor demektir.
           Alıcı rakamı navlun ve sigortayı içerdiği için (CIF) genellikle yüzde 5-10 yüksektir.
  sinama : Geçmişe dönük sınama. Rapor yalnızca 2021 sonuna kadarki veriyle kurulur, sonra 2021'den bugüne gerçekte ne
           olduğuna bakılır: skoru yüksek çıkan pazarlar daha mı çok büyüdü, Türkiye'nin ihracatı oralarda daha mı çok arttı?

Her ürün için birkaç Comtrade çağrısı yapar (günlük sınır 500); sonuçlar önbelleğe alınır.
"""

import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rapor  # noqa: E402
from radar import comtrade  # noqa: E402

OUT_FILE = Path(__file__).resolve().parent.parent / "cikti" / "dogrulama.json"
MIRROR_PRODUCTS = ["080222", "570242", "251512", "040900", "200570", "330499"]
# 2017 ve 2022 sınıflandırmalarında kodu değişmeyen ürünler (kodu değişen üründe eski yıllar karşılaştırılamaz).
BACKTEST_PRODUCTS = ["080222", "570242", "251512", "040900", "200570", "330499", "020714", "870323", "392321", "252329", "220421", "300490"]
# İkinci grup: Türkiye'nin başlıca ihraç ürünlerinden, kodu yine değişmemiş olanlar.
MORE_PRODUCTS = ["190219", "110100", "190531", "180690", "200290", "081310", "080620", "610910", "630260", "721420", "841810", "870899",
                 "940360", "680221", "711319", "401110", "070200", "080510", "151219", "170490", "620342", "520942", "730890", "845011",
                 "851660", "691010", "700529", "732111", "330590", "392062"]
PERIODS, HORIZON, TOP = [2021, 2019], 4, 10
SAMPLES_FILE = OUT_FILE.with_name("sinama_veri.json")


def ranks(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    result, i = [0.0] * len(values), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            result[order[k]] = (i + j) / 2
        i = j + 1
    return result


def spearman(xs, ys):
    """Sıra korelasyonu: +1 aynı sıra, 0 ilişkisiz, -1 ters sıra."""
    if len(xs) < 5:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    spread = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / spread if spread else None


def turkiye_exports(hs6, year):
    """Türkiye'nin bildirdiği ihracat, alıcı ülkeye göre: {ülke kodu: USD}."""
    rows = comtrade._query(reporterCode=comtrade.TURKIYE, flowCode="X", cmdCode=hs6, period=year)
    totals = {}
    for row in rows:
        totals[row["partnerCode"]] = max(totals.get(row["partnerCode"], 0), row.get("primaryValue") or 0)
    return totals


def mirror():
    pairs, per_product = [], []
    for hs6 in MIRROR_PRODUCTS:
        rows = rapor.build(hs6)["rows"]
        exports = {year: turkiye_exports(hs6, year) for year in {row["year"] for row in rows}}
        ours = theirs = 0.0
        for row in rows:
            reported_import = row["imports"] * row["tr_share"]
            reported_export = exports[row["year"]].get(row["code"], 0)
            if reported_import >= 500_000 and reported_export > 0:
                pairs.append((hs6, row["iso2"], reported_import / reported_export, reported_import))
                ours += reported_import
                theirs += reported_export
        per_product.append({"urun": hs6, "alici_bildirimi": ours, "turkiye_bildirimi": theirs, "oran": ours / theirs if theirs else None})
    ratios = sorted(ratio for _, _, ratio, _ in pairs)
    within = lambda tolerance: sum(1 / (1 + tolerance) <= ratio <= 1 + tolerance for ratio in ratios) / len(ratios)  # noqa: E731
    return {"cift_sayisi": len(pairs), "ortanca_oran": statistics.median(ratios), "yuzde25_icinde": within(0.25), "yuzde50_icinde": within(0.50),
            "urunler": per_product,
            "en_uyumsuz": [{"urun": hs6, "ulke": iso2, "oran": ratio, "tutar": value}
                           for hs6, iso2, ratio, value in sorted(pairs, key=lambda pair: -abs(math.log(pair[2])) * math.sqrt(pair[3]))[:8]]}


def backtest_one(hs6, as_of):
    """Tek ürün ve tek dönem: as_of yılının verisiyle skor, HORIZON yıl sonraki gerçek sonuç. Veri yetersizse None."""
    past = rapor.build(hs6, as_of=as_of)
    if past["t0"] != as_of or len(past["rows"]) < 15:
        return None
    later = {row["code"]: row for row in rapor.build(hs6, as_of=as_of + HORIZON)["rows"]}
    sample = [row for row in past["rows"] if row["code"] in later and not row.get("blocked")]
    if len(sample) < 15:
        return None
    return {"urun": hs6, "donem": as_of, "satirlar": [
        {"ulke": row["iso2"], "skor": row["score"], "z": row["z"], "ithalat": row["imports"], "gecmis_buyume": row["G_raw"],
         "pazar_buyumesi": math.log(later[row["code"]]["imports"] / row["imports"]),
         "turkiye_kazanci": later[row["code"]]["imports"] * later[row["code"]]["tr_share"] - row["imports"] * row["tr_share"],
         "pay_degisimi": later[row["code"]]["tr_share"] - row["tr_share"]} for row in sample]}


def backtest(products, periods, stop_at):
    """Sınamayı yürütür; her adımdan sonra kaydeder. Günlük çağrı sayısı stop_at'e ulaşınca durur, sonra kaldığı yerden sürer."""
    samples = json.loads(SAMPLES_FILE.read_text()) if SAMPLES_FILE.exists() else {}
    for as_of in periods:
        for hs6 in products:
            key = f"{hs6}-{as_of}"
            if key in samples:
                continue
            if comtrade.calls_today() >= stop_at:
                print("günlük çağrı sınırına yaklaşıldı, duruldu:", comtrade.calls_today())
                return samples
            try:
                samples[key] = backtest_one(hs6, as_of)
            except (RuntimeError, ValueError) as error:
                print(key, "atlandı:", str(error)[:90])
                if "bütçe" in str(error) or "yanıt vermedi" in str(error):
                    return samples
                samples[key] = None
            SAMPLES_FILE.write_text(json.dumps(samples))
            print(key, "tamam" if samples[key] else "veri yetersiz", "| çağrı:", comtrade.calls_today())
    return samples


if __name__ == "__main__":
    wanted = sys.argv[1:] or ["ayna", "sinama"]
    OUT_FILE.parent.mkdir(exist_ok=True)
    report = json.loads(OUT_FILE.read_text()) if OUT_FILE.exists() else {}
    if "ayna" in wanted:
        report["ayna"] = mirror()
    if "sinama" in wanted:
        samples = backtest(BACKTEST_PRODUCTS + MORE_PRODUCTS, PERIODS, stop_at=440)
        print(sum(1 for sample in samples.values() if sample), "geçerli örnek /", len(samples), "denenen")
    OUT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("yazıldı:", OUT_FILE)
