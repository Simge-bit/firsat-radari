"use strict";

// Yönetim paneli: üyeler, satın almalar ve sitenin durumu. Oturum yalnızca bu sekmede tutulur.
const $ = (id) => document.getElementById(id);
const esc = (text) => String(text).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const day = (seconds) => new Date(seconds * 1000).toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric" });
const moment = (seconds) => new Date(seconds * 1000).toLocaleString("tr-TR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const money = (amount) => amount.toLocaleString("tr-TR") + " TL";
const KINDS = { single: "Tek rapor", pro: "Pro, aylık", yearly: "Pro, yıllık" };
const SOURCES = { demo: "Deneme ödemesi", iyzico: "iyzico", yonetim: "Yönetici tanımladı" };

let token = "";
try { token = sessionStorage.getItem("fr-yonetim") || ""; } catch (error) { /* depolama kapalıysa her açılışta şifre sorulur */ }

async function call(url, body) {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return { ok: response.ok, status: response.status, data: await response.json() };
}

function signOut() {
  token = "";
  try { sessionStorage.removeItem("fr-yonetim"); } catch (error) { /* yok sayılır */ }
  $("panel").hidden = true;
  $("login").hidden = false;
}

function render(view) {
  const members = view.uyeler, purchases = view.satin_almalar, state = view.durum;
  const paid = purchases.filter((item) => item.saglayici === "iyzico");
  $("login").hidden = true;
  $("panel").hidden = false;
  $("stamp").textContent = "Son yenileme " + new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
  $("cards").innerHTML = [
    ["Üye", members.length, "kayıtlı hesap"],
    ["Pro üye", members.filter((member) => member.pro_bitis).length, "süresi devam eden"],
    ["Gerçek satış", paid.length, money(paid.reduce((sum, item) => sum + item.tutar, 0))],
    ["Haber bekleyen", new Set(view.bekleme.map((item) => item.eposta)).size, "paketler açılınca haber isteyen"],
  ].map(([label, value, note]) => `<div><span>${label}</span><b>${esc(value)}</b><small>${esc(note)}</small></div>`).join("");
  $("state").innerHTML = [
    [state.odeme === "gercek", state.odeme === "gercek" ? "Ödeme gerçek para alıyor" : state.odeme === "yakinda" ? "Ücretli paketler kapalı, yakında olarak görünüyor" : "Ödeme deneme modunda, para alınmıyor"],
    [state.veri_istegi < state.veri_siniri, "Bugünkü veri isteği " + state.veri_istegi + " / " + state.veri_siniri],
    [state.kalici, state.kalici ? "Üyeler kalıcı veritabanında" : "Üyeler kalıcı değil, sunucu yeniden başlayınca silinir"],
    [state.eposta, state.eposta ? "Giriş e-postaları gönderiliyor" : "Giriş e-postaları gönderilemiyor"],
  ].map(([good, text]) => `<span class="${good ? "ok" : "bad"}">${text}</span>`).join("");

  $("members").innerHTML = members.length ? members.map((member) => `<tr>
      <td><b>${esc(member.ad || "Ad belirtilmedi")}</b><small>${esc(member.eposta)}</small>${member.firma ? `<small>${esc(member.firma)}</small>` : ""}</td>
      <td>${day(member.kayit)}<small>${member.sifre_var ? "Şifreli hesap" : "Şifre belirlenmedi"}</small></td>
      <td>${member.pro_bitis ? "Pro<small>" + day(member.pro_bitis) + " tarihine kadar</small>" : "Ücretsiz"}
          ${member.raporlar.length ? `<small>Açık raporlar: ${esc(member.raporlar.join(", "))}</small>` : ""}</td>
      <td><div class="adm-acts" data-eposta="${esc(member.eposta)}">
        <button type="button" data-islem="pro-ay">1 ay Pro</button><button type="button" data-islem="pro-yil">1 yıl Pro</button>
        <button type="button" data-islem="rapor">Rapor aç</button>
        ${member.pro_bitis ? '<button type="button" data-islem="pro-bitir">Pro\'yu bitir</button>' : ""}
        <button type="button" class="danger" data-islem="sil">Sil</button></div></td></tr>`).join("")
    : '<tr><td colspan="4" class="adm-empty">Henüz kayıtlı üye yok.</td></tr>';

  $("waiting").innerHTML = view.bekleme.length ? view.bekleme.map((item) => `<tr>
      <td>${moment(item.zaman)}</td><td>${esc(item.eposta)}</td><td>${KINDS[item.tur] || esc(item.tur)}</td></tr>`).join("")
    : '<tr><td colspan="3" class="adm-empty">Henüz haber isteyen yok.</td></tr>';

  $("purchases").innerHTML = purchases.length ? purchases.map((item) => `<tr>
      <td>${moment(item.zaman)}</td><td>${esc(item.eposta)}</td>
      <td>${KINDS[item.tur] || esc(item.tur)}${item.urun ? `<small>Ürün kodu ${esc(item.urun)}</small>` : ""}</td>
      <td>${money(item.tutar)}</td><td>${SOURCES[item.saglayici] || esc(item.saglayici)}</td></tr>`).join("")
    : '<tr><td colspan="5" class="adm-empty">Henüz satın alma yok.</td></tr>';
}

async function act(body) {
  const problem = $("panel-error");
  problem.hidden = true;
  const { ok, status, data } = await call("/api/yonetim", { t: token, ...body });
  if (status === 401) return signOut();
  if (!ok) { problem.textContent = data.error || "İşlem yapılamadı."; problem.hidden = false; return; }
  render(data);
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const problem = $("login-error");
  problem.hidden = true;
  try {
    const { ok, data } = await call("/api/yonetim/giris", { sifre: $("pass").value });
    if (!ok) { problem.textContent = data.error === "Bulunamadı" ? "Yönetim paneli henüz açılmamış. Sunucuda yönetim şifresi tanımlı değil." : data.error; problem.hidden = false; return; }
    token = data.t;
    try { sessionStorage.setItem("fr-yonetim", token); } catch (error) { /* yalnızca bu sayfada geçerli olur */ }
    $("pass").value = "";
    render(data);
  } catch (error) { problem.textContent = "Sunucuya ulaşılamadı. Tekrar dene."; problem.hidden = false; }
});

$("logout").addEventListener("click", signOut);

$("grant").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!$("g-email").checkValidity()) return;
  act({ islem: event.submitter.dataset.islem, eposta: $("g-email").value }).then(() => { $("g-email").value = ""; });
});

// Silme ve Pro'yu bitirme geri alınamadığı için ikinci bir tıkla onaylanır.
$("members").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-islem]");
  if (!button) return;
  const email = button.parentElement.dataset.eposta, action = button.dataset.islem;
  if (action === "rapor") {
    const code = (window.prompt("Açılacak raporun 6 haneli ürün kodu (GTİP):") || "").replace(/\D/g, "");
    return code ? act({ islem: action, eposta: email, gtip: code }) : undefined;
  }
  if ((action === "sil" || action === "pro-bitir") && button.dataset.onay !== "1") {
    button.dataset.onay = "1";
    button.textContent = "Emin misin? Tekrar tıkla";
    return undefined;
  }
  return act({ islem: action, eposta: email });
});

if (token) act({ islem: "liste" });
