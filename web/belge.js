"use strict";

/* İçgörüler ve PDF rapor belgesi.
   Buradaki her cümle rapor verisinden hesaplanır; serbest metin ya da tahmin yoktur.
   Ülke adlarına ek getirilmez (Türkçe ek uyumu hataya açık): adlar hep yalın halde, liste ya da parantez içinde yazılır. */

const sumOf = (items, pick) => items.reduce((total, item) => total + pick(item), 0);
const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b), mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};
const trExport = (row) => row.imports * row.tr_share;
const NEGLIGIBLE = 0.001;                 // binde birin altındaki pay "yok" sayılır

// Raporun bütünü için başlıklı içgörüler: [{ title, text }]
function summaryInsights(report) {
  const rows = report.rows, count = rows.length;
  const total = sumOf(rows, (row) => row.imports), fromTurkiye = sumOf(rows, trExport);
  const share = total ? fromTurkiye / total : 0;
  const bySize = [...rows].sort((a, b) => b.imports - a.imports);
  const large = bySize.slice(0, Math.ceil(count / 2));    // büyük pazarlar: ithalatı ortancanın üzerindekiler
  const insights = [];

  const top = bySize.slice(0, 3);
  insights.push({
    title: "Pazarın büyüklüğü",
    text: `${count} aday pazarın ${report.t0} yılı toplam ithalatı ${million(total)}. En büyük pazarlar: `
      + top.map((row) => `${nameOf(row)} (${million(row.imports)})`).join(", ")
      + `. Bu ${top.length} pazar toplamın ${pct(sumOf(top, (row) => row.imports) / total)} kadarını oluşturuyor.`,
  });

  const level = share >= 0.5 ? "baskın tedarikçi" : share >= 0.2 ? "güçlü bir tedarikçi"
    : share >= 0.05 ? "orta ölçekli bir tedarikçi" : "küçük bir tedarikçi";
  const inTopThree = rows.filter((row) => row.tr_rank && row.tr_rank <= 3).length;
  const absent = rows.filter((row) => row.tr_share < NEGLIGIBLE).length;
  insights.push({
    title: "Türkiye'nin konumu",
    text: `Türkiye bu pazarlara yaklaşık ${million(fromTurkiye)} satıyor ve toplam ithalatın ${pct(share)} kadarını karşılıyor: ${level}. `
      + `${count} pazarın ${inTopThree} tanesinde ilk üç tedarikçi arasında; `
      + (absent ? `${absent} tanesinde ise yok ya da payı binde birin altında.` : "pazarların tamamında satışı var."),
  });

  if (fromTurkiye > 0) {
    const main = [...rows].sort((a, b) => trExport(b) - trExport(a)).slice(0, 3);
    const concentration = sumOf(main, trExport) / fromTurkiye;
    insights.push({
      title: "İhracatın dağılımı",
      text: `Türkiye'nin bu pazarlara ihracatının ${pct(concentration)} kadarı ${main.length} ülkeye gidiyor: `
        + main.map((row) => `${nameOf(row)} (${million(trExport(row))})`).join(", ") + ". "
        + (concentration >= 0.6 ? "Yoğunlaşma yüksek: bu ülkelerdeki bir talep düşüşü ihracatı doğrudan etkiler."
          : "İhracat az sayıda pazara bağımlı değil."),
    });
  }

  const growing = rows.filter((row) => row.G_raw > 0).length;
  const fastest = large.filter((row) => row.G_raw > 0).sort((a, b) => b.G_raw - a.G_raw).slice(0, 3);
  insights.push({
    title: "Talep eğilimi",
    text: `${growing} pazarda ithalat büyüyor, ${count - growing} pazarda küçülüyor; ortanca yıllık değişim ${pct(median(rows.map((row) => row.G_raw)))}. `
      + (fastest.length ? "Büyük pazarlar içinde en hızlı büyüyenler: "
        + fastest.map((row) => `${nameOf(row)} (${pct(row.G_raw)})`).join(", ") + "." : "Büyük pazarların hiçbirinde ithalat büyümüyor."),
  });

  const gaps = large.filter((row) => row.tr_share < 0.05).slice(0, 3);
  insights.push({
    title: "Boş alan",
    text: gaps.length
      ? "Türkiye'nin payının %5'in altında kaldığı büyük pazarlar: "
        + gaps.map((row) => `${nameOf(row)} (${million(row.imports)}, Türkiye payı ${pct(row.tr_share)})`).join("; ") + "."
      : "Büyük pazarların hepsinde Türkiye'nin payı %5'in üzerinde. Büyüme, yeni pazardan çok mevcut pazarlarda pay artışından gelebilir.",
  });

  // Rakipler her pazarın ilk beş tedarikçisinden toplanır; bu yüzden değerler alt sınırdır.
  const rivals = new Map();
  rows.forEach((row) => row.rivals.forEach((rival) => {
    const name = countryName(rival.iso2, rival.country);
    rivals.set(name, (rivals.get(name) || 0) + rival.share * row.imports);
  }));
  const leaders = [...rivals].sort((a, b) => b[1] - a[1]).slice(0, 3);
  if (leaders.length) {
    insights.push({
      title: "Rakipler",
      text: "Aday pazarlarda Türkiye dışında öne çıkan tedarikçiler: "
        + leaders.map(([name, value]) => `${name} (en az ${million(value)}, pay ${pct(value / total)})`).join("; ") + ".",
    });
  }

  const priced = rows.filter((row) => row.tr_unit_price && row.unit_price);
  if (priced.length >= 3) {
    const below = priced.filter((row) => row.tr_unit_price < row.unit_price).length;
    const gap = median(priced.map((row) => row.tr_unit_price / row.unit_price - 1));
    insights.push({
      title: "Fiyat konumu",
      text: `Fiyat verisi olan ${priced.length} pazarın ${below} tanesinde Türkiye'nin birim fiyatı, pazarın ortalama ithal fiyatının altında. `
        + (Math.abs(gap) < 0.05 ? "Türkiye'nin fiyatı genelde pazar ortalamasına yakın."
          : `Türkiye'nin fiyatı ortanca olarak pazar ortalamasının ${pct(Math.abs(gap))} ${gap < 0 ? "altında" : "üzerinde"}.`),
    });
  }

  insights.push({
    title: "Öne çıkan pazarlar",
    text: "Skora göre ilk üç pazar: "
      + rows.slice(0, 3).map((row) => `${nameOf(row)} (skor ${num(row.score, 0)})`).join(", ") + ". "
      + `Birinci sıradaki pazarın gerekçesi: ${whyText(rows[0]).toLocaleLowerCase("tr-TR")}`,
  });
  return insights;
}

