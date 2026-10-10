"""Fırsat skoru: plan belgesinin 6. bölümündeki model.

Altı faktör: G (büyüme), A (büyüklük), T (tarife: Türkiye'ye uygulanan gümrük vergisi),
L (lojistik: Türkiye'ye yakınlık), H (boşluk) ve F (parçalanma). Bir faktörün verisi alınamazsa
ağırlığı kalan faktörlere oransal olarak dağıtılır.
"""

import math
import statistics

# Ağırlıklar geçmişe dönük sınamaya göre belirlendi (tools/dogrulama.py; 27 ürün, 2021 verisiyle skor, 2025 sonucu):
# yakınlık ve Türkiye için boşluk sonraki yılları en iyi gösteren ölçülerdi, geçmiş talep büyümesi göstermedi.
# Plan belgesindeki ilk ağırlıklar: G 0.25, A 0.20, T 0.15, L 0.15, H 0.15, F 0.10.
WEIGHTS = {"L": 0.30, "H": 0.25, "A": 0.20, "T": 0.10, "F": 0.10, "G": 0.05}
WINDOW = 5
M_MIN = 1_000_000
M_MIN_SHARE = 0.001   # alt eşik ürüne göre ölçeklenir: dünya ithalatının binde biri
KAPPA_MIN = 0.3        # son verisi iki yıl geride kalan ama üç yılı dolu ülke (0,36) listede kalır, "veri zayıf" diye işaretlenir
G_CAP = (-0.30, 0.40)  # yıllık büyüme bu aralığa kırpılır: sürdürülemez sıçramalar skoru ele geçirmesin
ROBUST_MIN = 20        # bu sayıdan itibaren kırpma sınırları gerçek değerlerden seçilir
T_CAP = 30.0           # gümrük vergisi puanı: %0 vergi 1, bu oran ve üstü 0
ABSOLUTE = {"T"}       # zaten 0-1 ölçeğinde gelen, ülkeler arasında yeniden ölçeklenmeyen ölçüler
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


def tariff_score(rate):
    """Gümrük vergisi puanı, mutlak ölçekte: %0 -> 1, T_CAP ve üstü -> 0.

    Ülkeler arası göreli ölçek burada yanıltır: ülkelerin çoğu aynı oranı uygular (ör. bütün AB), bu yüzden
    yüzde 3'lük bir vergi "en kötüler" arasına düşüp sıfır puan alabilir.
    """
    return 1 - min(max(rate, 0.0), T_CAP) / T_CAP


def hhi(shares):
    return sum(share ** 2 for share in shares)


def _percentile(sorted_values, q):
    position = (len(sorted_values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def normalize(values):
    """%5-%95 kırpma, ardından 0-1 aralığına min-max (formül 13-14).

    Yeterli sayıda değer varsa (en az 20) sınırlar listedeki gerçek değerlerden seçilir: ara değer hesabı tek bir uç
    değeri sınırın içine taşır ve ölçeğin tamamını o değer belirler. Az sayıda değerde ara değer hesabı kullanılır.
    """
    ordered = sorted(values)
    if len(ordered) >= ROBUST_MIN:
        p5, p95 = ordered[math.ceil((len(ordered) - 1) * 0.05)], ordered[math.floor((len(ordered) - 1) * 0.95)]
    else:
        p5, p95 = _percentile(ordered, 0.05), _percentile(ordered, 0.95)
    if p95 == p5:
        return [0.5] * len(values)
    return [(min(max(value, p5), p95) - p5) / (p95 - p5) for value in values]


def score(rows):
    """rows: her biri ham faktörleri ("G", "A", "T", "L", "H", "F") taşıyan sözlükler. Skoru ve z değerlerini ekler."""
    if not rows:
        return []
    factors = [f for f in WEIGHTS if all(f in row for row in rows)]
    total_weight = sum(WEIGHTS[f] for f in factors)
    for row in rows:
        row["z"] = {}
    for f in factors:
        values = [row[f] for row in rows]
        for row, z in zip(rows, values if f in ABSOLUTE else normalize(values)):
            row["z"][f] = z
    for row in rows:
        row["score"] = 100 * sum(WEIGHTS[f] / total_weight * row["z"][f] for f in factors)
    return sorted(rows, key=lambda row: -row["score"])
