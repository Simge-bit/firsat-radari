"""Pazara giriş şartları için kurallı kontrol listesi.

Bu liste resmi bir veri kaynağından çekilmez; ürün grubu ve ülke bloğuna göre elle yazılmış genel
kurallardır. Amaç, ihracatçıya neyi araştırması gerektiğini göstermektir: her madde ilgili resmi
kurumun adresini taşır ve arayüzde "doğrula" uyarısıyla gösterilir. Mevzuat değiştikçe güncellenmelidir.
"""

AB = set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split())
AVRASYA = {"RU", "BY", "KZ", "KG", "AM"}
# Türkiye'nin ticareti durdurduğu ülkeler: raporda en sona alınır ve işaretlenir (bkz. COUNTRY_RULES).
TICARET_DURDU = {"IL"}
KORFEZ = {"SA", "AE", "KW", "QA", "BH", "OM"}
# Türkiye ile yürürlükte serbest ticaret anlaşması olan ülkeler (AB gümrük birliği ayrıca ele alınır).
STA = set("CH NO IS LI MK BA PS TN MA EG AL GE ME RS CL MU KR MY MD FO SG XK VE GB AE".split())

GIDA = {"hayvansal", "bitkisel", "islenmis_gida"}
SANAYI = {"kimya", "kozmetik", "tekstil", "deri_ayakkabi", "yapi", "karbon", "makine", "elektrik", "tasit", "oyuncak", "mobilya"}


def regime(iso2):
    if iso2 in AB:
        return "AB"
    if iso2 in AVRASYA:
        return "AVRASYA"
    if iso2 in KORFEZ:
        return "KORFEZ"
    return {"GB": "GB", "US": "US", "CN": "CN"}.get(iso2)


def families(hs6):
    """Ürün kodunun girdiği mevzuat grupları."""
    chapter, heading = int(hs6[:2]), int(hs6[:4])
    tags = set()
    if chapter <= 5 or chapter == 16:
        tags.add("hayvansal")
    elif chapter <= 14:
        tags.add("bitkisel")
    elif chapter == 15 or 17 <= chapter <= 22:
        tags.add("islenmis_gida")
    if chapter in (28, 29, 31, 32, 34, 35, 36, 37, 38):
        tags.add("kimya")
    if chapter == 30:
        tags.add("ilac")
    if chapter == 33:
        tags.add("kozmetik")
    if 50 <= chapter <= 63:
        tags.add("tekstil")
    if chapter in (41, 42, 43, 64):
        tags.add("deri_ayakkabi")
    if chapter in (68, 69, 70) or heading == 2523:
        tags.add("yapi")
    if chapter in (72, 73, 76, 31) or heading == 2523:
        tags.add("karbon")
    if chapter == 84:
        tags.add("makine")
    if chapter == 85:
        tags.add("elektrik")
    if chapter == 87:
        tags.add("tasit")
    if 9018 <= heading <= 9022:
        tags.add("medikal")
    if heading == 9503:
        tags.add("oyuncak")
    if chapter == 94:
        tags.add("mobilya")
    return tags


def _rule(rejim, gruplar, baslik, metin, kurum, url):
    return {"rejim": rejim, "gruplar": gruplar, "baslik": baslik, "metin": metin, "kurum": kurum, "url": url}


A2M = "https://trade.ec.europa.eu/access-to-markets"
CE = "https://single-market-economy.ec.europa.eu/single-market/ce-marking_en"

