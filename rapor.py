"""Kullanım: python3 rapor.py <GTİP>   (örnek: python3 rapor.py 5702.42)"""

import argparse
import csv
import datetime
import math
import re
from pathlib import Path

from radar import comtrade, model, urunler

OUT_DIR = Path(__file__).resolve().parent / "cikti"


def hs6_from(gtip):
    digits = re.sub(r"\D", "", gtip)
    if len(digits) < 6:
        raise ValueError("GTİP en az 6 haneli olmalı.")
    # 999999 Comtrade'in "sınıflandırılmamış" kalemidir, ürün değildir.
    if digits[:6] == "999999" or digits[:6] not in comtrade.product_codes():
        raise ValueError(f"{digits[:6]} geçerli bir ürün kodu değil. Ürün adıyla aramayı dene.")
    return digits[:6]


def build(hs6, max_countries=None):
    """Bir ürün için skorlanmış aday ülkeler. max_countries verilmezse anahtarsız erişimde 40 ile sınırlanır."""
    if max_countries is None and not comtrade.api_key():
        max_countries = 40
    names = comtrade.countries()
    last_year = datetime.date.today().year - 1
    yearly = {year: comtrade.imports_by_reporter(hs6, year) for year in range(last_year - model.WINDOW, last_year + 1)}

    # t0: raporlayan ülke sayısı yeterli olan en son yıl (yeni yıllar eksik gelir).
    most = max(len(totals) for totals in yearly.values())
    if most == 0:
        raise ValueError(f"{hs6} için Comtrade'de veri yok. Kodu kontrol et.")
    t0 = max(year for year, totals in yearly.items() if len(totals) >= 0.75 * most)
    window = range(t0 - model.WINDOW + 1, t0 + 1)

    # Kod yakın zamanda tanımlandıysa (HS revizyonu) eski yıllarda veri olmaz ve büyüme şişer.
    # Bu durumda büyüme ve güven, 4 haneli üst pozisyonun serisinden hesaplanır.
    growth_basis, trend = None, yearly
    if len(yearly[window[0]]) < 0.5 * len(yearly[t0]):
        growth_basis = hs6[:4]
        trend = {year: comtrade.imports_by_reporter(growth_basis, year) for year in window}

    countries = [code for code in {code for year in window for code in yearly[year]}
                 if code != comtrade.TURKIYE and code in names]
    latest_year = {code: max(year for year in window if code in yearly[year]) for code in countries}
    world = sum(yearly[latest_year[code]][code][0] for code in countries)
    m_min = max(model.M_MIN, model.M_MIN_SHARE * world)

    candidates = []
    for code in countries:
        series = {year: yearly[year][code][0] for year in window if code in yearly[year]}
        latest = latest_year[code]
        value, weight = yearly[latest][code]
        trend_series = {year: trend[year][code][0] for year in window if code in trend[year]}
        kappa = model.confidence(trend_series, t0)
        g = model.growth(trend_series)
        if value >= m_min and kappa >= model.KAPPA_MIN and g is not None:
            candidates.append({"code": code, "country": names[code][0], "iso2": names[code][1], "year": latest,
                               "imports": value, "unit_price": value / weight if weight else None, "kappa": kappa,
                               "series": [[year, series.get(year)] for year in window],
                               "G_raw": g, "A": math.log(value)})

    candidates.sort(key=lambda row: -row["imports"])
    max_countries = max_countries or len(candidates)
    skipped = max(0, len(candidates) - max_countries)
    candidates = candidates[:max_countries]

    exports = {year: comtrade.exports_by_reporter(hs6, year) for year in {row["year"] for row in candidates}}
    for row in candidates:
        # Yeniden ihracat oranı: ülkenin aynı üründeki ihracatı / ithalatı (en fazla 1).
        row["reexport"] = min(1.0, exports[row["year"]].get(row["code"], 0) / row["imports"])
        partners = comtrade.imports_by_partner(hs6, row["year"], row["code"])
        total = sum(value for value, _ in partners.values()) or row["imports"]
        shares = {code: value / total for code, (value, _) in partners.items()}
        row["tr_share"] = shares.get(comtrade.TURKIYE, 0.0)
        row["H"] = 1 - row["tr_share"]
        row["F"] = 1 - model.hhi(shares.values())
        top = sorted(((share, code) for code, share in shares.items() if code != comtrade.TURKIYE), reverse=True)[:5]
        row["rivals"] = [{"country": names.get(code, (str(code), None))[0], "iso2": names.get(code, (None, None))[1],
                          "share": share} for share, code in top]

    model.adjust_growth(candidates, m_min)
    return {"hs6": hs6, "product": comtrade.product_name(hs6), "product_path": urunler.path(hs6),
            "t0": t0, "skipped": skipped, "growth_basis": growth_basis, "m_min": m_min,
            "rows": model.score(candidates)}


def main():
    parser = argparse.ArgumentParser(description="GTİP için ülke fırsat sıralaması")
    parser.add_argument("gtip")
    parser.add_argument("--max-ulke", type=int, help="skorlanacak en büyük pazar sayısı (anahtarsız erişimde varsayılan 40)")
    args = parser.parse_args()

    try:
        report = build(hs6_from(args.gtip), args.max_ulke)
    except ValueError as error:
        raise SystemExit(str(error))
    hs6, rows, skipped = report["hs6"], report["rows"], report["skipped"]

    def rivals(row):
        return ", ".join(f"{rival['country']} %{rival['share'] * 100:.0f}" for rival in row["rivals"][:3])

    print(f"\nÜrün {hs6} | son veri yılı {report['t0']} | {len(rows)} aday ülke"
          + (f" ({skipped} küçük pazar dökümü çekilmediği için dışarıda)" if skipped else ""))
    print("Skor göreli bir sıralamadır; tarife ve lojistik faktörleri henüz dahil değil.\n")
    print(f"{'#':>2} {'Ülke':<22}{'Skor':>5} {'İthalat (mn $)':>15} {'Büyüme':>8} {'TR payı':>8} {'Y.ihr.':>7}  Ana rakipler")
    for rank, row in enumerate(rows, 1):
        print(f"{rank:>2} {row['country'][:21]:<22}{row['score']:>5.0f} {row['imports'] / 1e6:>15,.1f} "
              f"{row['G_raw'] * 100:>7.1f}% {row['tr_share'] * 100:>7.1f}% {row['reexport'] * 100:>6.0f}%  {rivals(row)}")

    OUT_DIR.mkdir(exist_ok=True)
    out_file = OUT_DIR / f"{hs6}.csv"
    with out_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sira", "ulke", "skor", "veri_yili", "ithalat_usd", "yillik_buyume", "tr_payi",
                         "parcalanma", "birim_fiyat_usd_kg", "guven", "yeniden_ihracat_orani", "ana_rakipler"])
        for rank, row in enumerate(rows, 1):
            writer.writerow([rank, row["country"], round(row["score"], 1), row["year"], round(row["imports"]),
                             round(row["G_raw"], 4), round(row["tr_share"], 4), round(row["F"], 4),
                             round(row["unit_price"], 2) if row["unit_price"] else "", round(row["kappa"], 2),
                             round(row["reexport"], 2), rivals(row)])
    print(f"\nCSV: {out_file}")


if __name__ == "__main__":
    main()
