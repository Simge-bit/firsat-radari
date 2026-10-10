"""iyzico'da aylık Pro aboneliğinin ürününü ve ödeme planını bir kez açar.

Kullanım: IYZICO_API_KEY, IYZICO_SECRET_KEY ve IYZICO_BASE ortam değişkenleri tanımlıyken
  python3 tools/iyzico_plan.py
Yazdırdığı plan kodu Render'da IYZICO_PLAN_MONTHLY değişkenine girilir. Deneme ve gerçek ortam için ayrı ayrı çalıştırılır.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import odeme  # noqa: E402
import server  # noqa: E402


def main():
    if not odeme.configured():
        sys.exit("Önce IYZICO_API_KEY ve IYZICO_SECRET_KEY değişkenlerini tanımla.")
    product = odeme._call("/v2/subscription/products", {"locale": "tr", "name": "İhraçbul Pro", "description": "Tüm ürünlerde tam rapor"})
    if product.get("status") != "success":
        sys.exit("Ürün açılamadı: " + str(product.get("errorMessage") or product))
    plan = odeme._call(f"/v2/subscription/products/{product['data']['referenceCode']}/pricing-plans", {
        "locale": "tr", "name": "Pro, aylık", "price": server.PRICES["pro"], "currencyCode": "TRY",
        "paymentInterval": "MONTHLY", "paymentIntervalCount": 1, "planPaymentType": "RECURRING"})
    if plan.get("status") != "success":
        sys.exit("Plan açılamadı: " + str(plan.get("errorMessage") or plan))
    print("Plan açıldı. Render'a şu değişkeni ekle:")
    print("IYZICO_PLAN_MONTHLY=" + plan["data"]["referenceCode"])


if __name__ == "__main__":
    main()
