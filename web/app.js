"use strict";

const regionNames = new Intl.DisplayNames(["tr"], { type: "region" });
const FACTORS = { L: "Türkiye'ye yakınlık", H: "Türkiye için boşluk", A: "Pazar büyüklüğü", T: "Gümrük vergisi", F: "Pazarın parçalılığı", G: "Talep büyümesi" };
const REASONS = {
  G: "talep hızlı büyüyor", A: "pazar büyük", T: "gümrük vergisi düşük", L: "ülke Türkiye'ye yakın",
  H: "Türkiye'nin payını artırabileceği alan geniş", F: "pazar tek bir tedarikçiye bağlı değil",
};
const VISIBLE_ROWS = 20;
const LOCKED_ROWS = 9;                    // kilitli önizlemede gösterilen boş satır sayısı
const PRICES = { single: 490, pro: 999, yearly: 9000 };   // TL; tek rapor tek seferlik, Pro aylık, Pro yıllık (tek ödeme)
PRICES.perMonth = PRICES.yearly / 12;                    // yıllık planın aylık karşılığı
const TITLE = document.title;
const LOCK_ICON = '<svg class="lock-ico" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="4" y="9" width="12" height="8" rx="2"/><path d="M7 9V6.5a3 3 0 0 1 6 0V9"/></svg>';