// Bir pazardaki tedarikçiler (Türkiye dahil), paya göre sıralı.
function suppliersOf(row) {
  return [{ name: "Türkiye", share: row.tr_share, unit_price: row.tr_unit_price, turkiye: true }]
    .concat(row.rivals.map((rival) => ({ name: countryName(rival.iso2, rival.country), share: rival.share, unit_price: rival.unit_price })))
    .filter((supplier) => supplier.share > 0 || supplier.turkiye)
    .sort((a, b) => b.share - a.share);
}

// Tek bir pazar için değerlendirme cümleleri.
function marketInsights(row) {
  const lines = [];
  const points = row.series.filter(([, value]) => value);
  if (points.length >= 2) {
    const [firstYear, firstValue] = points[0], [lastYear, lastValue] = points[points.length - 1];
    lines.push(`İthalat ${firstYear} yılında ${million(firstValue)} iken ${lastYear} yılında ${million(lastValue)} oldu; yıllık ortalama değişim ${pct(row.G_raw)}.`);
  }

  const suppliers = suppliersOf(row), leader = suppliers[0], hhi = 1 - row.F;
  const topShare = sumOf(suppliers.slice(0, 3), (supplier) => supplier.share);
  lines.push(`Pazarın lideri ${leader.name} (pay ${pct(leader.share)}). İlk üç tedarikçi ithalatın ${pct(topShare)} kadarını karşılıyor: `
    + (hhi > 0.4 ? "pazar az sayıda tedarikçide yoğunlaşmış, yeni girişi zorlaştırabilir."
      : hhi < 0.2 ? "pazar parçalı, yeni tedarikçiye alan var." : "yoğunlaşma orta düzeyde."));

  lines.push(row.tr_share < NEGLIGIBLE
    ? "Türkiye bu pazarda görünmüyor: ithalattaki payı yok ya da binde birin altında."
    : `Türkiye ${row.suppliers} tedarikçi arasında ${row.tr_rank}. sırada, payı ${pct(row.tr_share)}.`);

  if (row.tr_unit_price && row.unit_price) {
    const gap = row.tr_unit_price / row.unit_price - 1;
    lines.push(`Türkiye'nin birim fiyatı ${num(row.tr_unit_price, 2)} $/kg, pazar ortalaması ${num(row.unit_price, 2)} $/kg: `
      + (Math.abs(gap) < 0.02 ? "ortalamayla aynı düzeyde." : `ortalamanın ${pct(Math.abs(gap))} ${gap < 0 ? "altında" : "üzerinde"}.`)
      + (!leader.turkiye && leader.unit_price ? ` Lider tedarikçinin fiyatı ${num(leader.unit_price, 2)} $/kg.` : ""));
  } else if (row.unit_price) {
    lines.push(`Pazarın ortalama ithal birim fiyatı ${num(row.unit_price, 2)} $/kg.`);
  }

  if (isHub(row)) lines.push(`Dikkat: bu ülke ithal ettiği ürünün ${pct(row.reexport)} kadarını yeniden ihraç ediyor. Aktarma merkezi olabilir; ithalattaki artış iç talebi göstermeyebilir.`);
  else if (row.growth_trust < 0.5) lines.push("Dikkat: pazar küçük olduğu için birkaç sevkiyat büyüme oranını belirgin biçimde değiştirebilir.");
  if (row.kappa < 0.7) lines.push("Dikkat: bu ülkenin verisi eksik ya da gecikmeli; rakamları temkinli oku.");
  return lines;
}

