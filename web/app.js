"use strict";

const regionNames = new Intl.DisplayNames(["tr"], { type: "region" });
const FACTORS = { G: "Talep büyümesi", A: "Pazar büyüklüğü", H: "Türkiye için boşluk", F: "Pazarın parçalılığı" };
const REASONS = {
  G: "talep hızlı büyüyor", A: "pazar büyük",
  H: "Türkiye'nin payı düşük, büyüme alanı geniş", F: "tedarik tek bir ülkeye bağlı değil",
};
const VISIBLE_ROWS = 20;
const LOCKED_ROWS = 9;                    // kilitli önizlemede gösterilen boş satır sayısı
const PRICES = { single: 190, pro: 490 }; // TL; tek rapor tek seferlik, Pro aylık
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
const isHub = (row) => row.reexport >= 0.5;

// İlk üç pazarın tek cümlelik gerekçesi: en güçlü iki faktör.
function whyText(row) {
  const ranked = Object.keys(REASONS).filter((key) => key in row.z).sort((a, b) => row.z[b] - row.z[a]);
  const strong = ranked.filter((key) => row.z[key] >= 0.6).slice(0, 2);
  const text = (strong.length ? strong : ranked.slice(0, 1)).map((key) => REASONS[key]).join(" ve ");
  return text.charAt(0).toLocaleUpperCase("tr-TR") + text.slice(1) + ".";
}

/* ---------- Erişim (demo) ---------- */

// Demo sürümde hesap ve gerçek ödeme yoktur: açılan paketler yalnızca bu tarayıcıda saklanır.
// Gerçek üründe bu kontrol sunucuda yapılmalı ve kilitli veri tarayıcıya hiç gönderilmemelidir.
const access = { pro: false, reports: [] };
try {
  Object.assign(access, JSON.parse(localStorage.getItem("fr-erisim")) || {});
} catch (error) { /* depolama kapalıysa ücretsiz planla devam */ }

function saveAccess() {
  try { localStorage.setItem("fr-erisim", JSON.stringify(access)); } catch (error) { /* yalnızca bu oturumda geçerli olur */ }
  renderPlan();
}

const isUnlocked = (hs6) => access.pro || access.reports.includes(hs6);