const $ = (id) => document.getElementById(id);
const esc = (text) => String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (value, digits = 1) => value.toLocaleString("tr-TR", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const pct = (share) => (share < 0 ? "-%" : "%") + num(Math.abs(share) * 100);
const million = (usd) => (usd >= 1e9 ? num(usd / 1e9, 2) + " mr $" : num(usd / 1e6) + " mn $");
const dotted = (hs6) => hs6.slice(0, 4) + "." + hs6.slice(4);
const shorten = (text, max = 90) => (text.length > max ? text.slice(0, max).trimEnd() + "…" : text);

// Tarife yolundan okunur bir başlık ve alt satır çıkarır. Yolun ilk halkası pozisyon başlığıdır.
// Alt halkalar "Diğerleri" gibi tek başına anlamsızsa başlık pozisyondan, değilse ürünün kendi adından gelir.
function productLabels(path) {
  const heading = path[0].split(" (")[0], rest = path.slice(1).join(" › ");
  if (path.length === 1) return { title: path[0], sub: "" };
  if (path.length === 2) return { title: heading + " › " + path[1], sub: "" };
  return path.slice(1).some((part) => /^Diğer/.test(part)) ? { title: heading, sub: rest } : { title: rest, sub: path[0] };
}

// Comtrade'in ülke olmayan kalemleri: ISO kodu yok, adları elle çevrilir.
const SPECIAL_AREAS = {
  "Other Asia, nes": "Diğer Asya (belirtilmemiş)", "Areas, nes": "Belirtilmemiş bölgeler",
  "Bunkers": "Gemi ve uçak ikmali", "Free Zones": "Serbest bölgeler", "Special Categories": "Özel kategoriler",
};

function countryName(iso2, fallback) {
  try {
    if (/^[A-Z]{2}$/.test(iso2 || "")) return regionNames.of(iso2);
  } catch (error) { /* bilinmeyen kod */ }
  return SPECIAL_AREAS[fallback] || fallback;
}

const nameOf = (row) => countryName(row.iso2, row.country);
const isoTag = (iso2) => `<span class="iso">${/^[A-Z]{2}$/.test(iso2 || "") ? iso2 : ""}</span>`;
const confidenceLabel = (kappa) => (kappa >= 0.7 ? "Yüksek" : "Orta");
// Yön hem renkle hem okla gösterilir.
const growthCell = (g) => `<span class="${g >= 0 ? "up" : "down"}">${g >= 0 ? "▲" : "▼"} ${esc(pct(Math.abs(g)))}</span>`;
const scoreCell = (score) => `<span class="score">${num(score, 0)}<i><b style="width:${score}%"></b></i></span>`;
// İthal ettiği ürünün en az yarısı kadarını ihraç eden ülke: üretici ya da aktarma merkezi. Rozet yalnızca
// ihracatı ithalatını yakalayan (net ihracatçı) ülkelerde gösterilir; arası yalnızca değerlendirmede anılır.
const isHub = (row) => row.reexport >= 0.5;
const isNetExporter = (row) => row.reexport >= 0.999;

// İlk üç pazarın tek cümlelik gerekçesi: en güçlü iki faktör.
// Pazarın öne çıkma nedeni, cümle içinde kullanılacak biçimde (küçük harfle başlar, noktasız).
function whyClause(row) {
  const ranked = Object.keys(REASONS).filter((key) => key in row.z).sort((a, b) => row.z[b] - row.z[a]);
  const strong = ranked.filter((key) => row.z[key] >= 0.6).slice(0, 2);
  return (strong.length ? strong : ranked.slice(0, 1)).map((key) => REASONS[key]).join(" ve ");
}

function whyText(row) {
  const text = whyClause(row);
  return text.charAt(0).toLocaleUpperCase("tr-TR") + text.slice(1) + ".";
}

/* ---------- Erişim (demo) ---------- */

// Haklar sunucunun imzaladığı bir belirteçte durur; tarayıcı yalnızca saklar ve her rapor isteğiyle geri gönderir.
// Kilitli raporun verisi tarayıcıya hiç gelmez. Ödeme şimdilik gösterimdir: belirteç para alınmadan verilir.
const access = { email: "", pro: false, pro_until: 0, reports: [], token: "", ad: "", firma: "", sifre_var: false };
try {
  Object.assign(access, JSON.parse(localStorage.getItem("fr-erisim")) || {});
} catch (error) { /* depolama kapalıysa ücretsiz planla devam */ }
if (!access.token) Object.assign(access, { email: "", pro: false, pro_until: 0, reports: [] });   // belirteçsiz eski kayıt geçersizdir

function saveAccess() {
  try { localStorage.setItem("fr-erisim", JSON.stringify(access)); } catch (error) { /* yalnızca bu oturumda geçerli olur */ }
  renderPlan();
}

const isOpen = () => Boolean(current) && !current.kilitli;      // ekrandaki rapor tam mı (sunucunun kararı)

function renderPlan() {
  $("account").textContent = access.ad || access.email || "Giriş yap";
  $("account").title = access.email ? "Hesabım" : "";
  $("plan").textContent = access.pro ? "Pro" : "Ücretsiz plan";
  $("plan").classList.toggle("pro", access.pro);
  const buyPro = $("buy-pro");
  buyPro.textContent = access.pro ? "Aktif plan" : "Satın al";
  buyPro.disabled = access.pro;
  document.querySelectorAll("[data-price]").forEach((node) => { node.textContent = num(PRICES[node.dataset.price], 0); });
  renderBilling();
}

// Pro kartındaki ödeme dönemi: yıllık (varsayılan) ya da aylık.
let billing = "yearly";

function renderBilling() {
  const yearly = billing === "yearly";
  document.querySelectorAll("[data-billing]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.billing === billing)));
  $("pro-price").textContent = num(yearly ? PRICES.perMonth : PRICES.pro, 0);
  $("pro-note").textContent = yearly
    ? `Yılda bir kez ${num(PRICES.yearly, 0)} TL ödenir. Aylık plana göre ${num(PRICES.pro * 12 - PRICES.yearly, 0)} TL daha ucuzdur. Yıllık ödeme iade edilmez.`
    : `Her ay yenilenir. Yıllık planda aylık ücret ${num(PRICES.perMonth, 0)} TL'ye düşer.`;
  $("pro-cancel").textContent = yearly ? "Bir yıl boyunca sabit fiyat" : "İstediğin zaman iptal edebilirsin";
  $("bill-save").textContent = "%" + Math.round((1 - PRICES.yearly / (PRICES.pro * 12)) * 100) + " indirim";
  $("buy-pro").dataset.buy = billing;
}

/* ---------- Rapor ---------- */

let current = null;                       // ekrandaki rapor
let sort = { key: "score", dir: -1 };
let showAll = false;
let selected = null;                      // sağ panelde detayı gösterilen ülke kodu

function trendChart(row) {
  const width = 368, height = 150, top = 20, bottom = 22, slot = width / row.series.length, barWidth = 38;
  const max = Math.max(...row.series.map(([, value]) => value || 0));
  const plot = height - top - bottom;
  let marks = "";
  row.series.forEach(([year, value], index) => {
    const centre = slot * index + slot / 2, last = index === row.series.length - 1;
    marks += `<text x="${centre}" y="${height - 6}" text-anchor="middle">${year}</text>`;
    if (!value) {
      marks += `<text x="${centre}" y="${height - bottom - 6}" text-anchor="middle">veri yok</text>`;
      return;
    }
    const h = Math.max(2, plot * value / max), x = centre - barWidth / 2, y = top + plot - h, r = Math.min(3, h);
    marks += `<path class="bar${last ? " last" : ""}" data-tip="${year}: ${esc(million(value))}" d="M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + barWidth - r}Q${x + barWidth},${y} ${x + barWidth},${y + r}V${y + h}Z"/>`;
    if (last) marks += `<text x="${centre}" y="${y - 6}" text-anchor="middle">${esc(num(value / 1e6))}</text>`;
  });
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" role="img" aria-label="Yıllara göre ithalat">
    ${marks}<line class="axis" x1="0" x2="${width}" y1="${height - bottom}" y2="${height - bottom}"/></svg>`;
}

function hbar(label, share, text, cls = "") {
  return `<div class="hbar ${cls}" data-tip="${esc(label)}: ${esc(text)}"><span>${esc(label)}</span><i><b style="width:${Math.min(100, share * 100)}%"></b></i><em>${esc(text)}</em></div>`;
}

// Ülke detayının pazara giriş ve vergi parçaları: { limits, duty, entry }. Hangi sekmede duracaklarına renderDetail karar verir.
function entryParts(row) {
  const now = today(), link = requirementsLink(row, current.hs6);
  const offices = row.offices.length
    ? `<ul class="contacts">${row.offices.map((office) => `<li><span>${esc(office.sehir)}</span><a href="mailto:${esc(office.eposta)}">${esc(office.eposta)}</a></li>`).join("")}</ul>
       <a class="ghost wide" href="${esc(importerRequestLink(row.offices[0], row, current))}">İthalatçı listesi iste</a>
       <div class="sub">Düğmeye bastığında hazır bir e-posta açılır. Bu e-postayla müşavirlikten ürününü ithal eden firmaların listesini isteyebilirsin.</div>`
    : '<div class="sub">Bu ülkede Ticaret Bakanlığı\'nın müşavirliği ya da ataşeliği bulunmuyor.</div>';
  const fairs = row.fairs.length
    ? `<ul class="fairs">${row.fairs.map((fair) => `<li class="${fair.bitis < now ? "past" : ""}"><b>${esc(fair.ad)}</b>
        <span>${esc(fair.sehir)} · ${esc(fairDates(fair))}${fair.bitis < now ? " · geçti" : ""}</span><small>${esc(shorten(fair.konu.toLocaleLowerCase("tr-TR"), 70))}</small></li>`).join("")}</ul>`
    : '<div class="sub">Bu ülkede ürününün sektörüne uygun destekli bir fuar bulunamadı.</div>';
  const limits = row.restrictions.length ? `<div class="d-sec"><h3>Bildirilen ithalat kısıtlaması <span>DTÖ</span></h3>
      <ul class="reqs limits">${row.restrictions.map((item) => `<li><b>${esc(item.tur.map((kind) => RESTRICTION_KINDS[kind]).join(", "))}</b><p>${esc(item.metin_tr || shorten(item.metin, 260))}${item.genis ? " <em>Geniş bir ürün grubunu kapsıyor.</em>" : ""}</p>
        ${item.metin_tr ? `<small>Özgün ifade: ${esc(shorten(item.metin, 200))}</small>` : ""}
        ${item.belge ? `<a href="${esc(item.belge)}" target="_blank" rel="noopener">DTÖ bildirimi ↗</a>` : ""}</li>`).join("")}</ul>
      </div>` : "";
  const duty = dutyInfo(row);
  const duties = duty
    ? `<ul class="contacts duty"><li><span>Türkiye menşeli ürüne</span><b>${esc(duty.applied)}</b></li><li><span>Genel oran</span><b>${esc(duty.general)}</b></li></ul>
       ${duty.basis || duty.note ? `<div class="sub">${esc([duty.basis && "Bu oran " + duty.basis + " uygulanır.", duty.note].filter(Boolean).join(" "))}</div>` : ""}`
    : '<div class="sub">Bu ülke için yüzde olarak belirlenmiş bir vergi oranı bulunamadı. Vergi kilo başına hesaplanıyor olabilir ya da ülke oranını bildirmemiş olabilir.</div>';
  return { limits, duty: `<div class="d-sec"><h3>Gümrük vergisi <span>${duty ? "DTÖ, " + duty.year : "DTÖ"}</span></h3>${duties}</div>`,
    entry: `<div class="d-sec"><h3>Ticaret Müşavirliği <span>T.C. Ticaret Bakanlığı</span></h3>${offices}</div>
    <div class="d-sec"><h3>İlgili destekli fuarlar <span>2026</span></h3>${fairs}</div>
    <div class="d-sec"><h3>Olası şartlar <span>kontrol listesi</span></h3>
      ${row.requirements.length ? `<ul class="reqs">${row.requirements.map((item) => `<li><b>${esc(item.baslik)}</b><p>${esc(item.metin)}</p>
        <a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.kurum)} ↗</a></li>`).join("")}</ul>`
        : '<div class="sub">Bu ülke için hazır bir şart listemiz bulunmuyor. Şartları Ticaret Müşavirliği\'nden öğrenebilirsin.</div>'}
      ${link ? `<a class="ghost wide" href="${esc(link)}" target="_blank" rel="noopener">Bu ürünün resmi AB şartlarını gör ↗</a>` : ""}
    </div>` };
}

// Ülke detayı üç sekmedir; seçili sekme başka ülkeye geçince de korunur.
const DETAIL_TABS = [["ozet", "Özet"], ["rakip", "Rakipler"], ["giris", "Pazara giriş"]];
let detailTab = "ozet";

// Ücretsiz planda ülke detayı kapalıdır: başlık ve tek cümlelik özet görünür, gerisi kilitlidir.
const LOCKED_DETAIL = ["Beş yıllık ithalat grafiği ve eğilim", "Rakipler, payları ve birim fiyatları", "Gümrük vergisi ve Türkiye'ye tanınan oran",
  "Ticaret Müşavirliği, fuarlar ve şartlar", "Altı ölçünün her birinden aldığı puan"];

function insightItems(row) {
  const lines = marketInsights(row);
  return lines.map((line) => `<li class="${lines.warnings.has(line) ? "warn" : ""}">${esc(line)}</li>`).join("");
}

function renderLockedDetail(row) {
  $("detail").innerHTML = `
    <div class="d-head">
      <div class="name">${esc(nameOf(row))}<small>${row.rank}. sıra · ${esc(million(row.imports))} pazar · ${growthCell(row.G_raw)}</small></div>
      <div class="big">${num(row.score, 0)}<small>Skor</small></div>
    </div>
    <div class="d-sec"><h3>Değerlendirme</h3><ul class="notes"><li>${esc(trendLine(row))}</li></ul></div>
    <div class="d-sec d-locked">
      <div class="big-lock">${LOCK_ICON.replace(' class="lock-ico"', "")}</div>
      <h3>Bu pazarın detayı tam raporda</h3>
      <ul>${LOCKED_DETAIL.map((item) => `<li>${item}</li>`).join("")}</ul>
      <button type="button" class="go wide" data-buy="single">Bu raporu aç · ${num(PRICES.single, 0)} TL</button>
      <button type="button" class="ghost wide" data-buy="yearly">Pro'ya geç · ayda ${num(PRICES.perMonth, 0)} TL'den</button>
    </div>`;
}

function renderDetail() {
  const row = current.rows.find((item) => item.code === selected);
  if (!isOpen()) return renderLockedDetail(row);
  const suppliers = suppliersOf(row);
  const factors = Object.keys(FACTORS).filter((key) => key in row.z)
    .map((key) => hbar(FACTORS[key], row.z[key], num(row.z[key] * 100, 0), "factor")).join("");
  const parts = entryParts(row);
  const priced = suppliers.filter((supplier) => supplier.unit_price);
  const prices = priced.length ? `<div class="d-sec"><h3>Birim fiyat <span>$/kg</span></h3>
      <ul class="contacts duty">${priced.map((supplier) => `<li><span${supplier.turkiye ? ' class="tr"' : ""}>${esc(supplier.name)}</span><b>${esc(num(supplier.unit_price, 2))}</b></li>`).join("")}
        ${row.unit_price ? `<li><span>Pazar ortalaması</span><b>${esc(num(row.unit_price, 2))}</b></li>` : ""}</ul></div>` : "";
  const panels = {
    ozet: `<div class="d-sec"><h3>Değerlendirme</h3><ul class="notes">${insightItems(row)}</ul></div>
      <div class="d-sec"><h3>İthalat, milyon $</h3>${trendChart(row)}</div>
      ${row.blocked ? "" : `<div class="d-sec"><h3>Neden bu sırada <span>0-100</span></h3>${factors}<div class="sub">Her ölçü, ülkeler birbiriyle karşılaştırılarak puanlanır. Bu ülkenin veri güveni ${confidenceLabel(row.kappa).toLowerCase()} düzeydedir.</div></div>`}`,
    rakip: `<div class="d-sec"><h3>Tedarikçi payları <span>${row.year}</span></h3>${suppliers.map((supplier) => hbar(supplier.name, supplier.share, pct(supplier.share), supplier.turkiye ? "tr" : "")).join("")}</div>
      ${prices}${parts.duty}`,
    giris: `${parts.limits}${parts.entry}
      <div class="d-sec d-foot">Vergi, kısıtlama ve şart bilgileri genel bilgilendirmedir. Sevkiyattan önce alıcı ülkenin gümrüğünden ve alıcından doğrula.</div>`,
  };
  const alert = row.restrictions.some((item) => !item.genis);
  $("detail").innerHTML = `
    <div class="d-head">
      <div class="name">${esc(nameOf(row))}<small>${row.rank}. sıra · ${esc(million(row.imports))} pazar · ${growthCell(row.G_raw)}</small></div>
      <div class="big">${row.blocked ? "–" : num(row.score, 0)}<small>Skor</small></div>
    </div>
    <div class="d-tabs" role="tablist" aria-label="Ülke detayı">${DETAIL_TABS.map(([key, label]) =>
      `<button type="button" role="tab" data-tab="${key}" aria-selected="${key === detailTab}">${label}${key === "giris" && alert ? '<i title="Bildirilen kısıtlama var"></i>' : ""}</button>`).join("")}</div>
    <div role="tabpanel">${panels[detailTab]}</div>`;
}

const COLUMNS = [
  { key: "score", label: "Skor" },
  { key: "imports", label: "İthalat, mn $" },
  { key: "G_raw", label: "Yıllık büyüme" },
  { key: "tr_share", label: "Türkiye payı", cls: "col-share" },
];

const rowHtml = (row) => `
    <tr class="row${row.code === selected ? " selected" : ""}" data-code="${row.code}" tabindex="0" aria-selected="${row.code === selected}">
      <td>${row.rank}</td>
      <td>${isoTag(row.iso2)}${esc(nameOf(row))}${row.blocked ? '<span class="badge stop">Ticaret durdu</span>' : isNetExporter(row) ? '<span class="badge">Net ihracatçı</span>' : ""}</td>
      <td>${row.blocked ? '<span class="score">–</span>' : scoreCell(row.score)}</td><td>${esc(num(row.imports / 1e6))}</td><td>${growthCell(row.G_raw)}</td>
      <td class="col-share">${esc(pct(row.tr_share))}</td><td class="col-conf">${confidenceLabel(row.kappa)}</td></tr>`;

// Kilitli önizleme: yalnızca birinci pazar gerçek veriyle, kalanı içi boş satırlarla çizilir.
function renderLockedTable() {
  const hidden = current.pazar_sayisi - 1;
  const mask = (width) => `<span class="mask" style="width:${width}px"></span>`;
  const blanks = Array.from({ length: Math.min(LOCKED_ROWS, hidden) }, (_, index) => `
    <tr class="locked" aria-hidden="true"><td>${index + 2}</td><td>${mask(84 + (index * 37) % 72)}</td><td>${mask(78)}</td>
      <td>${mask(46)}</td><td>${mask(54)}</td><td class="col-share">${mask(44)}</td><td class="col-conf">${mask(46)}</td></tr>`).join("");
  const head = COLUMNS.map((column) => `<th class="${column.cls || ""}">${column.label}</th>`).join("");
  $("markets").innerHTML = `<div class="locked-wrap"><div class="scroll"><table class="grid">
      <thead><tr><th>#</th><th>Ülke</th>${head}<th class="col-conf">Veri güveni</th></tr></thead>
      <tbody>${rowHtml(current.rows[0])}${blanks}</tbody></table></div>
    ${hidden > 0 ? `<div class="paywall"><div class="paywall-card">
      <div class="big-lock">${LOCK_ICON.replace(' class="lock-ico"', "")}</div>
      <h3>${hidden} pazar daha var</h3>
      <p>Ücretsiz planda her raporun en iyi pazarını ve skorunu görebilirsin. Bütün sıralamayı, ülke detaylarını ve PDF belgesini görmek için raporu açman gerekir.</p>
      <div class="paywall-btns">
        <button type="button" class="go" data-buy="single">Bu raporu aç · ${num(PRICES.single, 0)} TL</button>
        <button type="button" class="ghost" data-buy="yearly">Pro'ya geç · ayda ${num(PRICES.perMonth, 0)} TL'den</button>
      </div>
      <a class="compare" href="/paketler" data-route>Paketleri karşılaştır</a>
    </div></div>` : ""}</div>`;
}

function renderTable() {
  if (!isOpen()) return renderLockedTable();
  const rows = [...current.rows].sort((a, b) => sort.dir * (a[sort.key] - b[sort.key]));
  const visible = showAll ? rows : rows.slice(0, VISIBLE_ROWS);
  const head = COLUMNS.map((column) => {
    const sorted = sort.key === column.key ? ` aria-sort="${sort.dir < 0 ? "descending" : "ascending"}"` : "";
    return `<th class="${column.cls || ""}"${sorted}><button type="button" data-sort="${column.key}">${column.label}</button></th>`;
  }).join("");
  $("markets").innerHTML = `<div class="scroll"><table class="grid">
      <thead><tr><th>#</th><th>Ülke</th>${head}<th class="col-conf">Veri güveni</th></tr></thead>
      <tbody>${visible.map(rowHtml).join("")}</tbody></table></div>
    ${rows.length > VISIBLE_ROWS ? `<button type="button" class="more" id="more">${showAll ? "İlk " + VISIBLE_ROWS + " ülkeyi göster" : "Tüm " + rows.length + " ülkeyi göster"}</button>` : ""}`;
}

function select(code, fromKeyboard = false) {
  if (!isOpen() && code !== current.rows[0].code) return openCheckout("single");
  selected = code;
  renderTable();
  renderDetail();
  document.querySelectorAll(".pick").forEach((pick) => pick.classList.toggle("selected", Number(pick.dataset.code) === code));
  if (fromKeyboard) {
    const row = document.querySelector(`tr.row[data-code="${code}"]`);
    if (row) row.focus({ preventScroll: true });
  }
  // Dar ekranda detay tablonun altındadır; seçim yapılınca oraya kaydırılır.
  if (window.matchMedia("(max-width: 1080px)").matches) $("detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderReport(report) {
  const rows = report.rows, path = report.product_path;
  rows.forEach((row, index) => { row.rank = index + 1; });
  current = report;
  sort = { key: "score", dir: -1 };
  showAll = false;
  selected = rows[0].code;

  const labels = path ? productLabels(path) : { title: report.product || dotted(report.hs6), sub: "" };
  const open = !report.kilitli, count = report.pazar_sayisi || rows.length;
  // Kilitli raporda diğer pazarların verisi gelmez; toplamları sunucu hesaplar.
  const total = report.ozet ? report.ozet.toplam : rows.reduce((sum, row) => sum + row.imports, 0);
  const fromTurkiye = report.ozet ? report.ozet.turkiye : rows.reduce((sum, row) => sum + row.imports * row.tr_share, 0);
  const tradable = rows.filter((row) => !row.blocked);
  const biggest = tradable.reduce((a, b) => (b.imports > a.imports ? b : a));
  const fastest = tradable.reduce((a, b) => (b.G > a.G ? b : a));
  const group = report.growth_basis ? report.growth_basis.slice(0, 2) + "." + report.growth_basis.slice(2) : "";
  const lockedPick = (index) => `
    <button type="button" class="panel pick is-locked" data-buy="single">
      <span class="pick-top"><span class="order">${index + 1}</span><span class="country">${index + 1}. pazar</span></span>
      <span class="locked-line">${LOCK_ICON}Tam raporda</span></button>`;
  const lockedKpi = (label) => `<div class="is-locked"><span>${label}</span><b>${LOCK_ICON}Tam raporda</b><small>&nbsp;</small></div>`;
  const picks = Array.from({ length: Math.min(3, count) }, (_, index) => rows[index]).map((row, index) => (!open && index > 0 ? lockedPick(index) : `
    <button type="button" class="panel pick${index === 0 ? " selected" : ""}" data-code="${row.code}">
      <span class="pick-top"><span class="order">${index + 1}</span><span class="country">${esc(nameOf(row))}</span>
        <span class="big">${num(row.score, 0)}<small>skor</small></span></span>
      <p class="why">${esc(whyText(row))}</p>
      <dl><dt>Pazar</dt><dd>${esc(million(row.imports))}</dd>
        <dt>Büyüme</dt><dd>${growthCell(row.G_raw)}</dd>
        <dt>Türkiye payı</dt><dd>${esc(pct(row.tr_share))}</dd></dl></button>`)).join("");

  // Ücretsiz planda yalnızca ülke adı içermeyen içgörü gösterilir; kalanı kilitli pazarları ele verir.
  const insights = open ? summaryInsights(report) : [];
  const insightPanel = open ? `<section class="panel insights">
      <div class="panel-head"><b>Öne çıkanlar</b><span class="count">Veriden hesaplanan değerlendirme</span></div>
      <div class="insight-grid">${insights.map((item) => `<div><h3>${item.title}</h3><p>${esc(item.text)}</p></div>`).join("")}</div>
    </section>` : `<section class="panel insights">
      <div class="panel-head"><b>Öne çıkanlar</b><span class="count">Veriden hesaplanan değerlendirme</span></div>
      <div class="insight-grid"><button type="button" class="insight-lock" data-buy="single">${LOCK_ICON}Pazarın büyüklüğü, Türkiye'nin konumu, rakipler ve fiyatlarla ilgili 8 değerlendirme tam raporda yer alıyor</button></div>
    </section>`;

  document.title = shorten(labels.title, 50) + " · İhraçbul";
  $("report").innerHTML = `
    <div class="rhead">
      <div>
        <div class="tags"><span class="tag hs">${esc(dotted(report.hs6))}</span><span class="tag">Veri yılı ${report.t0}</span><span class="tag">${count} ülke</span></div>
        <h1>${esc(shorten(labels.title, 120))}</h1>
        ${labels.sub ? `<p class="path">${esc(labels.sub)}</p>` : ""}
      </div>
      <div class="actions">
        <button type="button" class="ghost" id="copy">Bağlantıyı kopyala</button>
        <button type="button" class="ghost" id="print">${open ? "" : LOCK_ICON}PDF indir</button>
      </div>
    </div>
    <div class="kpis">
      <div><span>Aday pazarların ithalatı</span><b>${esc(million(total))}</b><small>${count} ülke toplamı</small></div>
      <div><span>Türkiye'nin payı</span><b>${esc(pct(total ? fromTurkiye / total : 0))}</b><small>${esc(million(fromTurkiye))} ihracat</small></div>
      ${open ? `<div><span>En büyük pazar</span><b>${esc(nameOf(biggest))}</b><small>${esc(million(biggest.imports))}</small></div>
      <div><span>En güçlü büyüme</span><b>${esc(nameOf(fastest))}</b><small>yılda ${esc(pct(fastest.G_raw))}</small></div>`
    : lockedKpi("En büyük pazar") + lockedKpi("En güçlü büyüme")}
    </div>
    <div class="picks">${picks}</div>
    ${insightPanel}
    <div class="board">
      <section class="panel">
        <div class="panel-head"><b>Tüm pazarlar</b><span class="count">${open ? "Detayları görmek için satıra, sıralamak için başlığa tıkla" : "Ücretsiz önizlemede yalnızca en iyi pazar gösterilir"}</span></div>
        <div id="markets"></div>
      </section>
      <aside class="panel" id="detail" aria-live="polite"></aside>
    </div>
    ${open ? `<section class="panel insights steps">
      <div class="panel-head"><b>Sonraki adımlar</b><span class="count">${esc(nameOf(rows[0]))} için yol haritası</span></div>
      <div class="insight-grid">${nextSteps(report).map((item, index) => `<div><h3><i>${index + 1}</i>${item.title}</h3><p>${esc(item.text)}</p></div>`).join("")}</div>
    </section>` : ""}
    <div class="panel reading">
      <h3>Raporu okurken</h3>
      <ul>
        <li>Skor, bu ürün için ülkelerin birbirine göre sırasını gösterir. Farklı ürünlerin skorları birbiriyle karşılaştırılamaz.</li>
        <li>İthalatı ${esc(million(report.m_min))} değerinin altında kalan pazarlar listeye alınmadı.</li>
        <li>Küçük pazarlarda ve aktarma merkezlerinde büyüme oranı skoru daha az etkiler. Tabloda gördüğün oran ise düzeltilmemiş veridir.</li>
        <li>${report.tariffs ? "Gümrük vergisi oranları, ülkelerin Dünya Ticaret Örgütü'ne bildirdiği yüzde oranlarıdır. Kilo başına alınan vergileri, ek vergileri ve kotaları kapsamaz." : "Bu raporda gümrük vergisi verisi alınamadığı için skor beş ölçüyle hesaplandı."} Yakınlık, ülkenin Türkiye'ye kuş uçuşu uzaklığıyla ölçülür ve navlun fiyatını göstermez. Analiz, ürün kodunun ilk 6 hanesi üzerinden yapılır.</li>
        ${group ? `<li>Bu ürün kodu yakın zamanda tanımlandığı için eski yılların verisi bulunmuyor. Yıllık büyüme, kodun bağlı olduğu ürün grubunun (${esc(group)}) ithalatından hesaplandı.</li>` : ""}
        ${rows.some((row) => row.blocked) ? "<li>Türkiye'nin ticareti durdurduğu ülkeler puanlanmaz ve listenin sonunda \"Ticaret durdu\" etiketiyle gösterilir.</li>" : ""}
        <li>Ticaret verileri UN Comtrade'den alınmıştır. Talebin yüksek olması satışı garanti etmez. Sertifika, dağıtım ve alıcı koşullarını ayrıca araştırman gerekir.</li>
      </ul>
      <p class="report-flag">Bu raporda yanlış ya da eksik bir bilgi gördüysen <a href="mailto:ihracbul@gmail.com?subject=${encodeURIComponent("Rapor hatası: GTİP " + dotted(report.hs6))}&body=${encodeURIComponent("Rapor: " + location.href + "\n\nGördüğüm hata:\n")}">bize bildirebilirsin</a>.</p>
    </div>`;
  renderTable();
  renderDetail();
}

$("report").addEventListener("click", (event) => {
  const sorter = event.target.closest("[data-sort]");
  if (sorter) {
    sort = { key: sorter.dataset.sort, dir: sort.key === sorter.dataset.sort ? -sort.dir : -1 };
    return renderTable();
  }
  if (event.target.closest("#more")) { showAll = !showAll; return renderTable(); }
  const tab = event.target.closest("[data-tab]");
  if (tab) { detailTab = tab.dataset.tab; return renderDetail(); }
  if (event.target.closest("#print")) return isOpen() ? printDocument() : openCheckout("single");
  const copy = event.target.closest("#copy");
  if (copy) {
    navigator.clipboard.writeText(location.href).then(
      () => { copy.textContent = "Kopyalandı"; setTimeout(() => { copy.textContent = "Bağlantıyı kopyala"; }, 1800); },
      () => { copy.textContent = "Kopyalanamadı"; });
    return;
  }
  const target = event.target.closest("tr.row, .pick[data-code]");
  if (target) select(Number(target.dataset.code));
});
$("report").addEventListener("keydown", (event) => {
  const row = event.target.closest("tr.row");
  if (row && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); select(Number(row.dataset.code), true); }
});

let loadId = 0;

function fail(message) {
  $("report").innerHTML = "";
  $("status").className = "error";
  $("status").textContent = message;
}

async function load(hs6) {
  const id = ++loadId, status = $("status");
  $("report").innerHTML = '<div class="skeleton" aria-hidden="true"><div></div><div></div><div></div><div></div></div>';
  status.className = "";
  status.textContent = "Veriler alınıyor. Bir ürün ilk kez arandığında bu işlem 20-30 saniye sürebilir.";
  $("go").disabled = true;
  document.body.classList.add("loading");
  try {
    const response = await fetch("/api/rapor?gtip=" + encodeURIComponent(hs6) + (access.token ? "&t=" + encodeURIComponent(access.token) : ""));
    const payload = await response.json();
    if (id !== loadId) return;
    if (!response.ok) throw new Error(payload.error || "Rapor alınamadı.");
    if (!payload.rows.length) throw new Error("Bu ürün için yeterince büyük bir pazar bulunamadı.");
    status.textContent = "";
    renderReport(payload);
  } catch (error) {
    if (id !== loadId) return;
    fail(error instanceof TypeError || error instanceof SyntaxError
      ? "Sunucuya ulaşılamadı. Sayfayı yenileyip tekrar dene." : error.message);
  } finally {
    if (id === loadId) {
      $("go").disabled = false;
      document.body.classList.remove("loading");
    }
  }
}

/* ---------- Giriş ve hesap ---------- */

const login = $("login");

function signOut() {
  Object.assign(access, { email: "", pro: false, pro_until: 0, reports: [], token: "", ad: "", firma: "", sifre_var: false });
  saveAccess();
  if (current) load(current.hs6);
}

function showLogin(pane) {
  ["lg-form", "lg-sent", "lg-account"].forEach((id) => { $(id).hidden = id !== pane; });
  if (!login.open) login.showModal();
}

$("account").addEventListener("click", () => {
  if (!access.email) return go("/giris");
  $("ac-name").textContent = access.ad || "Belirtilmedi";
  $("ac-company").textContent = access.firma || "Belirtilmedi";
  $("ac-setpass").hidden = access.sifre_var;
  $("ac-error").hidden = true;
  $("ac-pass").value = "";
  $("ac-email").textContent = access.email;
  $("ac-plan").textContent = access.pro
    ? "Pro, " + new Date(access.pro_until * 1000).toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric" }) + " tarihine kadar" : "Ücretsiz";
  $("ac-reports").textContent = access.pro ? "Tüm ürünler" : access.reports.length ? access.reports.map(dotted).join(", ") : "Yok";
  showLogin("lg-account");
});

$("lg-send").addEventListener("click", async () => {
  const field = $("lg-email"), problem = $("lg-error");
  const fail = (message) => { problem.textContent = message; problem.hidden = false; $("lg-send").disabled = false; };
  problem.hidden = true;
  if (!field.checkValidity()) return fail("Geçerli bir e-posta adresi yaz.");
  $("lg-send").disabled = true;
  try {
    const response = await postJson("/api/giris", { eposta: field.value });
    const payload = await response.json();
    if (!response.ok) return fail(payload.error || "Giriş bağlantısı gönderilemedi.");
    $("lg-sent-text").textContent = payload.gonderildi
      ? `${field.value} adresine bir giriş bağlantısı gönderdik. Bağlantı 20 dakika boyunca geçerlidir.`
      : "Deneme sürümünde e-posta gönderilmiyor. Giriş bağlantını aşağıda bulabilirsin.";
    $("lg-demo").hidden = !payload.demo_baglanti;
    if (payload.demo_baglanti) $("lg-demo").href = payload.demo_baglanti;
    else $("lg-demo").removeAttribute("href");
    $("lg-send").disabled = false;
    showLogin("lg-sent");
  } catch (error) {
    fail("Sunucuya ulaşılamadı. Tekrar dene.");
  }
});
$("lg-email").addEventListener("keydown", (event) => { if (event.key === "Enter") $("lg-send").click(); });
$("ac-logout").addEventListener("click", () => { login.close(); signOut(); });
login.addEventListener("click", (event) => { if (event.target === login || event.target.closest("[data-close]")) login.close(); });

/* ---------- Giriş ve kayıt sayfası ---------- */

function showAuth(signup) {
  if (access.email) return go("/");                 // giriş yapılmışsa bu sayfanın işi yok
  $("au-login").hidden = signup;
  $("au-signup").hidden = !signup;
  $("tab-giris").setAttribute("aria-selected", String(!signup));
  $("tab-kayit").setAttribute("aria-selected", String(signup));
  $("au-login-error").hidden = $("au-signup-error").hidden = true;
}

// Form gönderilir, yanıt oturum olarak kaydedilir ve ana sayfaya dönülür.
async function submitAuth(url, body, button, problem) {
  const label = button.textContent;
  const fail = (message) => { problem.textContent = message; problem.hidden = false; button.disabled = false; button.textContent = label; };
  problem.hidden = true;
  button.disabled = true;
  button.textContent = "Bekle…";
  try {
    const response = await postJson(url, body);
    const payload = await response.json();
    if (!response.ok) return fail(payload.error || "İşlem tamamlanamadı. Tekrar dene.");
    Object.assign(access, payload);
    saveAccess();
    button.disabled = false;
    button.textContent = label;
    go("/");
  } catch (error) {
    fail("Sunucuya ulaşılamadı. Tekrar dene.");
  }
}

$("au-login").addEventListener("submit", (event) => {
  event.preventDefault();
  const problem = $("au-login-error");
  if (!$("au-email").checkValidity() || !$("au-pass").value) { problem.textContent = "E-posta adresini ve şifreni yaz."; problem.hidden = false; return; }
  submitAuth("/api/giris-sifre", { eposta: $("au-email").value, sifre: $("au-pass").value }, $("au-login-go"), problem);
});

$("au-signup").addEventListener("submit", (event) => {
  event.preventDefault();
  const problem = $("au-signup-error");
  const stop = (message) => { problem.textContent = message; problem.hidden = false; };
  if (!$("su-name").value.trim()) return stop("Adını ve soyadını yaz.");
  if (!$("su-email").checkValidity()) return stop("Geçerli bir e-posta adresi yaz.");
  if ($("su-pass").value.length < 8) return stop("Şifren en az 8 karakter olmalı.");
  if (!$("su-consent").checked) return stop("Devam etmek için kullanım koşullarını ve gizlilik metnini onayla.");
  submitAuth("/api/kayit", { ad: $("su-name").value, firma: $("su-company").value, eposta: $("su-email").value, sifre: $("su-pass").value }, $("au-signup-go"), problem);
});

$("au-forgot").addEventListener("click", () => {
  $("lg-email").value = $("au-email").value;
  $("lg-error").hidden = true;
  showLogin("lg-form");
});

$("ac-savepass").addEventListener("click", async () => {
  const problem = $("ac-error");
  if ($("ac-pass").value.length < 8) { problem.textContent = "Şifren en az 8 karakter olmalı."; problem.hidden = false; return; }
  try {
    const response = await postJson("/api/profil", { t: access.token, sifre: $("ac-pass").value });
    const payload = await response.json();
    if (!response.ok) { problem.textContent = payload.error || "Şifre kaydedilemedi."; problem.hidden = false; return; }
    Object.assign(access, payload);
    saveAccess();
    $("ac-setpass").hidden = true;
  } catch (error) { problem.textContent = "Sunucuya ulaşılamadı. Tekrar dene."; problem.hidden = false; }
});

// E-postadaki bağlantıyla gelindi: kod sunucuda onaylanır, oturum açılır ve adres çubuğundaki kod silinir.
async function finishLogin() {
  const code = new URLSearchParams(location.search).get("k") || "";
  // Ödeme dönüşünde "d" satın alınan raporun adresidir; yalnızca site içi adres kabul edilir.
  const target = new URLSearchParams(location.search).get("d") || "";
  history.replaceState({}, "", /^\/rapor\/\d{6}$/.test(target) ? target : "/");
  try {
    const response = await postJson("/api/giris-onay", { k: code });
    const payload = await response.json();
    if (response.ok) {
      Object.assign(access, payload);
      saveAccess();
    } else {
      route();
      $("lg-error").textContent = payload.error;
      $("lg-error").hidden = false;
      return showLogin("lg-form");
    }
  } catch (error) { /* bağlantı yoksa ana sayfa açılır */ }
  route();
  if (access.email) $("account").click();
}

// Oturum her açılışta tazelenir: başka cihazda alınan paket ya da biten üyelik buraya da yansır.
async function refreshSession() {
  if (!access.token) return;
  try {
    const response = await fetch("/api/hesap?t=" + encodeURIComponent(access.token));
    if (!response.ok) return;
    const before = JSON.stringify([access.pro, access.reports]);
    Object.assign(access, await response.json());
    saveAccess();
    if (current && before !== JSON.stringify([access.pro, access.reports])) load(current.hs6);
  } catch (error) { /* çevrimdışı: eldeki oturumla devam */ }
}

/* ---------- Sayfa yönlendirme: "/" ana sayfa, "/rapor/<kod>" rapor ---------- */

const LEGAL_PAGES = {
  "/ekip": { id: "ekip-sayfa", title: "Ekip" },
  "/giris": { id: "giris-sayfa", title: "Giriş yap" },
  "/kayit": { id: "giris-sayfa", title: "Kayıt ol" },
  "/gizlilik": { id: "gizlilik-sayfa", title: "Gizlilik ve kişisel veriler" },
  "/kosullar": { id: "kosullar-sayfa", title: "Kullanım koşulları" },
  "/mesafeli-satis": { id: "mesafeli-sayfa", title: "Mesafeli satış sözleşmesi" },
  "/iade": { id: "iade-sayfa", title: "İptal ve iade koşulları" },
};

function route() {
  const match = location.pathname.match(/^\/rapor\/(\d{6})\/?$/);
  const legal = LEGAL_PAGES[location.pathname];
  if (location.pathname === "/giris" && new URLSearchParams(location.search).has("k")) return finishLogin();
  if (legal && legal.id === "giris-sayfa") showAuth(location.pathname === "/kayit");
  const known = match || legal || location.pathname === "/" || location.pathname === "/paketler";
  // Bilinmeyen adres rapor görünümünde bir hata iletisiyle karşılanır; arama kutusu üst şeritte kalır.
  const view = match || !known ? "report" : legal ? "legal" : location.pathname === "/paketler" ? "pricing" : "home";
  document.querySelectorAll(".legal").forEach((page) => { page.hidden = !legal || (page.id || page.dataset.with) !== legal.id; });
  ["home", "report", "pricing", "legal"].forEach((name) => document.body.classList.toggle("view-" + name, name === view));
  // Arama formu tek bir öğedir; ana sayfada giriş bölümünde, diğer görünümlerde üst şeritte durur.
  $(view === "home" ? "hero-search" : "head-search").appendChild($("form"));
  closeSuggestions();
  if (match) return load(match[1]);
  loadId++;
  current = null;
  const note = PAY_NOTES[new URLSearchParams(location.search).get("odeme")];
  $("pay-note").hidden = !(view === "pricing" && note);
  $("pay-note").textContent = note || "";
  document.title = view === "pricing" ? "Paketler · İhraçbul" : legal ? legal.title + " · İhraçbul" : TITLE;
  document.body.classList.remove("loading");
  $("go").disabled = false;
  $("status").textContent = "";
  $("report").innerHTML = "";
  if (view === "home") loadPreview();
  if (!known) {
    document.title = "Sayfa bulunamadı · İhraçbul";
    fail("Bu adreste bir sayfa yok. Üstteki kutudan ürün arayabilir ya da ana sayfaya dönebilirsin.");
  }
}

function go(path) {
  if (path !== location.pathname) history.pushState({}, "", path);
  route();
  window.scrollTo(0, 0);
}

window.addEventListener("popstate", route);
document.addEventListener("click", (event) => {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button) return;
  const link = event.target.closest("a[data-hs6], a[data-home], a[data-route]");
  if (!link) return;
  event.preventDefault();
  input.value = "";
  go(link.getAttribute("href"));
});

/* ---------- Paket satın alma (demo) ---------- */

const checkout = $("checkout");
const REAL_PAYMENT = document.body.dataset.odeme === "gercek";      // sunucuda iyzico anahtarları varsa
const BILLING = { ad: "co-name", soyad: "co-surname", adres: "co-address", sehir: "co-city" };
const PAY_NOTES = {
  basarisiz: "Ödeme tamamlanmadı ve kartından para çekilmedi. Yeniden deneyebilirsin.",
  belirsiz: "Ödemenin sonucu şu an doğrulanamadı. Kartından para çekildiyse bize yazman yeterli, paketini biz tanımlarız.",
  tamam: "Bu ödeme daha önce işlendi. Paketini kullanmak için satın alırken yazdığın e-postayla giriş yap.",
};
let order = null;                         // { kind: "single" | "pro", hs6 }

function openCheckout(kind) {
  // Tek rapor bir ürüne bağlıdır: açık bir rapor yoksa önce ürün seçtirilir.
  if (kind === "single" && !current) {
    go("/");
    input.focus();
    return;
  }
  order = { kind, hs6: current ? current.hs6 : null };
  const single = kind === "single", yearly = kind === "yearly";
  $("co-title").textContent = single ? "Tek rapor" : yearly ? "Pro abonelik, yıllık" : "Pro abonelik, aylık";
  $("co-desc").textContent = single
    ? "GTİP " + dotted(order.hs6) + " için tam raporu açar. Tüm pazarları, ülke detaylarını ve PDF belgesini içerir."
    : yearly ? `Bütün ürünlerde tam raporu açar ve günde 10 yeni ürün aramana izin verir. Bir yıl için tek ödeme yapılır ve aylık ücret ${num(PRICES.perMonth, 0)} TL'ye gelir. Yıllık ödeme iade edilmez.`
      : "Bütün ürünlerde tam raporu açar ve günde 10 yeni ürün aramana izin verir. Her ay yenilenir ve istediğin zaman iptal edebilirsin.";
  $("co-total").textContent = num(PRICES[kind], 0) + " TL" + (single ? "" : yearly ? " / yıl" : " / ay");
  $("co-pay").textContent = REAL_PAYMENT ? "Ödemeye geç: " + num(PRICES[kind], 0) + " TL" : num(PRICES[kind], 0) + " TL öde (demo)";
  $("co-pay").disabled = false;
  $("co-email").value = access.email;
  $("co-email").readOnly = Boolean(access.email);      // giriş yapılmışsa paket o hesaba yazılır
  $("co-consent").checked = false;
  $("co-error").hidden = true;
  $("co-form").hidden = false;
  $("co-done").hidden = true;
  checkout.showModal();
}