RULES = [
    # ---------- Avrupa Birliği ----------
    _rule("AB", None, "Dolaşım ve menşe belgesi",
          "Gümrük birliği kapsamındaki sanayi ürünleri ve işlenmiş tarım ürünleri A.TR dolaşım belgesiyle gümrük vergisiz girer. "
          "Tarım ürünleri ile kömür ve çelik ürünlerinde tercihli vergi için EUR.1 ya da menşe beyanı gerekir.",
          "T.C. Ticaret Bakanlığı", "https://ticaret.gov.tr"),
    _rule("AB", {"hayvansal"}, "Onaylı tesis ve veteriner sağlık sertifikası",
          "Hayvansal ürünler yalnızca AB'nin izin verdiği ülke ve onaylı tesislerden, resmi sağlık sertifikasıyla ve sınır kontrol noktası üzerinden girebilir. "
          "Türkiye'nin ve tesisinin ilgili ürün için AB listesinde olup olmadığını kontrol et.",
          "Avrupa Komisyonu, Gıda Güvenliği", "https://food.ec.europa.eu"),
    _rule("AB", {"bitkisel"}, "Bitki sağlık sertifikası ve kalıntı limitleri",
          "Taze meyve, sebze ve çoğu bitkisel ürün bitki sağlık sertifikası ister. Pestisit kalıntıları ve aflatoksin gibi bulaşanlar AB limitlerini aşmamalıdır. "
          "Bazı Türk ürünleri (örneğin kuru incir, fındık, Antep fıstığı ve bazı yaş meyve sebzeler) sınırda artırılmış kontrole tabidir; liste düzenli güncellenir.",
          "Avrupa Komisyonu, Gıda Güvenliği", "https://food.ec.europa.eu"),
    _rule("AB", {"islenmis_gida"}, "Gıda mevzuatı ve etiketleme",
          "Etikette alerjenler, içindekiler ve besin değerleri satılacağı ülkenin dilinde yer almalıdır. Katkı maddeleri ve bulaşan limitleri AB kurallarına uymalıdır. "
          "Ürün hayvansal bileşen içeriyorsa ek sağlık şartları doğar.",
          "Avrupa Komisyonu, Gıda Güvenliği", "https://food.ec.europa.eu"),
    _rule("AB", {"kimya"}, "REACH kaydı ve CLP etiketleme",
          "Yılda 1 tonun üzerinde AB'ye giren kimyasal maddeler REACH kapsamında kayıt gerektirir; kaydı AB'deki ithalatçı ya da atayacağın tek temsilci yapar. "
          "Tehlikeli maddeler CLP kurallarına göre sınıflandırılıp etiketlenmelidir.",
          "Avrupa Kimyasallar Ajansı (ECHA)", "https://echa.europa.eu"),
    _rule("AB", {"kozmetik"}, "Sorumlu kişi ve ürün bildirimi",
          "Kozmetik ürünler için AB'de yerleşik bir sorumlu kişi atanmalı, ürün satıştan önce CPNP sistemine bildirilmeli ve ürün güvenlilik raporu hazırlanmalıdır.",
          "Avrupa Komisyonu", A2M),
    _rule("AB", {"ilac"}, "Pazarlama izni",
          "İlaçlar, Avrupa İlaç Ajansı ya da ilgili ülke otoritesinden pazarlama izni almadan satılamaz; üretim tesisi iyi üretim uygulamaları (GMP) belgesine sahip olmalıdır.",
          "Avrupa İlaç Ajansı (EMA)", "https://www.ema.europa.eu"),
    _rule("AB", {"tekstil", "deri_ayakkabi"}, "Etiketleme ve kısıtlı kimyasallar",
          "Tekstilde lif bileşimi, ayakkabıda malzeme bilgisi etikette yer almalıdır. Azo boyalar gibi kısıtlı maddeler REACH limitlerini aşmamalıdır.",
          "Avrupa Komisyonu", A2M),
    _rule("AB", {"makine"}, "CE işareti: makine emniyeti",
          "Makineler CE işareti taşımalıdır: risk değerlendirmesi, teknik dosya ve AB uygunluk beyanı gerekir. Ürüne göre alçak gerilim ve elektromanyetik uyumluluk kuralları da uygulanır.",
          "Avrupa Komisyonu", CE),
    _rule("AB", {"elektrik"}, "CE işareti: elektrikli ürünler",
          "Elektrikli ve elektronik ürünler CE işareti taşımalıdır: alçak gerilim, elektromanyetik uyumluluk ve tehlikeli madde kısıtı (RoHS) kuralları; kablosuz özelliği varsa telsiz ekipmanı kuralları uygulanır. "
          "Bazı ürünlerde enerji etiketi zorunludur.",
          "Avrupa Komisyonu", CE),
    _rule("AB", {"yapi"}, "CE işareti: yapı malzemeleri",
          "Uyumlaştırılmış standart kapsamındaki yapı malzemeleri performans beyanı ve CE işaretiyle satılır.",
          "Avrupa Komisyonu", CE),
    _rule("AB", {"oyuncak"}, "CE işareti: oyuncak güvenliği",
          "Oyuncaklar oyuncak güvenliği kurallarına ve EN 71 standartlarına uygun olmalı, CE işareti taşımalıdır.",
          "Avrupa Komisyonu", CE),
    _rule("AB", {"medikal"}, "CE işareti: tıbbi cihazlar",
          "Tıbbi cihazlar Tıbbi Cihaz Tüzüğü'ne göre CE işareti almalıdır; çoğu sınıfta onaylanmış kuruluş denetimi ve AB'de yetkili temsilci gerekir.",
          "Avrupa Komisyonu", CE),
    _rule("AB", {"tasit"}, "Tip onayı",
          "Araçlar ve güvenlikle ilgili aksam ve parçalar AB tip onayı ya da ilgili BM regülasyonuna göre onay (E işareti) gerektirir.",
          "Avrupa Komisyonu", A2M),
    _rule("AB", {"mobilya"}, "Genel ürün güvenliği",
          "Tüketici ürünleri Genel Ürün Güvenliği Tüzüğü'ne tabidir: AB'de yerleşik bir sorumlu ekonomik operatör ve izlenebilirlik bilgisi gerekir.",
          "Avrupa Komisyonu", A2M),
    _rule("AB", {"karbon"}, "Sınırda karbon düzenlemesi (SKDM)",
          "Demir çelik, alüminyum, çimento ve gübre ithalatında AB'deki alıcı ürünün gömülü emisyonunu beyan eder ve 2026'dan itibaren bunun için mali yükümlülük doğar. "
          "Alıcın senden tesis bazında emisyon verisi isteyecektir.",
          "Avrupa Komisyonu, Vergilendirme ve Gümrük Birliği", "https://taxation-customs.ec.europa.eu/carbon-border-adjustment-mechanism_en"),

    # ---------- Birleşik Krallık ----------
    _rule("GB", None, "Serbest ticaret anlaşması ve menşe",
          "Türkiye ile Birleşik Krallık arasında serbest ticaret anlaşması yürürlüktedir. Tercihli vergiden yararlanmak için menşe beyanı ya da EUR.1 gerekir.",
          "T.C. Ticaret Bakanlığı", "https://ticaret.gov.tr"),
    _rule("GB", {"makine", "elektrik", "oyuncak", "yapi", "medikal"}, "UKCA ya da CE işareti",
          "Büyük Britanya pazarında ürün işareti UKCA'dır; çoğu ürün grubunda CE işareti de kabul edilmeye devam ediyor. Ürün grubun için hangisinin geçerli olduğunu kontrol et.",
          "Birleşik Krallık Hükümeti", "https://www.gov.uk/guidance/using-the-ukca-marking"),
    _rule("GB", GIDA, "Gıda ve bitki sağlığı kontrolleri",
          "Hayvansal ürünler sağlık sertifikası, düzenlemeye tabi bitkisel ürünler bitki sağlık sertifikası ister. Kontrol sıklığı ürünün risk sınıfına göre değişir.",
          "Birleşik Krallık Hükümeti", "https://www.gov.uk/import-goods-into-uk"),
    _rule("GB", {"kozmetik", "kimya"}, "Birleşik Krallık'a özgü kayıt",
          "Kozmetikte Birleşik Krallık'ta yerleşik sorumlu kişi ve ürün bildirimi, kimyasallarda UK REACH kaydı gerekir; AB'deki kayıtlar burada geçerli değildir.",
          "Birleşik Krallık Hükümeti", "https://www.gov.uk/import-goods-into-uk"),

    # ---------- Amerika Birleşik Devletleri ----------
    _rule("US", None, "Gümrük vergisi ve ek vergiler",
          "Türkiye ile ABD arasında serbest ticaret anlaşması yoktur. Standart tarifeye ek olarak ürün ve ülke bazlı ek vergiler sık değişir; sevkiyattan önce güncel oranı kontrol et.",
          "ABD Uluslararası Ticaret Komisyonu", "https://hts.usitc.gov"),
    _rule("US", GIDA, "FDA tesis kaydı ve ön bildirim",
          "Gıda üreten tesis FDA'ya kayıt olmalı ve bir ABD temsilcisi atamalıdır. Her sevkiyat için ön bildirim yapılır; ABD'deki ithalatçı tedarikçisini doğrulamakla yükümlüdür. "
          "Et, kanatlı ve yumurta ürünleri ayrıca Tarım Bakanlığı'nın ülke onayına tabidir; taze meyve sebzede bitki sağlığı izni gerekir.",
          "ABD Gıda ve İlaç Dairesi (FDA)", "https://www.fda.gov/food"),
    _rule("US", {"kozmetik"}, "FDA tesis kaydı ve ürün listeleme",
          "Kozmetik üreticileri tesisini FDA'ya kaydettirmeli ve ürünlerini listelemelidir.",
          "ABD Gıda ve İlaç Dairesi (FDA)", "https://www.fda.gov/cosmetics"),
    _rule("US", {"ilac", "medikal"}, "FDA kaydı ve onayı",
          "İlaç ve tıbbi cihazlarda kuruluş kaydı ve ürünün sınıfına göre FDA bildirimi ya da onayı gerekir.",
          "ABD Gıda ve İlaç Dairesi (FDA)", "https://www.fda.gov"),
    _rule("US", {"elektrik"}, "FCC uygunluğu ve güvenlik sertifikası",
          "Radyo frekansı yayan cihazlar FCC kurallarına uymalıdır. Yasal zorunluluk olmasa da alıcılar ve perakendeciler genellikle tanınmış bir laboratuvarın (örneğin UL, ETL) güvenlik sertifikasını ister.",
          "ABD Federal İletişim Komisyonu (FCC)", "https://www.fcc.gov"),
    _rule("US", {"oyuncak"}, "Çocuk ürünü sertifikası",
          "Çocuk ürünleri için akredite laboratuvar testi ve Çocuk Ürünü Sertifikası gerekir; oyuncaklar ASTM F963 standardına uymalıdır.",
          "ABD Tüketici Ürünleri Güvenliği Komisyonu (CPSC)", "https://www.cpsc.gov"),
    _rule("US", {"tekstil"}, "Etiketleme ve yanıcılık",
          "Tekstil ürünlerinde lif içeriği, menşe ülke ve üretici bilgisi etikette yer almalıdır. Giyim ve halılar federal yanıcılık standartlarına uymalıdır.",
          "ABD Tüketici Ürünleri Güvenliği Komisyonu (CPSC)", "https://www.cpsc.gov"),
    _rule("US", {"tasit"}, "Araç güvenliği ve emisyon",
          "Araçlar ve güvenlikle ilgili parçalar federal motorlu taşıt güvenlik standartlarına, motorlar çevre ajansının emisyon kurallarına uymalıdır.",
          "ABD Ulusal Karayolu Trafik Güvenliği İdaresi (NHTSA)", "https://www.nhtsa.gov"),

    # ---------- Avrasya Ekonomik Birliği ----------
    _rule("AVRASYA", None, "EAC işareti",
          "Birliğin teknik düzenlemelerine tabi ürünler uygunluk sertifikası ya da beyanı alıp EAC işareti taşımalıdır. Başvuruyu birlik içinde yerleşik bir firma yapar; etiket Rusça olmalıdır.",
          "Avrasya Ekonomik Komisyonu", "https://eec.eaeunion.org"),
    _rule("AVRASYA", {"hayvansal"}, "Onaylı tesis ve veteriner sertifikası",
          "Hayvansal ürünler yalnızca birliğin onayladığı tesislerden, veteriner sertifikasıyla girebilir.",
          "Avrasya Ekonomik Komisyonu", "https://eec.eaeunion.org"),

    # ---------- Körfez ülkeleri ----------
    _rule("KORFEZ", {"oyuncak", "elektrik"}, "Körfez uygunluk işareti (G işareti)",
          "Oyuncaklar ve alçak gerilimli elektrikli cihazlar Körfez teknik düzenlemelerine göre G işareti taşımalıdır.",
          "Körfez Standardizasyon Kuruluşu (GSO)", "https://www.gso.org.sa"),
    _rule("KORFEZ", GIDA, "Arapça etiket ve helal belgesi",
          "Gıda etiketleri Arapça olmalı, üretim ve son tüketim tarihlerini içermelidir. Et ve kanatlı ürünlerinde tanınmış bir kuruluştan helal sertifikası gerekir.",
          "Körfez Standardizasyon Kuruluşu (GSO)", "https://www.gso.org.sa"),

    # ---------- Çin ----------
    _rule("CN", GIDA, "Yurt dışı gıda üreticisi kaydı",
          "Çin'e gıda ihraç eden üretim tesisleri Çin gümrük idaresine (GACC) kayıt olmalıdır; etiket Çince olmalıdır. Bazı ürünlerde ülkeler arası protokol gerekir.",
          "Çin Gümrük Genel İdaresi (GACC)", "http://english.customs.gov.cn"),
    _rule("CN", {"elektrik", "oyuncak", "tasit"}, "Zorunlu ürün sertifikası (CCC)",
          "Katalogdaki ürünler (birçok elektrikli ev aleti, oto parçası ve oyuncak dahil) CCC sertifikası olmadan ithal edilemez.",
          "Çin Piyasa Düzenleme İdaresi", "https://www.samr.gov.cn"),
    _rule("CN", {"kozmetik"}, "Ürün kaydı ya da bildirimi",
          "Kozmetik ürünler satıştan önce Çin'deki sorumlu kişi aracılığıyla ilaç idaresine kaydedilmeli ya da bildirilmelidir.",
          "Çin Ulusal Tıbbi Ürünler İdaresi (NMPA)", "https://english.nmpa.gov.cn"),
]

