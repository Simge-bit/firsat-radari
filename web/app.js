"use strict";

const regionNames = new Intl.DisplayNames(["tr"], { type: "region" });
const FACTORS = { G: "Talep büyümesi", A: "Pazar büyüklüğü", H: "Türkiye için boşluk", F: "Pazarın parçalılığı" };
const REASONS = {
  G: "talep hızlı büyüyor", A: "pazar büyük",
  H: "Türkiye'nin payı düşük, büyüme alanı geniş", F: "tedarik tek bir ülkeye bağlı değil",
};
const VISIBLE_ROWS = 15;
const TITLE = document.title;

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
const growthCell = (g) => `<span class="dir" aria-hidden="true">${g >= 0 ? "▲" : "▼"}</span>${esc(pct(Math.abs(g)))}`;
const scoreCell = (score) => `<span class="score">${num(score, 0)}<i><b style="width:${score}%"></b></i></span>`;
const isHub = (row) => row.reexport >= 0.5;

// İlk üç pazarın tek cümlelik gerekçesi: en güçlü iki faktör.
function whyText(row) {
  const ranked = Object.keys(REASONS).filter((key) => key in row.z).sort((a, b) => row.z[b] - row.z[a]);
  const strong = ranked.filter((key) => row.z[key] >= 0.6).slice(0, 2);
  const text = (strong.length ? strong : ranked.slice(0, 1)).map((key) => REASONS[key]).join(" ve ");
  return text.charAt(0).toLocaleUpperCase("tr-TR") + text.slice(1) + ".";
}

/* ---------- Rapor ---------- */

let current = null;                       // ekrandaki rapor
let sort = { key: "score", dir: -1 };
let showAll = false;
const openRows = new Set();               // detayı açık ülke kodları