const postJson = (path, body) => fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

$("co-pay").addEventListener("click", async () => {
  const label = $("co-pay").textContent, problem = $("co-error");
  const fail = (message) => { problem.textContent = message; problem.hidden = false; $("co-pay").disabled = false; $("co-pay").textContent = label; };
  problem.hidden = true;
  if (!$("co-email").checkValidity()) return fail("Paketin hesabına tanımlanması için geçerli bir e-posta adresi yaz.");
  if (!$("co-consent").checked) return fail("Devam etmek için sözleşmeyi ve iade koşullarını onayla.");
  $("co-pay").disabled = true;
  $("co-pay").textContent = "İşleniyor…";
  try {
    // Hak, sunucunun imzaladığı belirteçle gelir; ekrandaki rapor tam veriyle yeniden yüklenir.
    const billing = Object.fromEntries(Object.entries(BILLING).map(([key, id]) => [key, $(id).value.trim()]));
    if (REAL_PAYMENT && !Object.values(billing).every(Boolean)) return fail("Fatura için ad, soyad, adres ve şehir alanlarını doldur.");
    const response = await postJson("/api/odeme", { tur: order.kind, gtip: order.hs6 || "", eposta: $("co-email").value, onay: true, ...billing });
    const payload = await response.json();
    if (!response.ok) return fail(payload.error || "Ödeme tamamlanamadı. Tekrar dene.");
    if (payload.odeme_url) return location.assign(payload.odeme_url);      // iyzico'nun ödeme sayfası
    Object.assign(access, payload);
    saveAccess();
    $("co-done-text").textContent = (order.kind !== "single"
      ? "Pro aboneliğin başladı. Artık bütün raporları görebilirsin."
      : "Bu ürünün tam raporu açıldı.") + ` Paket ${access.email} adresine tanımlandı. Bu bir deneme ödemesi olduğu için para çekilmedi.`;
    $("co-form").hidden = true;
    $("co-done").hidden = false;
    $("co-close").focus();
  } catch (error) {
    fail("Sunucuya ulaşılamadı. Tekrar dene.");
  }
});
$("co-cancel").addEventListener("click", () => checkout.close());
$("co-close").addEventListener("click", () => checkout.close());
checkout.addEventListener("click", (event) => { if (event.target === checkout) checkout.close(); });
checkout.addEventListener("close", () => { if (current && current.kilitli && (access.pro || access.reports.includes(current.hs6))) load(current.hs6); });

