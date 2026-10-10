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
  const rows = report.rows.filter((row) => !row.blocked), count = rows.length;
  const total = sumOf(rows, (row) => row.imports), fromTurkiye = sumOf(rows, trExport);
  const share = total ? fromTurkiye / total : 0;
  const bySize = [...rows].sort((a, b) => b.imports - a.imports);
  const large = bySize.slice(0, Math.ceil(count / 2));    // büyük pazarlar: ithalatı ortancanın üzerindekiler
  const insights = [];

  const top = bySize.slice(0, 3);
  insights.push({
    title: "Pazarın büyüklüğü",
    text: `${count} aday pazar ${report.t0} yılında toplam ${million(total)} değerinde ithalat yaptı. En büyük pazarlar `
      + top.map((row) => `${nameOf(row)} (${million(row.imports)})`).join(", ")
      + ` oldu. Bu ${top.length} pazar toplam ithalatın ${pct(sumOf(top, (row) => row.imports) / total)} kadarını oluşturuyor.`,
  });

  const level = share >= 0.5 ? "en büyük tedarikçi" : share >= 0.2 ? "güçlü bir tedarikçi"
    : share >= 0.05 ? "orta ölçekli bir tedarikçi" : "küçük bir tedarikçi";
  const inTopThree = rows.filter((row) => row.tr_rank && row.tr_rank <= 3).length;
  const absent = rows.filter((row) => row.tr_share < NEGLIGIBLE).length;
  insights.push({
    title: "Türkiye'nin konumu",
    text: `Türkiye bu pazarlara yaklaşık ${million(fromTurkiye)} değerinde satış yapıyor ve toplam ithalatın ${pct(share)} kadarını karşılıyor. Bu payla ${level} konumunda. `
      + `Türkiye ${count} pazarın ${inTopThree} tanesinde ilk üç tedarikçi arasında yer alıyor. `
      + (absent ? `${absent} pazarda ise hiç satışı yok ya da payı binde birin altında kalıyor.` : "Pazarların tamamında satışı bulunuyor."),
  });

  if (fromTurkiye > 0) {
    const main = [...rows].sort((a, b) => trExport(b) - trExport(a)).slice(0, 3);
    const concentration = sumOf(main, trExport) / fromTurkiye;
    insights.push({
      title: "İhracatın dağılımı",
      text: `Türkiye'nin bu pazarlara yaptığı ihracatın ${pct(concentration)} kadarı ${main.length} ülkeye gidiyor. Bu ülkeler `
        + main.map((row) => `${nameOf(row)} (${million(trExport(row))})`).join(", ") + " olarak sıralanıyor. "
        + (concentration >= 0.6 ? "İhracat birkaç ülkede toplandığı için bu ülkelerde talep düşerse ihracat doğrudan etkilenir."
          : "İhracat birçok ülkeye dağıldığı için tek bir pazara bağımlılık düşük."),
    });
  }

  const growing = rows.filter((row) => row.G_raw > 0).length;
  const fastest = large.filter((row) => row.G_raw > 0).sort((a, b) => b.G_raw - a.G_raw).slice(0, 3);
  insights.push({
    title: "Talep eğilimi",
    text: `İthalat ${growing} pazarda büyüyor, ${count - growing} pazarda küçülüyor. Pazarların yıllık değişimi ortalama ${pct(median(rows.map((row) => row.G_raw)))} düzeyinde. `
      + (fastest.length ? "Büyük pazarlar arasında en hızlı büyüyenler "
        + fastest.map((row) => `${nameOf(row)} (${pct(row.G_raw)})`).join(", ") + " oldu." : "Büyük pazarların hiçbirinde ithalat büyümüyor."),
  });

  const gaps = large.filter((row) => row.tr_share < 0.05).slice(0, 3);
  insights.push({
    title: "Boş alan",
    text: gaps.length
      ? "Türkiye'nin payının %5'in altında kaldığı büyük pazarlar "
        + gaps.map((row) => `${nameOf(row)} (${million(row.imports)}, Türkiye'nin payı ${pct(row.tr_share)})`).join(", ") + " olarak öne çıkıyor."
      : "Türkiye'nin payı büyük pazarların hepsinde %5'in üzerinde. Bu yüzden büyüme, yeni pazarlardan çok mevcut pazarlarda payı artırarak sağlanabilir.",
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
      text: "Bu pazarlarda Türkiye'nin en güçlü rakipleri "
        + leaders.map(([name, value]) => `${name} (en az ${million(value)}, payı ${pct(value / total)})`).join(", ") + " oldu.",
    });
  }

  const priced = rows.filter((row) => row.tr_unit_price && row.unit_price);
  if (priced.length >= 3) {
    const below = priced.filter((row) => row.tr_unit_price < row.unit_price).length;
    const gap = median(priced.map((row) => row.tr_unit_price / row.unit_price - 1));
    insights.push({
      title: "Fiyat konumu",
      text: `Fiyat verisi bulunan ${priced.length} pazarın ${below} tanesinde Türkiye, pazar ortalamasından daha ucuza satıyor. `
        + (Math.abs(gap) < 0.05 ? "Türkiye'nin fiyatı genel olarak pazar ortalamasına yakın."
          : `Türkiye'nin fiyatı genel olarak pazar ortalamasının ${pct(Math.abs(gap))} ${gap < 0 ? "altında" : "üzerinde"} kalıyor.`),
    });
  }

  insights.push({
    title: "Öne çıkan pazarlar",
    text: "Skoru en yüksek üç pazar "
      + rows.slice(0, 3).map((row) => `${nameOf(row)} (skor ${num(row.score, 0)})`).join(", ") + " oldu. "
      + `Birinci pazar öne çıkıyor çünkü ${whyClause(rows[0])}.`,
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
const RESTRICTION_KINDS = { yasak: "İthalat yasağı", kosullu_yasak: "Koşullu ithalat yasağı", lisans: "İzne bağlı ithalat", kota: "Kota" };

// İthalatın beş yıllık seyri, tek cümle. Kilitli raporda yalnızca bu cümle gösterilir.
function trendLine(row) {
  const points = row.series.filter(([, value]) => value);
  if (points.length < 2) return "";
  const [firstYear, firstValue] = points[0], [lastYear, lastValue] = points[points.length - 1];
  return `İthalat ${firstYear} yılında ${million(firstValue)} iken ${lastYear} yılında ${million(lastValue)} oldu. Yıllık ortalama değişim ${pct(row.G_raw)} olarak gerçekleşti.`;
}

// Satırlar düz metindir; uyarı olanlar lines.warnings kümesinde de tutulur (ekranda sarı gösterilir).
function marketInsights(row) {
  const lines = [];
  lines.warnings = new Set();
  const warn = (text) => { lines.push(text); lines.warnings.add(text); };
  if (row.blocked) warn("Türkiye bu ülkeyle ticareti durdurdu. Bu yüzden pazar puanlanmadı ve sıralamaya alınmadı. Güncel durumu Ticaret Bakanlığı'ndan öğrenebilirsin.");
  const trend = trendLine(row);
  if (trend) lines.push(trend);

  const suppliers = suppliersOf(row), leader = suppliers[0], hhi = 1 - row.F;
  const topShare = sumOf(suppliers.slice(0, 3), (supplier) => supplier.share);
  lines.push(`Pazarın en büyük tedarikçisi ${leader.name} (payı ${pct(leader.share)}). İlk üç tedarikçi ithalatın ${pct(topShare)} kadarını karşılıyor. `
    + (hhi > 0.4 ? "Pazar birkaç tedarikçinin elinde olduğu için yeni bir satıcının girmesi zor olabilir."
      : hhi < 0.2 ? "Pazarda çok sayıda tedarikçi olduğu için yeni bir satıcıya yer var." : "Pazarda rekabet orta düzeyde."));

  lines.push(row.tr_share < NEGLIGIBLE
    ? "Türkiye bu pazara satış yapmıyor ya da payı binde birin altında kalıyor."
    : `Türkiye ${row.suppliers} tedarikçi arasında ${row.tr_rank}. sırada yer alıyor ve payı ${pct(row.tr_share)}.`);

  if (row.tr_unit_price && row.unit_price) {
    const gap = row.tr_unit_price / row.unit_price - 1;
    lines.push(`Türkiye'nin birim fiyatı ${num(row.tr_unit_price, 2)} $/kg, pazar ortalaması ise ${num(row.unit_price, 2)} $/kg. `
      + (Math.abs(gap) < 0.02 ? "Türkiye'nin fiyatı ortalamayla aynı düzeyde." : `Türkiye'nin fiyatı ortalamanın ${pct(Math.abs(gap))} ${gap < 0 ? "altında" : "üzerinde"}.`)
      + (!leader.turkiye && leader.unit_price ? ` En büyük tedarikçinin fiyatı ${num(leader.unit_price, 2)} $/kg.` : ""));
  } else if (row.unit_price) {
    lines.push(`Bu pazarda ortalama ithalat fiyatı ${num(row.unit_price, 2)} $/kg.`);
  }

  const duty = dutyInfo(row);
  if (duty) lines.push(duty.sentence);

  // Geniş kapsamlı önlemler (ör. cıva içeren her ürün) çoğu ürünü ilgilendirmez; uyarı yalnızca ürüne özgü olanlar için verilir.
  const specific = row.restrictions.filter((item) => !item.genis);
  if (specific.length) {
    const kinds = [...new Set(specific.flatMap((item) => item.tur))].map((kind) => RESTRICTION_KINDS[kind].toLocaleLowerCase("tr-TR"));
    warn(`Bu ülke, ürününün de içinde olduğu bir ürün grubu için Dünya Ticaret Örgütü'ne kısıtlama bildirmiş (${kinds.join(", ")}). Kısıtlamanın senin ürününü kapsayıp kapsamadığını sevkiyattan önce öğrenmelisin.`);
  }
  if (isNetExporter(row)) warn("Bu ülke, bu üründe ithal ettiği kadarını ya da daha fazlasını ihraç ediyor. Ülke üretici ya da aktarma merkezi olabilir. Bu yüzden ithalattaki artış iç talebin arttığını göstermeyebilir.");
  else if (isHub(row)) warn(`Bu ülke ithal ettiği ürünün ${pct(row.reexport)} kadarını yeniden ihraç ediyor. İthalatın bir kısmı başka ülkelere gönderiliyor olabilir.`);
  else if (row.growth_trust < 0.5) warn("Bu pazar küçük olduğu için birkaç sevkiyat bile büyüme oranını önemli ölçüde değiştirebilir.");
  if (row.kappa < 0.7) warn("Bu ülkenin verileri eksik ya da gecikmeli olduğu için rakamlara dikkatle yaklaşmalısın.");
  return lines;
}

/* ---------- Gümrük vergisi (DTÖ) ---------- */

// Oranlar yüzde puandır (8 = %8). Veri yoksa null.
function dutyInfo(row) {
  const duty = row.tariff;
  if (!duty) return null;
  const rate = (value) => "%" + num(value, value % 1 ? 1 : 0);
  const applied = duty.tr === null ? duty.mfn : duty.tr;
  const basis = duty.tur === "anlasma" ? "ticaret anlaşması kapsamında" : duty.tur === "gsp" ? "gelişmekte olan ülkelere tanınan indirim kapsamında" : "";
  const note = duty.sta_eksik
    ? "Bu ülkenin Türkiye ile serbest ticaret anlaşması var ancak anlaşmalı oran Dünya Ticaret Örgütü verilerinde yer almıyor. Gerçek oran daha düşük olabilir."
    : duty.tur ? "İndirimli orandan yararlanmak için menşe belgesi gerekir." : "";
  const sentence = duty.tr !== null && duty.tr < duty.mfn
    ? `Türkiye'den gelen ürüne ${basis ? basis + " " : ""}${rate(duty.tr)} gümrük vergisi uygulanıyor. Genel oran ise ${rate(duty.mfn)}. Aradaki fark, anlaşması olmayan rakiplere karşı fiyat avantajı sağlar.`
    : duty.sta_eksik ? `Genel gümrük vergisi oranı ${rate(duty.mfn)}. ${note}`
      : applied === 0 ? "Bu ürün ülkeye gümrük vergisi ödenmeden giriyor." : `Bu ürüne ${rate(applied)} gümrük vergisi uygulanıyor. Türkiye'ye özel bir indirim bulunmuyor.`;
  return { applied: rate(applied), general: rate(duty.mfn), year: duty.yil, basis, note, sentence };
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

/* ---------- Sonraki adımlar: ilk sıradaki pazar için yol haritası ---------- */

const SUPPORT_URL = "https://ticaret.gov.tr/destekler";

// onScreen: ekrandaki düğmelere gönderme yapılır; PDF'te bu cümleler yer almaz.
function nextSteps(report, onScreen = true) {
  const row = report.rows[0], name = nameOf(row), now = today(), office = row.offices[0];
  const upcoming = row.fairs.find((fair) => fair.bitis >= now), anyFair = row.fairs[0];
  return [
    { title: "Pazarı doğrula", text: `${name} en yüksek skoru aldı. Karar vermeden önce ilk üç pazarın detaylarına bak. Oradaki birim fiyatları kendi fiyatınla, tedarikçileri de kendi rakiplerinle karşılaştır.` },
    { title: "Şartları netleştir", text: row.requirements.length
      ? `${name} için ${row.requirements.length} olası şart listelendi. Her birini ilgili kurumdan doğrulaman gerekir. Belge ve test işlemleri haftalarca sürebildiği için işe buradan başlamanı öneririz.`
      : `${name} için hazır bir şart listemiz bulunmuyor. Belge ve etiket şartlarını Ticaret Müşavirliği'nden ve görüştüğün alıcılardan öğrenebilirsin.` },
    { title: "Müşavirliğe yaz", text: office
      ? `${office.sehir} Ticaret Müşavirliği'nden (${office.eposta}) bu ürünü ithal eden firmaların listesini isteyebilirsin. Bu hizmet ücretsizdir.${onScreen ? ' Ülke detayındaki "İthalatçı listesi iste" düğmesine bastığında e-posta hazır olarak açılır.' : ""}`
      : `Ticaret Bakanlığı'nın ${name} ülkesinde müşavirliği ya da ataşeliği bulunmuyor. Bu bölgeye bakan en yakın müşavirliği Bakanlığın yurt dışı teşkilatı sayfasından bulabilirsin.` },
    { title: "Fuarı takvime koy", text: upcoming
      ? `${upcoming.ad} fuarı (${upcoming.sehir}, ${fairDates(upcoming)}) Ticaret Bakanlığı'nın destek listesinde yer alıyor. Stant açmadan önce fuara ziyaretçi olarak gidersen alıcıları ve rakiplerin fiyatlarını düşük maliyetle görebilirsin.`
      : anyFair ? `Bu yılın ilgili fuarları sona erdi (örneğin ${anyFair.ad}, ${anyFair.sehir}). Fuarların çoğu her yıl tekrarlandığı için gelecek yılın tarihlerini ve destek listesini takip edebilirsin.`
      : `Destek listesinde ${name} için ürününün sektörüne uygun bir fuar bulunamadı. Komşu ülkelerdeki sektör fuarlarında aynı alıcılara ulaşabilirsin.` },
    { title: "Devlet desteğine bak", text: `Ticaret Bakanlığı fuar katılımı, yurt dışı pazar araştırması ve tanıtım giderleri için destek veriyor. Harcama yapmadan önce başvuru koşullarını ve sürelerini ${SUPPORT_URL.replace("https://", "")} adresinden öğrenebilirsin.` },
    { title: "Alıcıya ulaş", text: "Bu rapor hangi ülkeye satacağını seçmene yardımcı olur ancak firma adı vermez. Alıcı bulmak için müşavirliğin göndereceği listeden ve fuarların katılımcı rehberlerinden yararlanabilirsin." },
  ];
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
      <div><span>Türkiye'ye uzaklık</span><b>${row.distance_km ? esc(num(Math.round(row.distance_km / 50) * 50, 0)) + " km" : "veri yok"}</b></div>
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
      : "<p><b>Olası şartlar.</b> Bu ülke için hazır bir şart listemiz bulunmuyor. Şartları Ticaret Müşavirliği'nden öğrenebilirsin.</p>"}
    ${link ? `<p><b>Resmi AB şart sayfası.</b> ${esc(link)}</p>` : ""}
    ${row.restrictions.length ? `<p><b>DTÖ'ye bildirilen ithalat kısıtlaması.</b></p><ul class="pd-list pd-reqs">${row.restrictions.map((item) =>
      `<li><b>${esc(item.tur.map((kind) => RESTRICTION_KINDS[kind]).join(", "))}.</b> ${esc(item.metin_tr || shorten(item.metin, 260))}${item.belge ? ` <span>Kaynak: ${esc(item.belge.replace(/^https?:\/\//, "").slice(0, 90))}</span>` : ""}</li>`).join("")}</ul>` : ""}
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
    <div class="pd-brand"><svg viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#e30a17"/><circle cx="16" cy="16" r="9" fill="none" stroke="#fff" stroke-width="2.4"/><path d="M16 16 22.5 9.5" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/><circle cx="16" cy="16" r="2.2" fill="#fff"/></svg><svg class="wordmark" aria-label="İhraçbul"><use href="#yazi"/></svg></div>
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
    <div class="pd-cover-foot">Kaynak: UN Comtrade resmi ticaret istatistikleri · Dünya Ticaret Örgütü tarife verisi · T.C. Ticaret Bakanlığı Türk Gümrük Tarife Cetveli 2026</div>
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
        <td class="pd-n">${row.tr_rank}.</td><td class="pd-n">${esc(growthText(row.G_raw))}</td><td class="pd-n">${row.blocked ? "–" : num(row.score, 0)}</td></tr>`).join("")}</tbody></table>`
      : "<p>Türkiye'nin aday pazarlara kayda değer ihracatı görünmüyor.</p>"}
  </section>

  <section class="pd-section">
    <div class="pd-kicker">Bölüm 5</div><h2>Tüm pazarlar</h2>
    <p class="pd-lead">${rows.length} aday pazar, fırsat skoruna göre sıralı.</p>
    <table class="pd-table pd-all"><thead><tr><th>#</th><th>Ülke</th><th class="pd-n">Skor</th><th class="pd-n">İthalat, mn $</th><th class="pd-n">Yıllık büyüme</th>
      <th class="pd-n">Türkiye payı</th><th class="pd-n">TR sırası</th><th class="pd-n">Birim fiyat, $/kg</th><th>Not</th></tr></thead>
      <tbody>${rows.map((row) => `<tr><td>${row.rank}</td><td>${esc(nameOf(row))}</td><td class="pd-n"><b>${row.blocked ? "–" : num(row.score, 0)}</b></td>
        <td class="pd-n">${esc(num(row.imports / 1e6))}</td><td class="pd-n">${esc(growthText(row.G_raw))}</td><td class="pd-n">${esc(pct(row.tr_share))}</td>
        <td class="pd-n">${row.tr_rank ? row.tr_rank + "." : "–"}</td><td class="pd-n">${row.unit_price ? esc(num(row.unit_price, 2)) : "–"}</td>
        <td>${[row.blocked ? "Ticaret durdu" : "", row.restrictions.some((item) => !item.genis) ? "Kısıtlama" : "", isNetExporter(row) ? "Net ihracatçı" : "", row.kappa < 0.7 ? "Veri zayıf" : ""].filter(Boolean).join(", ")}</td></tr>`).join("")}</tbody></table>
  </section>

  <section class="pd-section">
    <div class="pd-kicker">Bölüm 6</div><h2>Sonraki adımlar</h2>
    <p class="pd-lead">İlk sıradaki pazar olan ${esc(nameOf(rows[0]))} için sırayla yapılacaklar. Diğer pazarlar için aynı sıra izlenebilir.</p>
    <div class="pd-insights">${nextSteps(report, false).map((item, index) => `<div><h3>${index + 1}. ${item.title}</h3><p>${esc(item.text)}</p></div>`).join("")}</div>
  </section>

  <section class="pd-section">
    <div class="pd-kicker">Bölüm 7</div><h2>Yöntem ve sınırlar</h2>
    <h3>Skor nasıl hesaplanır</h3>
    <p>${report.tariffs ? "Fırsat skoru altı ölçünün ağırlıklı toplamıdır. Bu ölçüler Türkiye'ye yakınlık (%30), Türkiye için boşluk (%25), pazar büyüklüğü (%20), gümrük vergisi (%10), pazarın parçalılığı (%10) ve talep büyümesidir (%5). Ağırlıklar geçmiş yılların verileriyle sınanarak belirlenmiştir." : "Bu raporda gümrük vergisi verisi alınamadığı için skor beş ölçüyle hesaplandı. Bu ölçüler Türkiye'ye yakınlık (%33), Türkiye için boşluk (%28), pazar büyüklüğü (%22), pazarın parçalılığı (%11) ve talep büyümesidir (%6)."} Her ölçü aday ülkeler arasında 0-100 ölçeğine çekilir. Skor bu ürünün aday ülkeleri arasında göreli bir sıralamadır; farklı ürünlerin skorları karşılaştırılamaz.</p>
    <h3>Bilinmesi gerekenler</h3>
    <ul class="pd-list">
      <li>Veriler ülkelerin bildirdiği resmi ithalat istatistikleridir ve gecikmeli yayımlanır. Bu raporun veri yılı ${report.t0}.</li>
      <li>Analiz ürün kodunun uluslararası ortak olan ilk 6 hanesi üzerinden yapılır; bu, ürününü de içeren daha geniş bir ürün grubudur.</li>
      <li>İthalatı ${esc(million(report.m_min))} altında kalan pazarlar listeye alınmamıştır.</li>
      <li>Küçük pazarlarda ve aktarma merkezlerinde büyüme oranı skora daha az yansıtılır. Tablolardaki büyüme oranı ham veridir.</li>
      <li>Birim fiyat, ithalat değerinin net ağırlığa bölünmesiyle bulunur. Ürün grubu içindeki kalite ve çeşit farkları fiyatı etkiler; ağırlık bildirilmeyen ülkelerde hesaplanamaz.</li>
      <li>Rakip toplamları her pazarın ilk beş tedarikçisinden derlenmiştir, bu yüzden alt sınır niteliğindedir.</li>
      <li>Gümrük vergisi Dünya Ticaret Örgütü'ne bildirilen oranlardır ve yalnızca yüzde olarak tanımlı vergileri kapsar. Kilo başına vergiler, ek vergiler, damping önlemleri ve kotalar bu veride yoktur; oranı bilinmeyen ülke skorda ortalama kabul edilir. Sevkiyattan önce güncel oranı alıcı ülkenin gümrüğünden doğrula.</li>
      <li>İthalat kısıtlamaları, ülkelerin DTÖ'ye bildirdiği yürürlükteki yasak, lisans ve kotalardır. Her ülke bildirim yapmaz; listede kısıtlama görünmemesi kısıtlama olmadığı anlamına gelmez. Kısıtlamalar skoru etkilemez, uyarı olarak gösterilir.</li>
      <li>Türkiye'nin ticareti durdurduğu ülkeler skorlanmaz ve tablonun sonunda yer alır.</li>
      <li>Lojistik, Türkiye'ye kuş uçuşu uzaklıkla ölçülür; navlun fiyatını, sınır bekleme süresini ya da taşıma yolunu yansıtmaz.</li>
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
  if (!isOpen()) return false;
  $("print-doc").innerHTML = buildDocument(current);
  document.body.classList.add("has-doc");
  return true;
}

function printDocument() {
  if (prepareDocument()) window.print();
}

window.addEventListener("beforeprint", prepareDocument);
window.addEventListener("afterprint", () => document.body.classList.remove("has-doc"));