function trendChart(row) {
  const width = 300, height = 160, top = 22, bottom = 24, slot = width / row.series.length, barWidth = 30;
  const max = Math.max(...row.series.map(([, value]) => value || 0));
  const plot = height - top - bottom;
  let marks = "";
  row.series.forEach(([year, value], index) => {
    const centre = slot * index + slot / 2, last = index === row.series.length - 1;
    marks += `<text x="${centre}" y="${height - 7}" text-anchor="middle">${year}</text>`;
    if (!value) {
      marks += `<text x="${centre}" y="${height - bottom - 7}" text-anchor="middle">veri yok</text>`;
      return;
    }
    const h = Math.max(2, plot * value / max), x = centre - barWidth / 2, y = top + plot - h;
    marks += `<rect class="bar${last ? " last" : ""}" data-tip="${year}: ${esc(million(value))}" x="${x}" y="${y}" width="${barWidth}" height="${h}"/>`;
    if (last) marks += `<text x="${centre}" y="${y - 6}" text-anchor="middle">${esc(num(value / 1e6))}</text>`;
  });
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" role="img" aria-label="Yıllara göre ithalat">
    ${marks}<line class="axis" x1="0" x2="${width}" y1="${height - bottom}" y2="${height - bottom}"/></svg>`;
}

function hbar(label, share, text, cls = "") {
  return `<div class="hbar ${cls}" data-tip="${esc(label)}: ${esc(text)}"><span>${esc(label)}</span><i><b style="width:${Math.min(100, share * 100)}%"></b></i><em>${esc(text)}</em></div>`;
}

function detail(row) {
  const suppliers = [{ label: "Türkiye", share: row.tr_share, cls: "tr" }]
    .concat(row.rivals.map((rival) => ({ label: countryName(rival.iso2, rival.country), share: rival.share, cls: "" })))
    .sort((a, b) => b.share - a.share);
  const factors = Object.keys(FACTORS).filter((key) => key in row.z)
    .map((key) => hbar(FACTORS[key], row.z[key], num(row.z[key] * 100, 0), "factor")).join("");
  const price = row.unit_price ? `Ortalama ithal birim fiyatı ${num(row.unit_price, 2)} $/kg` : "Birim fiyat verisi yok";
  let flag = "";
  if (isHub(row)) {
    flag = `Bu ülke, ithal ettiği ürünün ${pct(row.reexport)} kadarını yeniden ihraç ediyor. Aktarma merkezi olabilir: artış iç talebi göstermeyebilir, bu yüzden büyüme oranı skora daha az yansıtıldı.`;
  } else if (row.growth_trust < 0.5) {
    flag = "Pazar küçük olduğu için birkaç sevkiyat büyüme oranını uçurabilir. Bu yüzden büyüme oranı skora daha az yansıtıldı.";
  }
  return `<div class="panels">
    <div><h3 class="label">İthalat, milyon $</h3>${trendChart(row)}<div class="sub">${esc(price)}</div></div>
    <div><h3 class="label">Tedarikçi payları, ${row.year}</h3>${suppliers.map((s) => hbar(s.label, s.share, pct(s.share), s.cls)).join("")}</div>
    <div><h3 class="label">Neden bu sırada</h3>${factors}<div class="sub">Her faktör, aday ülkeler arasında 0-100 ölçeğinde. Veri güveni: ${confidenceLabel(row.kappa).toLowerCase()}.</div></div>
  </div>${flag ? `<div class="flag">${esc(flag)}</div>` : ""}`;
}

const COLUMNS = [
  { key: "score", label: "Skor" },
  { key: "imports", label: "İthalat, mn $" },
  { key: "G_raw", label: "Yıllık büyüme" },
  { key: "tr_share", label: "Türkiye payı", cls: "col-share" },
];

function renderTable() {
  const rows = [...current.rows].sort((a, b) => sort.dir * (a[sort.key] - b[sort.key]));
  const visible = showAll ? rows : rows.slice(0, VISIBLE_ROWS);
  const head = COLUMNS.map((column) => {
    const sorted = sort.key === column.key ? ` aria-sort="${sort.dir < 0 ? "descending" : "ascending"}"` : "";
    return `<th class="${column.cls || ""}"${sorted}><button type="button" data-sort="${column.key}">${column.label}</button></th>`;
  }).join("");
  const body = visible.map((row) => {
    const open = openRows.has(row.code);
    return `<tr class="row${open ? " open" : ""}" data-code="${row.code}" tabindex="0" role="button" aria-expanded="${open}">
      <td>${String(row.rank).padStart(2, "0")}</td>
      <td>${isoTag(row.iso2)}${esc(nameOf(row))}${isHub(row) ? '<span class="badge">Aktarma</span>' : ""}</td>
      <td>${scoreCell(row.score)}</td><td>${esc(num(row.imports / 1e6))}</td><td>${growthCell(row.G_raw)}</td>
      <td class="col-share">${esc(pct(row.tr_share))}</td><td class="col-conf">${confidenceLabel(row.kappa)}</td></tr>
      ${open ? `<tr class="detail"><td colspan="7">${detail(row)}</td></tr>` : ""}`;
  }).join("");
  $("markets").innerHTML = `<div class="scroll"><table class="ledger">
      <thead><tr><th>#</th><th>Ülke</th>${head}<th class="col-conf">Veri güveni</th></tr></thead>
      <tbody>${body}</tbody></table></div>
    ${rows.length > VISIBLE_ROWS ? `<button type="button" class="more" id="more">${showAll ? "İlk " + VISIBLE_ROWS + " ülkeyi göster" : "Tüm " + rows.length + " ülkeyi göster"}</button>` : ""}`;
}

function toggleRow(code) {
  if (!openRows.delete(code)) openRows.add(code);
  renderTable();
  const row = document.querySelector(`tr.row[data-code="${code}"]`);
  if (row) row.focus({ preventScroll: true });
}

function renderReport(report) {
  const rows = report.rows, path = report.product_path;
  rows.forEach((row, index) => { row.rank = index + 1; });
  current = report;
  sort = { key: "score", dir: -1 };
  showAll = false;
  openRows.clear();
  openRows.add(rows[0].code);

  const labels = path ? productLabels(path) : { title: report.product || dotted(report.hs6), sub: "" };
  const total = rows.reduce((sum, row) => sum + row.imports, 0);
  const fromTurkiye = rows.reduce((sum, row) => sum + row.imports * row.tr_share, 0);
  const biggest = rows.reduce((a, b) => (b.imports > a.imports ? b : a));
  const fastest = rows.reduce((a, b) => (b.G > a.G ? b : a));
  const group = report.growth_basis ? report.growth_basis.slice(0, 2) + "." + report.growth_basis.slice(2) : "";
  const picks = rows.slice(0, 3).map((row, index) => `
    <div class="pick"><div class="order">${index + 1}</div>
      <div class="country">${esc(nameOf(row))}</div>
      <p class="why">${esc(whyText(row))}</p>
      <dl><dt>Pazar</dt><dd>${esc(million(row.imports))}</dd>
        <dt>Yıllık büyüme</dt><dd>${esc(pct(row.G_raw))}</dd>
        <dt>Türkiye'nin payı</dt><dd>${esc(pct(row.tr_share))}</dd></dl></div>`).join("");

  document.title = shorten(labels.title, 50) + " · Fırsat Radarı";
  $("report").innerHTML = `
    <div class="report-head">
      <div>
        <div class="label">Fırsat raporu · GTİP ${esc(dotted(report.hs6))} · Veri yılı ${report.t0}</div>
        <h1>${esc(shorten(labels.title, 110))}</h1>
        ${labels.sub ? `<p class="path">${esc(labels.sub)}</p>` : ""}
      </div>
      <div class="actions">
        <button type="button" class="ghost" id="copy">Bağlantıyı kopyala</button>
        <button type="button" class="ghost" id="print">PDF indir</button>
      </div>
    </div>
    <div class="kpis">
      <div><span class="label">Aday pazarların ithalatı</span><b>${esc(million(total))}</b><small>${rows.length} ülke, ${report.t0}</small></div>
      <div><span class="label">Türkiye'nin payı</span><b>${esc(pct(total ? fromTurkiye / total : 0))}</b><small>${esc(million(fromTurkiye))} ihracat</small></div>
      <div><span class="label">En büyük pazar</span><b>${esc(nameOf(biggest))}</b><small>${esc(million(biggest.imports))}</small></div>
      <div><span class="label">En güçlü büyüme</span><b>${esc(nameOf(fastest))}</b><small>yılda ${esc(pct(fastest.G_raw))}</small></div>
    </div>
    <div class="section-title"><span class="label">01</span><h2>En umut verici üç pazar</h2></div>
    <div class="picks">${picks}</div>
    <div class="section-title"><span class="label">02</span><h2>Tüm pazarlar</h2><span class="hint">Detay için satıra, sıralamak için başlığa tıkla</span></div>
    <div id="markets"></div>
    <div class="reading">
      <div class="label">Raporu okurken</div>
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
}

$("report").addEventListener("click", (event) => {
  const sorter = event.target.closest("[data-sort]");
  if (sorter) {
    sort = { key: sorter.dataset.sort, dir: sort.key === sorter.dataset.sort ? -sort.dir : -1 };
    return renderTable();
  }
  if (event.target.closest("#more")) { showAll = !showAll; return renderTable(); }
  if (event.target.closest("#print")) return window.print();
  const copy = event.target.closest("#copy");
  if (copy) {
    navigator.clipboard.writeText(location.href).then(
      () => { copy.textContent = "Kopyalandı"; setTimeout(() => { copy.textContent = "Bağlantıyı kopyala"; }, 1800); },
      () => { copy.textContent = "Kopyalanamadı"; });
    return;
  }
  const row = event.target.closest("tr.row");
  if (row) toggleRow(Number(row.dataset.code));
});
$("report").addEventListener("keydown", (event) => {
  const row = event.target.closest("tr.row");
  if (row && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); toggleRow(Number(row.dataset.code)); }
});

let loadId = 0;

function fail(message) {
  $("report").innerHTML = "";
  $("status").className = "error";
  $("status").textContent = message;
}

async function load(hs6) {
  const id = ++loadId, status = $("status");
  $("report").innerHTML = '<div class="skeleton" aria-hidden="true"><div></div><div></div><div></div><div></div><div></div></div>';
  status.className = "";
  status.textContent = "Veri çekiliyor. Bir ürün ilk kez sorulduğunda 20-30 saniye sürebilir";
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
  document.body.classList.toggle("view-report", Boolean(match));
  document.body.classList.toggle("view-home", !match);
  // Arama formu tek bir öğedir; görünüme göre üst şeride ya da giriş bölümüne taşınır.
  $(match ? "head-search" : "hero-search").appendChild($("form"));
  closeSuggestions();
  if (match) {
    load(match[1]);
  } else {
    loadId++;
    document.title = TITLE;
    document.body.classList.remove("loading");
    $("go").disabled = false;
    $("status").textContent = "";
    $("report").innerHTML = "";
    if (location.pathname !== "/") fail("Sayfa bulunamadı.");
    loadPreview();
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
  const link = event.target.closest("a[data-hs6], a[data-home]");
  if (!link) return;
  event.preventDefault();
  if (link.dataset.hs6) input.value = "";
  go(link.dataset.hs6 ? "/rapor/" + link.dataset.hs6 : "/");
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
      <span class="code">${esc(dotted(item.hs6))}</span>
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

/* ---------- Ana sayfadaki canlı örnek ---------- */

let previewLoaded = false;

async function loadPreview() {
  if (previewLoaded) return;
  previewLoaded = true;
  try {
    const response = await fetch("/api/rapor?gtip=080222");
    if (!response.ok) return;
    const report = await response.json();
    if (!report.rows.length) return;
    $("preview-table").innerHTML = `
      <thead><tr><th>#</th><th>Ülke</th><th>Skor</th><th>İthalat, mn $</th><th class="col-share">Yıllık büyüme</th></tr></thead>
      <tbody>${report.rows.slice(0, 5).map((row, index) => `<tr>
        <td>${String(index + 1).padStart(2, "0")}</td><td>${isoTag(row.iso2)}${esc(nameOf(row))}</td>
        <td>${scoreCell(row.score)}</td><td>${esc(num(row.imports / 1e6))}</td>
        <td class="col-share">${growthCell(row.G_raw)}</td></tr>`).join("")}</tbody>`;
    $("ornek").hidden = false;
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

route();