document.addEventListener("click", (event) => {
  const period = event.target.closest("[data-billing]");
  if (period) { billing = period.dataset.billing; return renderBilling(); }
  const buy = event.target.closest("[data-buy]");
  if (buy) return openCheckout(buy.dataset.buy);
  if (event.target.closest("#reset-access")) {
    // Gösterim modunda açılan paketler sunucudan da silinir ve oturum kapanır.
    postJson("/api/demo-sifirla", { t: access.token }).catch(() => {});
    signOut();
  }
});

/* ---------- Arama ---------- */

const input = $("gtip"), suggest = $("suggest");
let suggestions = [], active = -1, searchId = 0;

// Sunucuya ulaşılamazsa null döner (boş liste "eşleşme yok" demektir).
async function fetchSuggestions(query) {
  try {
    const response = await fetch("/api/ara?q=" + encodeURIComponent(query));
    return response.ok ? await response.json() : null;
  } catch (error) {
    return null;
  }
}

function showSuggestions(emptyNote = "") {
  suggest.hidden = !suggestions.length && !emptyNote;
  input.setAttribute("aria-expanded", String(!suggest.hidden));
  if (!suggestions.length) { suggest.innerHTML = emptyNote ? `<li class="empty">${esc(emptyNote)}</li>` : ""; return; }
  suggest.innerHTML = suggestions.map((item, index) => {
    const labels = productLabels(item.path);
    return `<li role="option" data-index="${index}" aria-selected="${index === active}" class="${index === active ? "active" : ""}">
      <span class="hs">${esc(dotted(item.hs6))}</span>
      <span><div class="name">${esc(shorten(labels.title, 110))}</div>
        ${labels.sub ? `<div class="context">${esc(labels.sub)}</div>` : ""}</span></li>`;
  }).join("");
}