/* ---------- Pazara giriş: müşavirlik, fuarlar, resmi şart kaynağı ---------- */

const EU_MEMBERS = new Set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split(" "));
const today = () => new Date().toISOString().slice(0, 10);

// "10-12 Haz 2026" ya da "28 Nis - 1 May 2026"
function fairDates(fair) {
  const start = new Date(fair.baslangic), end = new Date(fair.bitis);
  const short = (date) => date.toLocaleDateString("tr-TR", { day: "numeric", month: "short" });
  const range = start.getMonth() === end.getMonth() ? `${start.getDate()}-${short(end)}` : `${short(start)} - ${short(end)}`;
  return fair.baslangic === fair.bitis ? `${short(start)} ${start.getFullYear()}` : `${range} ${end.getFullYear()}`;
}

// AB üyeleri için Avrupa Komisyonu'nun ürün ve menşe bazlı şart sayfası.
function requirementsLink(row, hs6) {
  return EU_MEMBERS.has(row.iso2)
    ? `https://trade.ec.europa.eu/access-to-markets/en/results?product=${hs6}&origin=TR&destination=${row.iso2}` : "";
}

// Müşavirliğe gönderilecek ithalatçı listesi talebinin hazır e-postası.
function importerRequestLink(office, row, report) {
  const product = report.product_path ? productLabels(report.product_path).title : report.product || "";
  const subject = `İthalatçı firma listesi talebi: GTİP ${dotted(report.hs6)}`;
  const body = `Sayın Yetkili,\n\nFirmamız, GTİP ${dotted(report.hs6)} (${product}) kapsamındaki ürünlerin ihracatını yapmaktadır. `
    + `${nameOf(row)} pazarına giriş çalışmamız kapsamında, bu ürünü ithal eden firmaların listesini ve pazara ilişkin güncel bilgi notunuzu paylaşmanızı rica ederiz.`
    + `\n\nFirma adı:\nYetkili kişi:\nTelefon:\nWeb sitesi:\n\nSaygılarımızla`;
  return `mailto:${office.eposta}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

/* ---------- PDF belgesi ---------- */

const growthText = (g) => (g >= 0 ? "↑ " : "↓ ") + pct(Math.abs(g));

function marketPage(row, index) {
  const suppliers = suppliersOf(row);
  const factors = Object.keys(FACTORS).filter((key) => key in row.z).map((key) => `
    <div><span>${FACTORS[key]}</span><b>${num(row.z[key] * 100, 0)}</b><i><em style="width:${row.z[key] * 100}%"></em></i></div>`).join("");
  return `<section class="pd-section pd-market">
    <div class="pd-market-head">
      <div><div class="pd-kicker">${index + 1}. öneri</div><h2>${esc(nameOf(row))}</h2></div>
      <div class="pd-score"><b>${num(row.score, 0)}</b><span>fırsat skoru</span></div>
    </div>
    <div class="pd-facts">
      <div><span>Pazar büyüklüğü</span><b>${esc(million(row.imports))}</b></div>
      <div><span>Yıllık büyüme</span><b>${esc(growthText(row.G_raw))}</b></div>
      <div><span>Türkiye'nin payı</span><b>${esc(pct(row.tr_share))}</b></div>
      <div><span>Türkiye'nin sırası</span><b>${row.tr_rank ? row.tr_rank + ". / " + row.suppliers : "yok"}</b></div>
      <div><span>Ort. birim fiyat</span><b>${row.unit_price ? esc(num(row.unit_price, 2)) + " $/kg" : "veri yok"}</b></div>
    </div>
    <h3>Değerlendirme</h3>
    <ul class="pd-list">${marketInsights(row).map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
    <div class="pd-cols">
      <div><h3>İthalat, milyon $</h3>${trendChart(row)}</div>
      <div><h3>Tedarikçiler, ${row.year}</h3>
        <table class="pd-table"><thead><tr><th>Ülke</th><th class="pd-n">Pay</th><th class="pd-n">Birim fiyat</th></tr></thead>
        <tbody>${suppliers.map((supplier) => `<tr class="${supplier.turkiye ? "pd-tr" : ""}"><td>${esc(supplier.name)}</td>
          <td class="pd-n">${esc(pct(supplier.share))}</td><td class="pd-n">${supplier.unit_price ? esc(num(supplier.unit_price, 2)) + " $/kg" : "–"}</td></tr>`).join("")}</tbody></table>
      </div>
    </div>
    <h3>Skoru oluşturan faktörler <span>aday ülkeler arasında 0-100</span></h3>
    <div class="pd-factors">${factors}</div>
  </section>`;
}

function entryBlock(row) {
  const now = today(), link = requirementsLink(row, current.hs6);
  return `<div class="pd-entry">
    <h3 class="pd-country">${esc(nameOf(row))}</h3>
    ${row.offices.length ? `<p><b>Ticaret Müşavirliği.</b> ${row.offices.map((office) => `${esc(office.sehir)} (${esc(office.eposta)})`).join(", ")}.
      Bu ofislerden ürününü ithal eden firmaların listesini ve güncel pazar bilgisini talep edebilirsin.</p>`
      : "<p><b>Ticaret Müşavirliği.</b> Bu ülkede Ticaret Bakanlığı'nın müşavirliği ya da ataşeliği bulunmuyor.</p>"}
    ${row.requirements.length ? `<p><b>Olası şartlar.</b></p><ul class="pd-list pd-reqs">${row.requirements.map((item) =>
      `<li><b>${esc(item.baslik)}.</b> ${esc(item.metin)} <span>Kaynak: ${esc(item.kurum)}, ${esc(item.url.replace(/^https?:\/\//, ""))}</span></li>`).join("")}</ul>`
      : "<p><b>Olası şartlar.</b> Bu ülke için hazır bir kontrol listemiz yok; şartları Ticaret Müşavirliği'nden öğrenebilirsin.</p>"}
    ${link ? `<p><b>Resmi AB şart sayfası.</b> ${esc(link)}</p>` : ""}
    ${row.fairs.length ? `<p><b>Destek kapsamındaki ilgili fuarlar.</b></p>
      <table class="pd-table"><thead><tr><th>Fuar</th><th>Şehir</th><th>Tarih</th><th>Konu</th></tr></thead>
      <tbody>${row.fairs.map((fair) => `<tr><td>${esc(fair.ad)}</td><td>${esc(fair.sehir)}</td><td>${esc(fairDates(fair))}${fair.bitis < now ? " (geçti)" : ""}</td><td>${esc(shorten(fair.konu, 60))}</td></tr>`).join("")}</tbody></table>`
      : "<p><b>Destek kapsamındaki ilgili fuarlar.</b> Bu ülkede ürününün sektörüyle eşleşen destekli fuar bulunamadı.</p>"}
  </div>`;
}

function buildDocument(report) {
  const rows = report.rows, path = report.product_path;
  const labels = path ? productLabels(path) : { title: report.product || dotted(report.hs6), sub: "" };
  const total = sumOf(rows, (row) => row.imports), fromTurkiye = sumOf(rows, trExport);
  const today = new Date().toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric" });
  const group = report.growth_basis ? report.growth_basis.slice(0, 2) + "." + report.growth_basis.slice(2) : "";
  const strongholds = [...rows].filter((row) => row.tr_share >= NEGLIGIBLE).sort((a, b) => trExport(b) - trExport(a)).slice(0, 10);

  return `
  <section class="pd-cover">
    <div class="pd-brand"><svg viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#e30a17"/><circle cx="16" cy="16" r="9" fill="none" stroke="#fff" stroke-width="2.4"/><path d="M16 16 22.5 9.5" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/><circle cx="16" cy="16" r="2.2" fill="#fff"/></svg>Fırsat Radarı</div>
    <div class="pd-cover-main">
      <div class="pd-kicker">Pazar fırsat raporu</div>
      <h1>${esc(shorten(labels.title, 130))}</h1>
      ${labels.sub ? `<p>${esc(labels.sub)}</p>` : ""}
    </div>
    <dl class="pd-cover-meta">
      <div><dt>GTİP</dt><dd>${esc(dotted(report.hs6))}</dd></div>
      <div><dt>Veri yılı</dt><dd>${report.t0}</dd></div>
      <div><dt>Aday pazar</dt><dd>${rows.length} ülke</dd></div>
      <div><dt>Hazırlanma tarihi</dt><dd>${esc(today)}</dd></div>
    </dl>
    <div class="pd-cover-foot">Kaynak: UN Comtrade resmi ticaret istatistikleri · T.C. Ticaret Bakanlığı Türk Gümrük Tarife Cetveli 2026</div>
  </section>

  <section class="pd-section">
    <div class="pd-kicker">Bölüm 1</div><h2>Yönetici özeti</h2>
    <div class="pd-facts">
      <div><span>Aday pazarların ithalatı</span><b>${esc(million(total))}</b></div>
      <div><span>Türkiye'nin ihracatı</span><b>${esc(million(fromTurkiye))}</b></div>
      <div><span>Türkiye'nin payı</span><b>${esc(pct(total ? fromTurkiye / total : 0))}</b></div>
      <div><span>Önerilen ilk pazar</span><b>${esc(nameOf(rows[0]))}</b></div>
    </div>
    <div class="pd-insights">${summaryInsights(report).map((item) => `<div><h3>${item.title}</h3><p>${esc(item.text)}</p></div>`).join("")}</div>
  </section>

  <div class="pd-part"><div class="pd-kicker">Bölüm 2</div><h2>Önerilen pazarlar</h2></div>
  ${rows.slice(0, 3).map(marketPage).join("")}

  <section class="pd-section">
    <div class="pd-kicker">Bölüm 3</div><h2>Pazara giriş: ilk adımlar</h2>
    <p class="pd-lead">Önerilen üç pazar için kiminle iletişime geçeceğin ve hangi fuarlarda alıcılarla buluşabileceğin. Fuarlar, konusu ürününün sektörüyle örtüşen ve Ticaret Bakanlığı'nın katılım desteği verdiği fuarlardır.</p>
    ${rows.slice(0, 3).map(entryBlock).join("")}
  </section>

  <section class="pd-section">
    <div class="pd-kicker">Bölüm 4</div><h2>Türkiye'nin mevcut pazarları</h2>
    <p class="pd-lead">Türkiye'nin bu üründe en çok sattığı pazarlar. İhracat değeri, ülkenin bildirdiği ithalat ile Türkiye'nin payından hesaplanmıştır.</p>
    ${strongholds.length ? `<table class="pd-table"><thead><tr><th>Ülke</th><th class="pd-n">Türkiye'nin ihracatı</th><th class="pd-n">Pay</th><th class="pd-n">Sıra</th><th class="pd-n">Pazar büyümesi</th><th class="pd-n">Skor</th></tr></thead>
      <tbody>${strongholds.map((row) => `<tr><td>${esc(nameOf(row))}</td><td class="pd-n">${esc(million(trExport(row)))}</td><td class="pd-n">${esc(pct(row.tr_share))}</td>
        <td class="pd-n">${row.tr_rank}.</td><td class="pd-n">${esc(growthText(row.G_raw))}</td><td class="pd-n">${num(row.score, 0)}</td></tr>`).join("")}</tbody></table>`
      : "<p>Türkiye'nin aday pazarlara kayda değer ihracatı görünmüyor.</p>"}
  </section>

  <section class="pd-section">
    <div class="pd-kicker">Bölüm 5</div><h2>Tüm pazarlar</h2>
    <p class="pd-lead">${rows.length} aday pazar, fırsat skoruna göre sıralı.</p>
    <table class="pd-table pd-all"><thead><tr><th>#</th><th>Ülke</th><th class="pd-n">Skor</th><th class="pd-n">İthalat, mn $</th><th class="pd-n">Yıllık büyüme</th>
      <th class="pd-n">Türkiye payı</th><th class="pd-n">TR sırası</th><th class="pd-n">Birim fiyat, $/kg</th><th>Not</th></tr></thead>
      <tbody>${rows.map((row) => `<tr><td>${row.rank}</td><td>${esc(nameOf(row))}</td><td class="pd-n"><b>${num(row.score, 0)}</b></td>
        <td class="pd-n">${esc(num(row.imports / 1e6))}</td><td class="pd-n">${esc(growthText(row.G_raw))}</td><td class="pd-n">${esc(pct(row.tr_share))}</td>
        <td class="pd-n">${row.tr_rank ? row.tr_rank + "." : "–"}</td><td class="pd-n">${row.unit_price ? esc(num(row.unit_price, 2)) : "–"}</td>
        <td>${[isHub(row) ? "Aktarma" : "", row.kappa < 0.7 ? "Veri zayıf" : ""].filter(Boolean).join(", ")}</td></tr>`).join("")}</tbody></table>
  </section>

  <section class="pd-section">
    <div class="pd-kicker">Bölüm 6</div><h2>Yöntem ve sınırlar</h2>
    <h3>Skor nasıl hesaplanır</h3>
    <p>Fırsat skoru dört ölçünün ağırlıklı toplamıdır: talep büyümesi (%36), pazar büyüklüğü (%29), Türkiye için boşluk (%21) ve pazarın parçalılığı (%14). Her ölçü aday ülkeler arasında 0-100 ölçeğine çekilir. Skor bu ürünün aday ülkeleri arasında göreli bir sıralamadır; farklı ürünlerin skorları karşılaştırılamaz.</p>
    <h3>Bilinmesi gerekenler</h3>
    <ul class="pd-list">
      <li>Veriler ülkelerin bildirdiği resmi ithalat istatistikleridir ve gecikmeli yayımlanır. Bu raporun veri yılı ${report.t0}.</li>
      <li>Analiz ürün kodunun uluslararası ortak olan ilk 6 hanesi üzerinden yapılır; bu, ürününü de içeren daha geniş bir ürün grubudur.</li>
      <li>İthalatı ${esc(million(report.m_min))} altında kalan pazarlar listeye alınmamıştır.</li>
      <li>Küçük pazarlarda ve aktarma merkezlerinde büyüme oranı skora daha az yansıtılır. Tablolardaki büyüme oranı ham veridir.</li>
      <li>Birim fiyat, ithalat değerinin net ağırlığa bölünmesiyle bulunur. Ürün grubu içindeki kalite ve çeşit farkları fiyatı etkiler; ağırlık bildirilmeyen ülkelerde hesaplanamaz.</li>
      <li>Rakip toplamları her pazarın ilk beş tedarikçisinden derlenmiştir, bu yüzden alt sınır niteliğindedir.</li>
      <li>Bu sürümde gümrük vergisi ve lojistik maliyeti skora dahil değildir.</li>
      <li>"Olası şartlar" başlığındaki maddeler ürün grubu ve ülke bloğuna göre hazırlanmış genel bir kontrol listesidir; resmi veri değildir, eksik ya da güncelliğini yitirmiş olabilir. Sevkiyattan önce ilgili kurumdan doğrula.</li>
      <li>Fuarlar, Ticaret Bakanlığı'nın 2026 yılı destek listesinden, konu başlığı ürünün sektörüyle eşleştirilerek seçilmiştir. Katılmadan önce fuarın ürününe uygunluğunu ve güncel tarihini doğrula.</li>
      ${group ? `<li>Bu ürün kodu yakın zamanda tanımlandığı için yıllık büyüme, bağlı olduğu ürün grubunun (${esc(group)}) ithalatından hesaplanmıştır.</li>` : ""}
    </ul>
    <h3>Sorumluluk reddi</h3>
    <p>Bu rapor bilgilendirme amaçlıdır; ticari ya da hukuki tavsiye değildir. Talep verisi satışı garanti etmez. Sertifika şartları, dağıtım kanalları ve alıcı koşulları gibi verinin göstermediği etkenler ayrıca araştırılmalıdır.</p>
  </section>`;
}

// Belgeyi kurar ve yazdırma penceresini açar. Kilitli raporda belge kurulmaz.
function prepareDocument() {
  if (!current || !isUnlocked(current.hs6)) return false;
  $("print-doc").innerHTML = buildDocument(current);
  document.body.classList.add("has-doc");
  return true;
}

function printDocument() {
  if (prepareDocument()) window.print();
}

window.addEventListener("beforeprint", prepareDocument);
window.addEventListener("afterprint", () => document.body.classList.remove("has-doc"));
