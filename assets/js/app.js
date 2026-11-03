// TEFAS Quant - uygulama girişi: veri yükleme, yönlendirme, tema, arama
import { esc, dateTR, toast } from "./util.js";
import { initPush } from "./push.js";
import * as overview from "./views/overview.js";
import * as ranking from "./views/ranking.js";
import * as fund from "./views/fund.js";
import * as compare from "./views/compare.js";
import * as method from "./views/method.js";
import * as backtest from "./views/backtest.js";
import * as simulation from "./views/simulation.js";
import * as report from "./views/report.js";
import * as modelreport from "./views/modelreport.js";
import * as personal from "./views/personal.js";
import * as model from "./views/model.js";
import * as bes from "./views/bes.js";

const VIEWS = {
  genel: { mod: overview, title: "Genel Bakış", eyebrow: "PİYASA ÖZETİ" },
  siralama: { mod: ranking, title: "Fon Sıralaması", eyebrow: "KATEGORİ İÇİ DERECELENDİRME" },
  bes: { mod: bes, title: "BES Fonları", eyebrow: "BİREYSEL EMEKLİLİK FONLARI" },
  fon: { mod: fund, title: "Fon Detayı", eyebrow: "FON ANALİZİ", nav: "genel" },
  karsilastir: { mod: compare, title: "Karşılaştır", eyebrow: "FON KIYASLAMA" },
  backtest: { mod: backtest, title: "Quant / Backtest", eyebrow: "GEÇMİŞ A+ PERFORMANSI" },
  simulasyon: { mod: simulation, title: "Portföy Simülasyonu", eyebrow: "AYLIK A+ SEPETİ" },
  portfoykarsilastir: { mod: personal, title: "Model Simülasyonu", eyebrow: "PORTFÖY · MODELLER · KIYASLAR" },
  portfoyrapor: { mod: personal, title: "Portföy Raporu", eyebrow: "KİŞİSEL PORTFÖY RAPORU", nav: "portfoykarsilastir" },
  model: { mod: model, title: "Model Portföyler", eyebrow: "GÜVENLİ · DENGELİ · ATAK" },
  rapor: { mod: report, title: "Fon Akış Raporu", eyebrow: "HAFTALIK · AYLIK AKIŞ" },
  modelrapor: { mod: modelreport, title: "Model Raporu", eyebrow: "AYLIK MODEL PERFORMANSI" },
  metodoloji: { mod: method, title: "Metodoloji", eyebrow: "PUANLAMA & CEZALAR" },
};

const app = document.getElementById("app");
const historyCache = new Map();

export const store = {
  meta: null,
  funds: [],
  byCode: new Map(),
  categories: {},
  _bench: null,
  async benchmarks() {
    if (!this._bench) this._bench = fetch("data/benchmarks.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    return this._bench;
  },
  async history(code) {
    if (!historyCache.has(code)) {
      historyCache.set(code, fetch(`data/history/${encodeURIComponent(code)}.json`).then((r) => (r.ok ? r.json() : null)));
    }
    return historyCache.get(code);
  },
};

async function load() {
  const v = Date.now().toString(36).slice(0, -3); // ~ dakikalık önbellek kırıcı
  const get = (p) => fetch(`${p}?v=${v}`).then((r) => {
    if (!r.ok) throw new Error(`${p}: ${r.status}`);
    return r.json();
  });
  const [meta, funds, categories] = await Promise.all([get("data/meta.json"), get("data/funds.json"), get("data/categories.json")]);
  store.meta = meta;
  store.funds = funds;
  store.categories = categories;
  store.byCode = new Map(funds.map((f) => [f.c, f]));
  document.getElementById("dataStatus").textContent =
    `Son fiyat günü: ${dateTR(meta.lastDataDate)} · ${meta.fundCount} fon derecelendirildi · ` +
    `Veri penceresi: ${dateTR(meta.firstDataDate)} – ${dateTR(meta.lastDataDate)} (${meta.config.historyYears} yıl)`;
  document.getElementById("sideStatus").textContent = `TEFAS · ${dateTR(meta.lastDataDate)}`;
}

function parseRoute() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const [view, arg] = path.split("/");
  return { view: VIEWS[view] ? view : "genel", arg: arg ? decodeURIComponent(arg) : null, params: new URLSearchParams(query) };
}

async function render() {
  const route = parseRoute();
  const def = VIEWS[route.view];
  document.querySelectorAll(".tab").forEach((t) =>
    t.setAttribute("aria-current", t.dataset.view === (def.nav || route.view) ? "page" : "false"));
  document.getElementById("pageTitle").textContent = def.title;
  document.getElementById("pageEyebrow").textContent = def.eyebrow;
  try {
    await def.mod.render(app, route, store);
    if (route.view === "fon" && route.arg) document.getElementById("pageTitle").textContent = route.arg;
  } catch (err) {
    console.error(err);
    app.innerHTML = `<div class="card empty"><h3>Sayfa açılamadı</h3><p>${esc(err.message)}</p></div>`;
  }
  window.scrollTo({ top: 0 });
}

// ----------------------------------------------------------------- tema
const THEME_KEY = "tq-theme";
function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
}
try { applyTheme(localStorage.getItem(THEME_KEY)); } catch { /* özel pencere */ }
document.getElementById("themeBtn").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = dark ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem(THEME_KEY, next); } catch { /* yok say */ }
});

