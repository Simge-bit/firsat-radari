"""Ana sayfada dönen örnek ürünlerin raporlarını depoya yazar.

Kullanım: python3 tools/hazir_raporlar.py [GTİP ...]  ->  data/hazir/<kod>.json

Sunucu bu dosyaları Comtrade'e gitmeden verir; böylece ana sayfa, sunucu yeni açıldığında da
(önbellek boşken) hemen dolar. Kodlar web/app.js içindeki SAMPLES listesiyle aynı olmalıdır.
Veri yenilendiğinde ya da fuar takvimi eskidiğinde yeniden çalıştırılır.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rapor  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "hazir"
SAMPLES = ["080222", "570242", "150920", "251512"]

if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    for gtip in sys.argv[1:] or SAMPLES:
        hs6 = rapor.hs6_from(gtip)
        report = rapor.build(hs6)
        (OUT_DIR / f"{hs6}.json").write_text(json.dumps(report), encoding="utf-8")
        print(f"{hs6}: {len(report['rows'])} pazar")
