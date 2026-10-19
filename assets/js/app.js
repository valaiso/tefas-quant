// TEFAS Quant - uygulama girişi: veri yükleme, yönlendirme, tema, arama
import { esc, dateTR, debounce, searchFunds } from "./util.js";
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
import * as deger from "./views/deger.js";

const VIEWS = {
  genel: { mod: overview, title: "Genel Bakış", eyebrow: "PİYASA ÖZETİ" },
  siralama: { mod: ranking, title: "Fon Sıralaması", eyebrow: "KATEGORİ İÇİ DERECELENDİRME" },
  bes: { mod: bes, title: "BES Fonları", eyebrow: "BİREYSEL EMEKLİLİK FONLARI" },
  deger: { mod: deger, title: "Değer", eyebrow: "FON + BES DAĞILIMI DEĞERLENDİRME" },
  fon: { mod: fund, title: "Fon Detayı", eyebrow: "FON ANALİZİ", nav: "genel" },
  karsilastir: { mod: compare, title: "Karşılaştır", eyebrow: "FON KIYASLAMA" },
  backtest: { mod: backtest, title: "Quant / Backtest", eyebrow: "GEÇMİŞ A+ PERFORMANSI" },
  simulasyon: { mod: simulation, title: "Portföy Simülasyonu", eyebrow: "AYLIK A+ SEPETİ" },
  portfoy: { mod: personal, title: "Portföy Özeti", eyebrow: "KİŞİSEL PORTFÖY" },
  portfoykarsilastir: { mod: personal, title: "Modellerle Karşılaştır", eyebrow: "PORTFÖY · MODELLER · KIYASLAR" },
  portfoyrapor: { mod: personal, title: "Portföy Raporu", eyebrow: "KİŞİSEL PORTFÖY RAPORU", nav: "portfoy" },
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

// ---------------------------------------------------------------- arama
const searchInput = document.getElementById("globalSearch");
const searchList = document.getElementById("searchResults");
searchInput.addEventListener("input", debounce(() => {
  const q = searchInput.value.trim();
  if (!q) { searchList.hidden = true; return; }
  const hits = searchFunds(store.funds, q, { limit: 10 });
  searchList.innerHTML = hits.length
    ? hits.map((f) => `<a class="ac-item" href="#/fon/${encodeURIComponent(f.c)}"><b class="mono">${esc(f.c)}</b><span class="ac-name">${esc(f.n)}</span></a>`).join("")
    : `<div class="ac-item dim">Sonuç yok</div>`;
  searchList.hidden = false;
}, 80));
searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") searchList.querySelector("a")?.click();
  if (e.key === "Escape") searchList.hidden = true;
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".search")) searchList.hidden = true;
  if (e.target.closest(".ac-item")) { searchList.hidden = true; searchInput.value = ""; }
});

window.addEventListener("hashchange", render);
load().then(render).catch((err) => {
  app.innerHTML = `<div class="card empty"><h3>Veriler yüklenemedi</h3><p>${esc(err.message)}</p></div>`;
});