window.addEventListener("hashchange", render);
// ---------------------------------------------------------------- yenile ve denetle
// ↻: sunucuda yeni veri ya da yeni site sürümü varsa sayfa yeniden yüklenir (görünümler veriyi kendi içinde
// önbellekte tuttuğu için en güvenli yol); yoksa "veriler güncel" denir. Her iki durumda derlemedeki denetimin
// (data/checks.json) ve tarayıcıda yüklenen verinin hızlı denetiminin sonucu gösterilir.
const REFRESH_FLAG = "tq-refreshed";
const noStore = (p) => fetch(`${p}${p.includes("?") ? "&" : "?"}r=${Date.now()}`, { cache: "no-store" });

function clientChecks() {
  const errors = [], warnings = [];
  const funds = store.funds || [];
  if (!funds.length) errors.push("fon listesi boş");
  const codes = new Set();
  for (const f of funds) {
    if (codes.has(f.c)) errors.push(`tekrarlanan fon kodu: ${f.c}`);
    codes.add(f.c);
    if (typeof f.s !== "number" || !Number.isFinite(f.s) || f.s < 0 || f.s > 100) errors.push(`geçersiz skor: ${f.c}`);
  }
  const last = store.meta?.lastDataDate;
  const age = last ? Math.round((Date.now() - Date.parse(`${last}T18:00:00+03:00`)) / 86400000) : null;
  if (age != null && age > 6) warnings.push(`son fiyat günü ${dateTR(last)} (${age} gün önce)`);
  return { errors: errors.slice(0, 10), warnings };
}

function showChecks(server, fresh) {
  const local = clientChecks();
  const errors = [...(server?.errors || []), ...local.errors];
  // Derleme denetimi zaten "son fiyat günü" uyarısı verdiyse tarayıcıdaki aynı uyarı tekrarlanmaz
  const serverStale = (server?.warnings || []).some((w) => w.startsWith("son fiyat"));
  const warnings = [...(server?.warnings || []), ...local.warnings.filter((w) => !(serverStale && w.startsWith("son fiyat")))];
  const head = `${fresh ? "Yeni veriler yüklendi" : "Veriler güncel"} · son fiyat ${dateTR(store.meta?.lastDataDate)}`;
  toast(errors.length ? `${head} · ${errors.length} veri hatası` : warnings.length ? `${head} · ${warnings.length} uyarı` : `${head} · denetim: sorun yok`);
  const panel = document.getElementById("checkPanel");
  if (!panel) return;
  if (!errors.length && !warnings.length) { panel.hidden = true; return; }
  panel.innerHTML = `<section class="card check-card ${errors.length ? "has-error" : ""}">
    <div class="card-head"><h2>Veri denetimi</h2><button class="icon-btn" type="button" id="checkClose" aria-label="Kapat">✕</button></div>
    ${server?.at ? `<p class="dim">Derleme denetimi: ${esc(new Date(server.at).toLocaleString("tr-TR"))}</p>` : ""}
    <ul>${errors.map((e) => `<li class="down"><b>Hata:</b> ${esc(e)}</li>`).join("")}${warnings.map((w) => `<li><b>Uyarı:</b> ${esc(w)}</li>`).join("")}</ul></section>`;
  panel.hidden = false;
  panel.querySelector("#checkClose").addEventListener("click", () => (panel.hidden = true));
}

async function refreshSite() {
  const btn = document.getElementById("refreshBtn");
  if (btn.disabled) return;
  btn.disabled = true;
  btn.classList.add("spinning");
  try {
    const [meta, html, checks] = await Promise.all([
      noStore("data/meta.json").then((r) => r.json()),
      noStore("./").then((r) => (r.ok ? r.text() : "")).catch(() => ""),
      noStore("data/checks.json").then((r) => (r.ok ? r.json() : null)).catch(() => null),
    ]);
    const cur = document.querySelector('script[type="module"][src*="assets/js/app.js"]')?.getAttribute("src");
    const next = html.match(/src="([^"]*assets\/js\/app\.js)"/)?.[1];
    if (meta.generated !== store.meta?.generated || meta.lastDataDate !== store.meta?.lastDataDate || (cur && next && cur !== next)) {
      try { sessionStorage.setItem(REFRESH_FLAG, "1"); } catch { /* yok say */ }
      location.reload();
      return;
    }
    showChecks(checks, false);
  } catch {
    toast("Yenilenemedi · internet bağlantını kontrol et");
  } finally {
    btn.disabled = false;
    btn.classList.remove("spinning");
  }
}
document.getElementById("refreshBtn")?.addEventListener("click", refreshSite);

initPush().catch((err) => console.warn("bildirim kurulumu", err));
load().then(async () => {
  let refreshed = false;
  try { refreshed = sessionStorage.getItem(REFRESH_FLAG) === "1"; sessionStorage.removeItem(REFRESH_FLAG); } catch { /* yok say */ }
  if (refreshed) showChecks(await noStore("data/checks.json").then((r) => (r.ok ? r.json() : null)).catch(() => null), true);
}).then(render).catch((err) => {
  app.innerHTML = `<div class="card empty"><h3>Veriler yüklenemedi</h3><p>${esc(err.message)}</p></div>`;
});