function renderPlan() {
  $("plan").textContent = access.pro ? "Pro" : "Ücretsiz plan";
  $("plan").classList.toggle("pro", access.pro);
  const buyPro = $("buy-pro");
  buyPro.textContent = access.pro ? "Aktif plan" : "Pro'ya geç";
  buyPro.disabled = access.pro;
  document.querySelectorAll("[data-price]").forEach((node) => { node.textContent = PRICES[node.dataset.price]; });
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

// Pazara giriş: resmi listelerden müşavirlik iletişimi, destekli fuarlar ve (AB için) şart kaynağı.
function entrySection(row) {
  const now = today(), link = requirementsLink(row, current.hs6);
  const offices = row.offices.length
    ? `<ul class="contacts">${row.offices.map((office) => `<li><span>${esc(office.sehir)}</span><a href="mailto:${esc(office.eposta)}">${esc(office.eposta)}</a></li>`).join("")}</ul>
       <a class="ghost wide" href="${esc(importerRequestLink(row.offices[0], row, current))}">İthalatçı listesi iste</a>
       <div class="sub">Hazır e-posta açılır: müşavirlikten bu ürünü ithal eden firmaların listesini talep eder.</div>`
    : '<div class="sub">Bu ülkede Ticaret Bakanlığı\'nın müşavirliği ya da ataşeliği bulunmuyor.</div>';
  const fairs = row.fairs.length
    ? `<ul class="fairs">${row.fairs.map((fair) => `<li class="${fair.bitis < now ? "past" : ""}"><b>${esc(fair.ad)}</b>
        <span>${esc(fair.sehir)} · ${esc(fairDates(fair))}${fair.bitis < now ? " · geçti" : ""}</span><small>${esc(shorten(fair.konu.toLocaleLowerCase("tr-TR"), 70))}</small></li>`).join("")}</ul>`
    : '<div class="sub">Bu ülkede ürününün sektörüyle eşleşen destekli fuar bulunamadı.</div>';
  return `<div class="d-sec"><h3>Ticaret Müşavirliği <span>T.C. Ticaret Bakanlığı</span></h3>${offices}</div>
    <div class="d-sec"><h3>İlgili destekli fuarlar <span>2026</span></h3>${fairs}</div>
    <div class="d-sec"><h3>Olası şartlar <span>kontrol listesi</span></h3>
      ${row.requirements.length ? `<ul class="reqs">${row.requirements.map((item) => `<li><b>${esc(item.baslik)}</b><p>${esc(item.metin)}</p>
        <a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.kurum)} ↗</a></li>`).join("")}</ul>`
        : '<div class="sub">Bu ülke için hazır bir kontrol listemiz yok. Şartları Ticaret Müşavirliği\'nden öğrenebilirsin.</div>'}
      ${link ? `<a class="ghost wide" href="${esc(link)}" target="_blank" rel="noopener">Bu ürünün resmi AB şartlarını gör ↗</a>` : ""}
      ${row.requirements.length ? '<div class="sub">Genel bilgilendirmedir; resmi veri değildir ve eksik olabilir. Sevkiyattan önce ilgili kurumdan doğrula.</div>' : ""}
    </div>`;
}

function renderDetail() {
  const row = current.rows.find((item) => item.code === selected);
  const suppliers = [{ label: "Türkiye", share: row.tr_share, cls: "tr" }]
    .concat(row.rivals.map((rival) => ({ label: countryName(rival.iso2, rival.country), share: rival.share, cls: "" })))
    .sort((a, b) => b.share - a.share);
  const factors = Object.keys(FACTORS).filter((key) => key in row.z)
    .map((key) => hbar(FACTORS[key], row.z[key], num(row.z[key] * 100, 0), "factor")).join("");
  $("detail").innerHTML = `
    <div class="d-head">
      <div class="name">${esc(nameOf(row))}<small>${row.rank}. sıra · ${esc(million(row.imports))} pazar · ${growthCell(row.G_raw)}</small></div>
      <div class="big">${num(row.score, 0)}<small>Skor</small></div>
    </div>
    <div class="d-sec"><h3>Değerlendirme</h3><ul class="notes">${marketInsights(row).map((line) => `<li class="${line.startsWith("Dikkat") ? "warn" : ""}">${esc(line)}</li>`).join("")}</ul></div>
    ${entrySection(row)}
    <div class="d-sec"><h3>İthalat, milyon $</h3>${trendChart(row)}</div>
    <div class="d-sec"><h3>Tedarikçi payları <span>${row.year}</span></h3>${suppliers.map((s) => hbar(s.label, s.share, pct(s.share), s.cls)).join("")}</div>
    <div class="d-sec"><h3>Neden bu sırada <span>0-100</span></h3>${factors}<div class="sub">Her faktör aday ülkeler arasında ölçeklenir. Veri güveni: ${confidenceLabel(row.kappa).toLowerCase()}.</div></div>`;
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
      <td>${isoTag(row.iso2)}${esc(nameOf(row))}${isHub(row) ? '<span class="badge">Aktarma</span>' : ""}</td>
      <td>${scoreCell(row.score)}</td><td>${esc(num(row.imports / 1e6))}</td><td>${growthCell(row.G_raw)}</td>
      <td class="col-share">${esc(pct(row.tr_share))}</td><td class="col-conf">${confidenceLabel(row.kappa)}</td></tr>`;

// Kilitli önizleme: yalnızca birinci pazar gerçek veriyle, kalanı içi boş satırlarla çizilir.
function renderLockedTable() {
  const hidden = current.rows.length - 1;
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
      <p>Ücretsiz planda her raporun en iyi pazarını görürsün. Tüm sıralama, ülke detayları ve PDF için raporu aç.</p>
      <div class="paywall-btns">
        <button type="button" class="go" data-buy="single">Bu raporu aç · ${PRICES.single} TL</button>
        <button type="button" class="ghost" data-buy="pro">Pro'ya geç · ${PRICES.pro} TL/ay</button>
      </div>
      <a class="compare" href="/paketler" data-route>Paketleri karşılaştır</a>
    </div></div>` : ""}</div>`;
}

function renderTable() {
  if (!isUnlocked(current.hs6)) return renderLockedTable();
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
  if (!isUnlocked(current.hs6) && code !== current.rows[0].code) return openCheckout("single");
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
  const total = rows.reduce((sum, row) => sum + row.imports, 0);
  const fromTurkiye = rows.reduce((sum, row) => sum + row.imports * row.tr_share, 0);
  const biggest = rows.reduce((a, b) => (b.imports > a.imports ? b : a));
  const fastest = rows.reduce((a, b) => (b.G > a.G ? b : a));
  const group = report.growth_basis ? report.growth_basis.slice(0, 2) + "." + report.growth_basis.slice(2) : "";
  const open = isUnlocked(report.hs6);
  const lockedPick = (index) => `
    <button type="button" class="panel pick is-locked" data-buy="single">
      <span class="pick-top"><span class="order">${index + 1}</span><span class="country">${index + 1}. pazar</span></span>
      <span class="locked-line">${LOCK_ICON}Tam raporda</span></button>`;
  const lockedKpi = (label) => `<div class="is-locked"><span>${label}</span><b>${LOCK_ICON}Tam raporda</b><small>&nbsp;</small></div>`;
  const picks = rows.slice(0, 3).map((row, index) => (!open && index > 0 ? lockedPick(index) : `
    <button type="button" class="panel pick${index === 0 ? " selected" : ""}" data-code="${row.code}">
      <span class="pick-top"><span class="order">${index + 1}</span><span class="country">${esc(nameOf(row))}</span>
        <span class="big">${num(row.score, 0)}<small>skor</small></span></span>
      <p class="why">${esc(whyText(row))}</p>
      <dl><dt>Pazar</dt><dd>${esc(million(row.imports))}</dd>
        <dt>Büyüme</dt><dd>${growthCell(row.G_raw)}</dd>
        <dt>Türkiye payı</dt><dd>${esc(pct(row.tr_share))}</dd></dl></button>`)).join("");

  // Ücretsiz planda yalnızca ülke adı içermeyen içgörü gösterilir; kalanı kilitli pazarları ele verir.
  const insights = summaryInsights(report);
  const shown = open ? insights : insights.filter((item) => item.title === "Türkiye'nin konumu");
  const insightPanel = `<section class="panel insights">
      <div class="panel-head"><b>Öne çıkanlar</b><span class="count">Veriden hesaplanan değerlendirme</span></div>
      <div class="insight-grid">${shown.map((item) => `<div><h3>${item.title}</h3><p>${esc(item.text)}</p></div>`).join("")}
        ${open ? "" : `<button type="button" class="insight-lock" data-buy="single">${LOCK_ICON}${insights.length - shown.length} içgörü daha tam raporda</button>`}</div>
    </section>`;

  document.title = shorten(labels.title, 50) + " · Fırsat Radarı";
  $("report").innerHTML = `
    <div class="rhead">
      <div>
        <div class="tags"><span class="tag hs">${esc(dotted(report.hs6))}</span><span class="tag">Veri yılı ${report.t0}</span><span class="tag">${rows.length} ülke</span></div>
        <h1>${esc(shorten(labels.title, 120))}</h1>
        ${labels.sub ? `<p class="path">${esc(labels.sub)}</p>` : ""}
      </div>
      <div class="actions">
        <button type="button" class="ghost" id="copy">Bağlantıyı kopyala</button>
        <button type="button" class="ghost" id="print">${open ? "" : LOCK_ICON}PDF indir</button>
      </div>
    </div>
    <div class="kpis">
      <div><span>Aday pazarların ithalatı</span><b>${esc(million(total))}</b><small>${rows.length} ülke toplamı</small></div>
      <div><span>Türkiye'nin payı</span><b>${esc(pct(total ? fromTurkiye / total : 0))}</b><small>${esc(million(fromTurkiye))} ihracat</small></div>
      ${open ? `<div><span>En büyük pazar</span><b>${esc(nameOf(biggest))}</b><small>${esc(million(biggest.imports))}</small></div>
      <div><span>En güçlü büyüme</span><b>${esc(nameOf(fastest))}</b><small>yılda ${esc(pct(fastest.G_raw))}</small></div>`
    : lockedKpi("En büyük pazar") + lockedKpi("En güçlü büyüme")}
    </div>
    <div class="picks">${picks}</div>
    ${insightPanel}
    <div class="board">
      <section class="panel">
        <div class="panel-head"><b>Tüm pazarlar</b><span class="count">${open ? "Detay için satıra, sıralamak için başlığa tıkla" : "Ücretsiz önizleme: en iyi pazar açık"}</span></div>
        <div id="markets"></div>
      </section>
      <aside class="panel" id="detail" aria-live="polite"></aside>
    </div>
    <div class="panel reading">
      <h3>Raporu okurken</h3>
      <ul>
        <li>Skor, bu ürünün aday ülkeleri arasında göreli bir sıralamadır. Farklı ürünlerin skorları birbiriyle karşılaştırılamaz.</li>
        <li>İthalatı ${esc(million(report.m_min))} altında kalan pazarlar listeye alınmadı.</li>
        <li>Küçük pazarlarda ve aktarma merkezlerinde büyüme oranı skora daha az yansıtılır. Tabloda görünen oran ham veridir.</li>
        <li>Bu sürümde gümrük vergisi ve lojistik skora dahil değil. Analiz kodun ilk 6 hanesi üzerinden yapılır.</li>
        ${group ? `<li>Bu ürün kodu yakın zamanda tanımlandığı için eski yılların verisi yok. Yıllık büyüme, bağlı olduğu ürün grubunun (${esc(group)}) ithalatından hesaplandı.</li>` : ""}
        <li>Kaynak: UN Comtrade. Talep verisi satışı garanti etmez; sertifika, dağıtım ve alıcı koşullarını ayrıca araştır.</li>
      </ul>
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
  if (event.target.closest("#print")) return isUnlocked(current.hs6) ? printDocument() : openCheckout("single");
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
  status.textContent = "Veri çekiliyor. Bir ürün ilk kez sorulduğunda 20-30 saniye sürebilir.";
  $("go").disabled = true;
  document.body.classList.add("loading");
  try {
    const response = await fetch("/api/rapor?gtip=" + encodeURIComponent(hs6));
    const payload = await response.json();
    if (id !== loadId) return;
    if (!response.ok) throw new Error(payload.error || "Rapor alınamadı.");
    if (!payload.rows.length) throw new Error("Bu ürün için yeterli büyüklükte pazar bulunamadı.");
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

/* ---------- Sayfa yönlendirme: "/" ana sayfa, "/rapor/<kod>" rapor ---------- */

function route() {
  const match = location.pathname.match(/^\/rapor\/(\d{6})\/?$/);
  const view = match ? "report" : location.pathname === "/paketler" ? "pricing" : "home";
  ["home", "report", "pricing"].forEach((name) => document.body.classList.toggle("view-" + name, name === view));
  // Arama formu tek bir öğedir; ana sayfada giriş bölümünde, diğer görünümlerde üst şeritte durur.
  $(view === "home" ? "hero-search" : "head-search").appendChild($("form"));
  closeSuggestions();
  if (match) return load(match[1]);
  loadId++;
  current = null;
  document.title = view === "pricing" ? "Paketler · Fırsat Radarı" : TITLE;
  document.body.classList.remove("loading");
  $("go").disabled = false;
  $("status").textContent = "";
  $("report").innerHTML = "";
  if (view === "home") loadPreview();
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
let order = null;                         // { kind: "single" | "pro", hs6 }

function openCheckout(kind) {
  // Tek rapor bir ürüne bağlıdır: açık bir rapor yoksa önce ürün seçtirilir.
  if (kind === "single" && !current) {
    go("/");
    input.focus();
    return;
  }
  order = { kind, hs6: current ? current.hs6 : null };
  const single = kind === "single";
  $("co-title").textContent = single ? "Tek rapor" : "Pro abonelik";
  $("co-desc").textContent = single
    ? "GTİP " + dotted(order.hs6) + " için tam rapor: tüm pazarlar, ülke detayları ve PDF."
    : "Tüm ürünlerde sınırsız tam rapor. İstediğin zaman iptal edebilirsin.";
  $("co-total").textContent = PRICES[kind] + " TL" + (single ? "" : " / ay");
  $("co-pay").textContent = PRICES[kind] + " TL öde (demo)";
  $("co-pay").disabled = false;
  $("co-form").hidden = false;
  $("co-done").hidden = true;
  checkout.showModal();
}

$("co-pay").addEventListener("click", () => {
  $("co-pay").disabled = true;
  $("co-pay").textContent = "İşleniyor…";
  setTimeout(() => {
    if (order.kind === "pro") access.pro = true;
    else if (!access.reports.includes(order.hs6)) access.reports.push(order.hs6);
    saveAccess();
    $("co-done-text").textContent = order.kind === "pro"
      ? "Pro aboneliğin aktif. Artık tüm raporlar açık. (Demo: para çekilmedi.)"
      : "Bu ürünün tam raporu açıldı. (Demo: para çekilmedi.)";
    $("co-form").hidden = true;
    $("co-done").hidden = false;
    $("co-close").focus();
  }, 900);
});
$("co-cancel").addEventListener("click", () => checkout.close());
$("co-close").addEventListener("click", () => checkout.close());
checkout.addEventListener("click", (event) => { if (event.target === checkout) checkout.close(); });
checkout.addEventListener("close", () => { if (current) renderReport(current); });

document.addEventListener("click", (event) => {
  const buy = event.target.closest("[data-buy]");
  if (buy) return openCheckout(buy.dataset.buy);
  if (event.target.closest("#reset-access")) {
    access.pro = false;
    access.reports = [];
    saveAccess();
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
  showSuggestions(found && !found.length && query.length >= 2 ? "Eşleşen ürün yok. Başka bir kelime dene." : "");
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
    : found.length ? "" : "Bu adla bir ürün bulunamadı. Daha genel bir kelime ya da GTİP kodunu dene.");
  input.focus();
}

$("form").addEventListener("submit", (event) => {
  event.preventDefault();
  submit(input.value.trim());
});

/* ---------- Ana sayfadaki canlı örnek ve şerit ---------- */

let previewLoaded = false;

async function loadPreview() {
  if (previewLoaded) return;
  previewLoaded = true;
  try {
    const response = await fetch("/api/rapor?gtip=080222");
    if (!response.ok) return;
    const rows = (await response.json()).rows;
    if (!rows.length) return;
    $("preview-table").innerHTML = `
      <thead><tr><th>#</th><th>Ülke</th><th>Skor</th><th>İthalat, mn $</th><th class="col-share">Büyüme</th></tr></thead>
      <tbody>${rows.slice(0, 7).map((row, index) => `<tr>
        <td>${index + 1}</td><td>${isoTag(row.iso2)}${esc(nameOf(row))}</td>
        <td>${scoreCell(row.score)}</td><td>${esc(num(row.imports / 1e6))}</td>
        <td class="col-share">${growthCell(row.G_raw)}</td></tr>`).join("")}</tbody>`;
    $("preview").hidden = false;
    // Şerit kesintisiz dönsün diye içerik iki kez yazılır.
    const items = rows.slice(0, 14).map((row) => `<span><b>${esc(nameOf(row))}</b><em>${esc(million(row.imports))}</em>${growthCell(row.G_raw)}</span>`).join("");
    $("ticker-track").innerHTML = items + items;
    $("ticker").hidden = false;
  } catch (error) { /* örnek gösterilemezse bölüm gizli kalır */ }
}

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
