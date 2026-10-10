"""Ana sayfa kapağındaki noktalı dünya haritasının verisini üretir.

Kullanım: python3 tools/dunya.py
  -> web/dunya.json       {"w", "h", "dots": [[x, y], ...], "centroids": {ISO2: [x, y]}}
  -> data/konumlar.json   {ISO2: [boylam, enlem]}  (skordaki yakınlık ölçüsü için)

Kaynak: Natural Earth ülke sınırları (kamu malı). Harita 1:110m veriden, eş aralıklı silindirik
izdüşümle çizilir. Konumlar 1:50m veriden alınır, çünkü küçük ülkeler yalnızca orada vardır.
"""

import json
import urllib.request
from pathlib import Path

SOURCE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"
DETAILED_SOURCE = SOURCE.replace("ne_110m", "ne_50m")
OUT_FILE = Path(__file__).resolve().parent.parent / "web" / "dunya.json"
LOCATIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "konumlar.json"

WIDTH = 1000
LAT_TOP, LAT_BOTTOM = 80, -56          # Antarktika ve kutup bölgesi kırpılır
STEP = 1.8                             # nokta aralığı, derece
HEIGHT = round(WIDTH * (LAT_TOP - LAT_BOTTOM) / 360)


def project(lon, lat):
    return round((lon + 180) / 360 * WIDTH, 1), round((LAT_TOP - lat) / (LAT_TOP - LAT_BOTTOM) * HEIGHT, 1)


def inside(lon, lat, ring):
    """Işın atma yöntemiyle nokta çokgenin içinde mi?"""
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def label_points(source):
    """Her ülkenin etiket noktası: (ISO2, boylam, enlem, özellik)."""
    for feature in json.loads(urllib.request.urlopen(source, timeout=120).read())["features"]:
        props = feature["properties"]
        iso2 = props.get("ISO_A2") if props.get("ISO_A2", "-99") != "-99" else props.get("ISO_A2_EH")
        yield (iso2 if iso2 != "-99" and props.get("LABEL_X") is not None else None,
               props.get("LABEL_X"), props.get("LABEL_Y"), feature)


def locations():
    points = {iso2: [round(lon, 2), round(lat, 2)] for iso2, lon, lat, _ in label_points(DETAILED_SOURCE) if iso2}
    LOCATIONS_FILE.write_text(json.dumps(points, separators=(",", ":")))
    return len(points)


def build():
    polygons, centroids = [], {}
    for iso2, lon, lat, feature in label_points(SOURCE):
        geometry = feature["geometry"]
        parts = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        for part in parts:
            outer = [(x, y) for x, y, *_ in part[0]]
            xs, ys = [x for x, _ in outer], [y for _, y in outer]
            polygons.append((min(xs), max(xs), min(ys), max(ys), outer))
        if iso2:
            centroids[iso2] = project(lon, lat)

    dots = []
    lat = LAT_TOP - STEP / 2
    while lat > LAT_BOTTOM:
        lon = -180 + STEP / 2
        while lon < 180:
            if any(x1 <= lon <= x2 and y1 <= lat <= y2 and inside(lon, lat, ring) for x1, x2, y1, y2, ring in polygons):
                dots.append(project(lon, lat))
            lon += STEP
        lat -= STEP

    OUT_FILE.write_text(json.dumps({"w": WIDTH, "h": HEIGHT, "dots": dots, "centroids": centroids}, separators=(",", ":")))
    return len(dots), len(centroids)


if __name__ == "__main__":
    dots, countries = build()
    print(f"{dots} nokta, {countries} ülke merkezi yazıldı: {OUT_FILE}")
    print(f"{locations()} ülke konumu yazıldı: {LOCATIONS_FILE}")