function closeSuggestions() {
  searchId++;
  suggestions = [];
  active = -1;
  showSuggestions();
}

function choose(item) {
  input.value = shorten(productLabels(item.path).title, 70);
  go("/rapor/" + item.hs6);
}

input.addEventListener("input", async () => {
  const id = ++searchId, query = input.value.trim();
  const found = query.length >= 2 ? await fetchSuggestions(query) : [];
  if (id !== searchId) return;
  suggestions = found || [];
  active = -1;
  showSuggestions(found && !found.length && query.length >= 2 ? "Bu kelimeyle eşleşen bir ürün bulunamadı. Başka bir kelime deneyebilirsin." : "");
});
input.addEventListener("keydown", (event) => {
  if (!suggestions.length || !["ArrowDown", "ArrowUp", "Escape"].includes(event.key)) return;
  event.preventDefault();
  if (event.key === "Escape") return closeSuggestions();
  active = (active + (event.key === "ArrowDown" ? 1 : -1) + suggestions.length) % suggestions.length;
  showSuggestions();
  const item = suggest.querySelector(".active");
  if (item) item.scrollIntoView({ block: "nearest" });
});
suggest.addEventListener("mousedown", (event) => {
  const item = event.target.closest("li[data-index]");
  if (item) { event.preventDefault(); choose(suggestions[item.dataset.index]); }
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".search")) closeSuggestions();
});