# Tek ülkeye özgü uyarılar ve kurallar.
COUNTRY_RULES = {
    # SABER gıda dışı ürünler içindir; gıda ayrı bir kurumun (SFDA) denetimindedir.
    "SA": [_rule(None, SANAYI, "SABER uygunluk sertifikası",
                 "Düzenlemeye tabi ürünler için ithalatçı, SABER platformu üzerinden ürün ve sevkiyat uygunluk sertifikası almalıdır.",
                 "Suudi Standartlar Kurumu (SASO)", "https://saber.sa")],
    "RU": [_rule(None, None, "Yaptırımlar ve ödeme kısıtları",
                 "Rusya'ya yönelik uluslararası yaptırımlar bazı ürünlerin satışını, bankacılık ve ödeme işlemlerini kısıtlıyor. Ürününün ve alıcının yaptırım kapsamında olmadığını ve ödemeyi nasıl alacağını önceden netleştir.",
                 "T.C. Ticaret Bakanlığı", "https://ticaret.gov.tr")],
    "IL": [_rule(None, None, "Ticaret durduruldu",
                 "Türkiye, Mayıs 2024'ten itibaren İsrail ile ihracat ve ithalatı durdurmuştur. Güncel durumu Ticaret Bakanlığı'ndan teyit et.",
                 "T.C. Ticaret Bakanlığı", "https://ticaret.gov.tr")],
}

