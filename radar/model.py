"""Fırsat skoru: plan belgesinin 6. bölümündeki model.

Bu sürümde G (büyüme), A (büyüklük), H (boşluk) ve F (parçalanma) hesaplanır.
T (tarife) ve L (lojistik) verisi henüz bağlı değil; ağırlıkları kalan faktörlere
oransal olarak dağıtılır.
"""

import math
import statistics

WEIGHTS = {"G": 0.25, "A": 0.20, "T": 0.15, "L": 0.15, "H": 0.15, "F": 0.10}
WINDOW = 5
M_MIN = 1_000_000
M_MIN_SHARE = 0.001   # alt eşik ürüne göre ölçeklenir: dünya ithalatının binde biri
KAPPA_MIN = 0.4
G_CAP = (-0.30, 0.40)  # yıllık büyüme bu aralığa kırpılır: sürdürülemez sıçramalar skoru ele geçirmesin
SIZE_HALF = 5          # pazar, alt eşiğin bu kadar katındayken büyüme oranına güven 0,5 olur


def growth(series):
    """Log-doğrusal regresyon eğiminden yıllık büyüme (formül 2-4). series: {yıl: USD}."""
    points = [(year, math.log(value)) for year, value in sorted(series.items()) if value > 0]
    if len(points) < 3:
        return None
    mean_t = sum(t for t, _ in points) / len(points)
    mean_l = sum(l for _, l in points) / len(points)
    slope = sum((t - mean_t) * (l - mean_l) for t, l in points) / sum((t - mean_t) ** 2 for t, _ in points)
    return math.exp(slope) - 1


def confidence(series, t0):
    """Güven skoru κ = (verili yıl sayısı / n) · e^(-yaş/4) (formül 18)."""
    years = [year for year, value in series.items() if value > 0]
    if not years:
        return 0.0
    return len(years) / WINDOW * math.exp(-(t0 - max(years)) / 4)


def adjust_growth(rows, m_min):
    """Ham büyümeyi (G_raw), gerçek talep işareti olarak ne kadar güvenilir olduğuna göre düzeltir (G).

    Güven = büyüklük güveni x (1 - yeniden ihracat oranı). Küçük pazarda birkaç sevkiyat oranı
    uçurur; ithal ettiğini büyük ölçüde yeniden ihraç eden ülkede (aktarma merkezi) artış iç talebi
    göstermez. Güven düştükçe oran, aday ülkelerin ortanca büyümesine çekilir.
    """
    low, high = G_CAP
    capped = [min(max(row["G_raw"], low), high) for row in rows]
    median = statistics.median(capped) if capped else 0.0
    for row, g in zip(rows, capped):
        size_trust = row["imports"] / (row["imports"] + SIZE_HALF * m_min)
        row["growth_trust"] = size_trust * (1 - row["reexport"])
        row["G"] = row["growth_trust"] * g + (1 - row["growth_trust"]) * median


def hhi(shares):
    return sum(share ** 2 for share in shares)


def _percentile(sorted_values, q):
    position = (len(sorted_values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def normalize(values):
    """%5-%95 kırpma, ardından 0-1 aralığına min-max (formül 13-14)."""
    ordered = sorted(values)
    p5, p95 = _percentile(ordered, 0.05), _percentile(ordered, 0.95)
    if p95 == p5:
        return [0.5] * len(values)
    return [(min(max(value, p5), p95) - p5) / (p95 - p5) for value in values]


def score(rows):
    """rows: her biri ham faktörleri ("G", "A", "H", "F") taşıyan sözlükler. Skoru ve z değerlerini ekler."""
    if not rows:
        return []
    factors = [f for f in WEIGHTS if all(f in row for row in rows)]
    total_weight = sum(WEIGHTS[f] for f in factors)
    for row in rows:
        row["z"] = {}
    for f in factors:
        for row, z in zip(rows, normalize([row[f] for row in rows])):
            row["z"][f] = z
    for row in rows:
        row["score"] = 100 * sum(WEIGHTS[f] / total_weight * row["z"][f] for f in factors)
    return sorted(rows, key=lambda row: -row["score"])