// Kod yazıldıysa doğrudan rapor. Ad yazıldıysa: tek eşleşme varsa o, birden fazlaysa kullanıcı listeden seçer.
async function submit(query) {
  if (!query) return;
  const digits = query.replace(/\D/g, "");
  if (/^[\d.\s]+$/.test(query) && digits.length >= 6) return go("/rapor/" + digits.slice(0, 6));
  if (active >= 0 && suggestions[active]) return choose(suggestions[active]);
  const id = ++searchId, found = await fetchSuggestions(query);
  if (id !== searchId) return;
  suggestions = found || [];
  active = -1;
  if (found && found.length === 1) return choose(found[0]);
  showSuggestions(found === null ? "Sunucuya ulaşılamadı. Sayfayı yenileyip tekrar dene."
    : found.length ? "" : "Bu adla bir ürün bulunamadı. Daha genel bir kelime yazabilir ya da GTİP kodunu deneyebilirsin.");
  input.focus();
}

$("form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(input.value.trim());
});

/* ---------- Ana sayfa kapağı: örnek ürünler, şerit ve dünya haritası ---------- */

// Kapak tek bir ürüne bağlı değildir: bu örnekler arasında kendiliğinden döner.
const SAMPLES = [
  { hs6: "080222", name: "İç fındık" },
  { hs6: "570242", name: "Makine halısı" },
  { hs6: "150920", name: "Sızma zeytinyağı" },
  { hs6: "251512", name: "Blok mermer" },
];
const SAMPLE_INTERVAL = 7000;             // ms; fare panelin üzerindeyken durur
const MAP_HOME = "TR";
const MAP_ARCS = 7;                       // haritada hat çizilen pazar sayısı
const MAP_LABELS = 4;                     // adı yazılan pazar sayısı (kalabalık olmasın)
let previewLoaded = false, sampleIndex = 0, sampleTimer = null, mapData = null;