_STA_RULE = _rule(None, None, "Serbest ticaret anlaşması ve menşe",
                  "Türkiye ile bu ülke arasında serbest ticaret anlaşması yürürlüktedir. Tercihli gümrük vergisinden yararlanmak için anlaşmanın öngördüğü menşe ispat belgesi gerekir.",
                  "T.C. Ticaret Bakanlığı", "https://ticaret.gov.tr")


# Ülkeden bağımsız, dünya genelinde yaygın şartlar. Kendi gıda kuralları yazılmış bloklarda tekrar edilmez.
_GENERAL = [
    _rule(None, {"bitkisel"}, "Bitki sağlık sertifikası",
          "Çoğu ülke bitkisel ürünlerde ihracatçı ülkenin resmi otoritesinden bitki sağlık sertifikası ister; Türkiye'de Tarım ve Orman Bakanlığı düzenler. "
          "Alıcı ülkenin ek şartlarını (ilaçlama, kalıntı limiti, ithalat izni) alıcından ya da Ticaret Müşavirliği'nden öğren.",
          "T.C. Tarım ve Orman Bakanlığı", "https://www.tarimorman.gov.tr"),
    _rule(None, {"hayvansal"}, "Veteriner sağlık sertifikası ve ülke onayı",
          "Hayvansal ürünlerde alıcı ülke genellikle Türkiye'yi ve üretim tesisini önceden onaylamış olmalıdır; sevkiyata veteriner sağlık sertifikası eşlik eder. "
          "İlgili ülkeye ihracat izni olan tesisleri Tarım ve Orman Bakanlığı'ndan öğren.",
          "T.C. Tarım ve Orman Bakanlığı", "https://www.tarimorman.gov.tr"),
]
_ORIGIN_RULE = _rule(None, None, "Menşe şahadetnamesi",
                     "Alıcı ülkenin gümrüğü ya da alıcın, ürünün Türkiye menşeli olduğunu gösteren menşe şahadetnamesi isteyebilir. Belgeyi ticaret ve sanayi odaları düzenler.",
                     "Türkiye Odalar ve Borsalar Birliği (TOBB)", "https://www.tobb.org.tr")


def checklist(hs6, iso2):
    """Bu ürün ve ülke için kontrol listesi: [{"baslik", "metin", "kurum", "url"}]. Kapsam dışıysa boş liste."""
    tags, bloc = families(hs6), regime(iso2)
    items = [rule for rule in COUNTRY_RULES.get(iso2, []) if rule["gruplar"] is None or rule["gruplar"] & tags]
    items += [rule for rule in RULES if rule["rejim"] == bloc and (rule["gruplar"] is None or rule["gruplar"] & tags)]
    if bloc not in ("AB", "GB", "US"):
        items += [rule for rule in _GENERAL if rule["gruplar"] & tags]
    if iso2 in STA and iso2 != "GB":
        items.append(_STA_RULE)
    elif bloc is None:
        items.append(_ORIGIN_RULE)
    return [{key: rule[key] for key in ("baslik", "metin", "kurum", "url")} for rule in items]