// Seçili örneğin öne çıkan pazarlarına Türkiye'den uzanan hatlar.
// Dar ekranda harita hatların kapladığı bölgeye yakınlaştırılır; yazı boyutu ekranda hep okunur kalacak şekilde ölçeklenir.
function drawArcs(rows) {
  if (!mapData) return;
  const svg = document.querySelector("#worldmap svg"), home = mapData.centroids[MAP_HOME];
  const targets = rows.filter((row) => mapData.centroids[row.iso2]).slice(0, MAP_ARCS);
  const points = [home].concat(targets.map((row) => mapData.centroids[row.iso2]));

  let view = [0, 0, mapData.w, mapData.h];
  if (window.matchMedia("(max-width: 900px)").matches) {
    const xs = points.map(([x]) => x), ys = points.map(([, y]) => y);
    let x1 = Math.min(...xs) - 70, x2 = Math.max(...xs) + 70, y1 = Math.min(...ys) - 45, y2 = Math.max(...ys) + 30;
    // Çok basık ya da çok dar bir kesit olmasın: en az 1,35 genişlik/yükseklik oranı korunur.
    const centreY = (y1 + y2) / 2, height = Math.max(y2 - y1, (x2 - x1) / 1.35);
    y1 = centreY - height / 2; y2 = centreY + height / 2;
    view = [Math.max(0, x1), Math.max(0, y1), Math.min(mapData.w, x2) - Math.max(0, x1), Math.min(mapData.h, y2) - Math.max(0, y1)];
  }
  svg.setAttribute("viewBox", view.join(" "));
  const unit = view[2] / (svg.clientWidth || 1);          // 1 ekran pikseli kaç harita birimi
  const font = Math.max(9, 11 * unit), mark = Math.max(1, unit);
  svg.style.setProperty("--map-font", font + "px");
  svg.style.setProperty("--map-mark", mark);

  // Etiketler üst üste binmesin: çakışan etiket aşağı ya da yukarı kaydırılır.
  const placed = [];
  const place = (x, y, text, anchorEnd) => {
    const width = text.length * font * 0.56, left = anchorEnd ? x - width : x;
    for (const dy of [-5 * mark, 12 * mark, -5 * mark - font * 1.15, 12 * mark + font * 1.15]) {
      const box = { x1: left, x2: left + width, y1: y + dy - font, y2: y + dy };
      if (!placed.some((other) => box.x1 < other.x2 && box.x2 > other.x1 && box.y1 < other.y2 && box.y2 > other.y1)) { placed.push(box); return y + dy; }
    }
    return y - 5 * mark;
  };
  place(home[0] + 6 * mark, home[1] + 16 * mark, "Türkiye", false);

  document.querySelector("#worldmap .map-arcs").innerHTML = targets.map((row, index) => {
    const [x, y] = mapData.centroids[row.iso2];
    const lift = Math.hypot(x - home[0], y - home[1]) * 0.16;
    const path = `M${home[0]},${home[1]} Q${(home[0] + x) / 2},${Math.min(home[1], y) - lift} ${x},${y}`;
    const delay = (index * 0.12).toFixed(2), left = x < home[0];
    const label = index < MAP_LABELS ? nameOf(row) : "";
    return `<path id="arc${index}" class="map-arc${index >= MAP_LABELS ? " dim" : ""}" pathLength="1" d="${path}" style="animation-delay:${delay}s"/>
      <circle class="map-pulse" r="${1.5 * mark}"><animateMotion dur="${(3.2 + index * 0.35).toFixed(2)}s" begin="${delay}s" repeatCount="indefinite"><mpath href="#arc${index}"/></animateMotion></circle>
      <circle class="map-end" cx="${x}" cy="${y}" r="${2.6 * mark}"/>
      ${label ? `<text class="map-label" x="${x + (left ? -5 : 5) * mark}" y="${place(x + (left ? -5 : 5) * mark, y, label, left)}" text-anchor="${left ? "end" : "start"}">${esc(label)}</text>` : ""}`;
  }).join("");
  const homeLabel = document.querySelector("#worldmap .map-home-label");
  homeLabel.setAttribute("x", home[0] + 6 * mark);
  homeLabel.setAttribute("y", home[1] + 16 * mark);
  document.querySelector("#worldmap .map-home").setAttribute("r", 3.4 * mark);
  document.querySelector("#worldmap .map-ring").setAttribute("r", 6 * mark);
}

// Noktalı dünya haritasının sabit kısmı bir kez çizilir; hatlar örnek değiştikçe yenilenir.
async function drawMap() {
  const response = await fetch("/static/dunya.json");
  if (!response.ok) return;
  mapData = await response.json();
  const home = mapData.centroids[MAP_HOME], radius = 0.7;
  const dots = mapData.dots.map(([x, y]) => `M${x - radius},${y}a${radius},${radius} 0 1,0 ${2 * radius},0a${radius},${radius} 0 1,0 ${-2 * radius},0`).join("");
  $("worldmap").innerHTML = `<svg viewBox="0 0 ${mapData.w} ${mapData.h}" role="img" aria-label="Türkiye'den öne çıkan pazarlara ticaret hatları">
    <path class="map-dots" d="${dots}"/><g class="map-arcs"></g>
    <circle class="map-ring" cx="${home[0]}" cy="${home[1]}" r="6"/><circle class="map-home" cx="${home[0]}" cy="${home[1]}" r="3.4"/>
    <text class="map-label map-home-label" x="${home[0] + 6}" y="${home[1] + 11}">Türkiye</text></svg>`;
}

function showSample(index) {
  const loaded = SAMPLES.filter((sample) => sample.rows);
  if (!loaded.length) return;
  sampleIndex = (index + SAMPLES.length) % SAMPLES.length;
  // Henüz yüklenmemiş örnek atlanır.
  while (!SAMPLES[sampleIndex].rows) sampleIndex = (sampleIndex + 1) % SAMPLES.length;
  const sample = SAMPLES[sampleIndex];
  $("sample-name").textContent = sample.name;
  $("sample-link").href = "/rapor/" + sample.hs6;
  $("preview-list").innerHTML = sample.rows.slice(0, 5).map((row, position) => `<li><span>${position + 1}</span><b>${esc(nameOf(row))}</b>
    <em>${num(row.score, 0)}</em><small>${growthCell(row.G_raw)}</small></li>`).join("");
  $("sample-dots").innerHTML = SAMPLES.map((item, position) => `<button type="button" data-sample="${position}" aria-pressed="${position === sampleIndex}"
    aria-label="${esc(item.name)}" title="${esc(item.name)}"${item.rows ? "" : " disabled"}></button>`).join("");
  $("preview").hidden = false;
  $("worldmap").classList.add("switching");
  setTimeout(() => { drawArcs(sample.rows); $("worldmap").classList.remove("switching"); }, 220);
}

// Üst şerit: TCMB döviz alış kurları. Kurlar günde bir kez yayımlandığı için tarihiyle gösterilir.
let tickerHasRates = false;

async function loadRates() {
  try {
    const response = await fetch("/api/doviz");
    if (!response.ok) return;
    const data = await response.json();
    // Kur değişimi küçük olduğu için iki ondalıkla gösterilir.
    const change = (rate) => `<span class="${rate >= 0 ? "up" : "down"}">${rate >= 0 ? "▲" : "▼"} %${num(Math.abs(rate) * 100, 2)}</span>`;
    const body = (rate) => `<b>${rate.kod}/TRY</b><em>${num(rate.alis, 4)}</em>${rate.degisim === null ? "" : change(rate.degisim)}`;
    const track = $("ticker-track");
    if (tickerHasRates && track.querySelectorAll("[data-kod]").length === data.kurlar.length * 2) {
      // Yenilemede şerit baştan başlamasın diye yalnızca rakamlar değiştirilir.
      data.kurlar.forEach((rate) => track.querySelectorAll(`[data-kod="${rate.kod}"]`).forEach((node) => { node.innerHTML = body(rate); }));
    } else {
      const items = data.kurlar.map((rate) => `<span data-kod="${rate.kod}">${body(rate)}</span>`).join("");
      track.innerHTML = items + items;                 // kesintisiz dönsün diye iki kez
    }
    const day = new Date(data.tarih).toLocaleDateString("tr-TR", { day: "numeric", month: "long" });
    $("ticker-label").innerHTML = `<i class="live"></i>` + (data.kaynak === "piyasa" ? `Döviz · piyasa ${esc(data.saat)}` : `Döviz · TCMB ${esc(day)}`);
    $("ticker").hidden = false;
    tickerHasRates = true;
  } catch (error) { /* kurlar alınamazsa şeritte örnek ürünler kalır */ }
}
setInterval(() => { if (document.body.classList.contains("view-home") && !document.hidden) loadRates(); }, 120000);

function renderTicker() {
  if (tickerHasRates) return;
  // Kurlar gelmediyse yedek içerik: her örnek üründen ilk üç pazar (iki kez, kesintisiz dönsün diye).
  const items = SAMPLES.filter((sample) => sample.rows).map((sample) => sample.rows.slice(0, 3).map((row) =>
    `<a href="/rapor/${sample.hs6}" data-route><b>${esc(sample.name)}</b><i>→</i><b>${esc(nameOf(row))}</b><em>${esc(million(row.imports))}</em>${growthCell(row.G_raw)}</a>`).join("")).join("");
  $("ticker-track").innerHTML = items + items;
  $("ticker").hidden = !items;
}

// Ana sayfadaki örnek raporlar şeridi: her örnek ürünün birinci pazarı ve skoru.
function renderSamples() {
  const loaded = SAMPLES.filter((sample) => sample.rows);
  $("samples").innerHTML = loaded.map((sample) => {
    const top = sample.rows[0];
    return `<a class="sample-card" href="/rapor/${sample.hs6}" data-hs6="${sample.hs6}">
      <small>${esc(sample.name)}</small><b>${num(top.score, 0)}</b>
      <span class="where">${esc(nameOf(top))}</span>
      <span class="facts">${esc(million(top.imports))} pazar · ${growthCell(top.G_raw)}</span>
      <span class="open">Raporu aç</span></a>`;
  }).join("");
  $("ornekler").hidden = !loaded.length;
}

function startRotation() {
  clearInterval(sampleTimer);
  sampleTimer = setInterval(() => {
    if (document.body.classList.contains("view-home") && !$("preview").matches(":hover")) showSample(sampleIndex + 1);
  }, SAMPLE_INTERVAL);
}

async function loadPreview() {
  if (previewLoaded) return;
  previewLoaded = true;
  loadRates();
  try {
    await drawMap();
  } catch (error) { /* harita çizilemezse liste yine gösterilir */ }
  // Örnekler sırayla yüklenir; ilki gelir gelmez gösterilir, diğerleri hazır oldukça dönüşe katılır.
  for (const sample of SAMPLES) {
    try {
      const response = await fetch("/api/ornek?gtip=" + sample.hs6);
      if (!response.ok) continue;
      const rows = (await response.json()).rows;
      if (!rows.length) continue;
      sample.rows = rows;
      renderTicker();
      renderSamples();
      if (SAMPLES.filter((item) => item.rows).length === 1) { showSample(SAMPLES.indexOf(sample)); startRotation(); }
      else showSample(sampleIndex);       // noktaları güncelle
    } catch (error) { /* bu örnek atlanır */ }
  }
}

window.addEventListener("resize", () => { if (SAMPLES[sampleIndex].rows) drawArcs(SAMPLES[sampleIndex].rows); });

$("sample-dots").addEventListener("click", (event) => {
  const dot = event.target.closest("[data-sample]");
  if (dot) { showSample(Number(dot.dataset.sample)); startRotation(); }
});

/* ---------- İpucu balonu ---------- */

const tip = $("tip");
document.addEventListener("mousemove", (event) => {
  const target = event.target.closest("[data-tip]");
  if (!target) { tip.style.display = "none"; return; }
  tip.textContent = target.dataset.tip;
  tip.style.display = "block";
  tip.style.left = Math.min(event.clientX + 12, window.innerWidth - tip.offsetWidth - 8) + "px";
  tip.style.top = event.clientY + 14 + "px";
});

renderPlan();
route();
refreshSession();

/* ---------- Görünüm: karanlık ya da aydınlık ---------- */

$("theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("fr-tema", next); } catch (error) { /* depolama kapalıysa seçim yalnızca bu sayfada geçerli */ }
});

/* ---------- Ana sayfa kapanışı ---------- */

$("close-price").textContent = num(PRICES.perMonth, 0);
$("close-search").addEventListener("click", () => {
  window.scrollTo({ top: 0, behavior: "smooth" });
  input.focus({ preventScroll: true });
});
