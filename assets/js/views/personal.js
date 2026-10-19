// Kişisel portföy: Analiz'deki gerçek portföy (Model Simülasyonu sayfası ve A4 Portföy Raporu).
//
// Portföy herkese açık siteye hiç yazılmaz. Sayfa açıldığında tarayıcıda okunur:
//   1. Analiz hesabı: aynı kökende (valaiso.github.io) Analiz'in Supabase oturumu paylaşılır,
//      portfolio_state satırı kullanıcının kendi yetkisiyle (RLS) çekilir.
//   2. Bu tarayıcıdaki Analiz kaydı (localStorage "tefas-portfoy-v1").
//   3. Aylık e-postada CI, portföyü sayfaya window.__TQ_PORTFOLIO__ olarak verir.
// Pozisyonlar Analiz Panel'in kaydettiği aylık fotoğraflardan (monthlySnapshots), getiri günlük değer kaydından
// (valueHistory, para giriş/çıkışından arındırılmış) gelir; modellerle portföy kaydının başladığı günden kıyaslanır.
import { esc, num, dateTR, monthLabel } from "../util.js";
import { lineChart } from "../chart.js";
import * as R from "./modelreport.js";
import * as PR from "../portfolio-report.js";

const ANALIZ = new URL("/Analiz/", "https://valaiso.github.io").href;
const SUPABASE_URL = "https://jqmfvinbzgqyitqquzdc.supabase.co";
const SUPABASE_KEY = "sb_publishable_uw979hCwS6xyLRTexQX55A_ZqgWidDs";  // tarayıcı anahtarı; veriyi RLS korur
const LOCAL_KEY = "tefas-portfoy-v1";
const MODEL_COLORS = { guvenli: "#0b7a45", dengeli: "#1f5fbf", atak: "#db2777", bes: "#0891b2",
  bes_koruyucu: "#64748b", bes_dengeli: "#0891b2", bes_buyume: "#7c2d12" };
const PORT_COLOR = "#0b2a5b";
// Ekrandaki grafik (koyu / açık tema): lacivert ve mavi koyu zeminde kayboluyordu
const SCREEN_COLORS = { guvenli: "#10b981", dengeli: "#f59e0b", atak: "#ec4899", bes: "#06b6d4",
  bes_koruyucu: "#94a3b8", bes_dengeli: "#06b6d4", bes_buyume: "#ef4444" };
const tl = (v) => (v == null || !isFinite(v) ? "—" : `${num(v, 0)} ₺`);
const tlS = (v) => (v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v), 0)} ₺`);

// ------------------------------------------------------------------ portföy durumu
let statePromise = null;
function portfolioState() {
  return (statePromise ||= (async () => {
    if (window.__TQ_PORTFOLIO__) return { state: window.__TQ_PORTFOLIO__, source: "rapor" };
    let local = null;
    try { local = JSON.parse(localStorage.getItem(LOCAL_KEY)); } catch { /* özel pencere */ }
    try {
      const { createClient } = await import("https://esm.sh/@supabase/supabase-js@2.117.2");
      const sb = createClient(SUPABASE_URL, SUPABASE_KEY, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false } });
      const { data: { session } } = await sb.auth.getSession();
      if (session) {
        const { data, error } = await sb.from("portfolio_state").select("state_json, updated_at").eq("user_id", session.user.id).maybeSingle();
        if (!error && data?.state_json) return { state: data.state_json, source: "hesap", updatedAt: data.updated_at };
      }
    } catch (err) {
      console.warn("Analiz hesabı okunamadı", err);
    }
    return local ? { state: local, source: "tarayıcı" } : null;
  })());
}

/** Analiz Panel'in kaydettiği en son aylık pozisyon fotoğrafı. */
function latestSnapshot(state) {
  const snaps = Object.entries(state?.monthlySnapshots || {}).filter(([, s]) => Array.isArray(s?.rows) && s.rows.length);
  if (!snaps.length) return null;
  const [, s] = snaps.sort(([a], [b]) => a.localeCompare(b)).at(-1);
  return s;
}

// ------------------------------------------------------------------ Analiz fiyat verisi
let analizPromise = null;
function analiz() {
  return (analizPromise ||= Promise.all(["calendar.json", "benchmarks.json", "funds.json"].map((f) =>
    fetch(`${ANALIZ}data/${f}`).then((r) => { if (!r.ok) throw new Error(`Analiz ${f}: ${r.status}`); return r.json(); })))
    .then(([cal, bench, funds]) => ({ cal, bench, meta: new Map(funds.map((f) => [f.code, f])) })));
}
/** Takvimde verilen güne kadarki son indeks. */
function idxOn(cal, iso) {
  let lo = 0, hi = cal.length - 1, ans = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (cal[m] <= iso) { ans = m; lo = m + 1; } else hi = m - 1; }
  return ans;
}

/**
 * Pozisyonlar: fotoğraftaki satırlar + Analiz'den ad ve tür.
 * Nakit ayrı bir satır olarak eklenir.
 */
async function positions(snap) {
  const az = await analiz();
  const rows = snap.rows.filter((r) => r.value > 0).map((r) => {
    const m = az.meta.get(r.code) || {};
    return { code: r.code, name: m.name || r.label || r.code, group: r.group || "Diğer", label: r.label || m.cat || "",
      value: r.value, pl: r.totalPLTRY, plPct: r.totalPct, kind: m.kind, frozen: r.frozen };
  });
  if (snap.cash > 0) rows.push({ code: "NAKİT", name: "Nakit (TL)", group: "Nakit", label: "", value: snap.cash, cash: true });
  const total = rows.reduce((s, r) => s + r.value, 0);
  for (const r of rows) r.w = total ? (r.value / total) * 100 : 0;
  return { rows: rows.sort((a, b) => b.value - a.value), total, az };
}

// ------------------------------------------------------------------ gerçek portföy + günlük model serileri
/** Kayıtlı günlük değerlerden para giriş/çıkışından arındırılmış portföy endeksi (ilk kayıt = 100). */
function portfolioIndex(state) {
  const hist = state?.valueHistory || {};
  const flows = Array.isArray(state?.cashflows) ? state.cashflows : [];
  const dates = Object.keys(hist).filter((k) => hist[k] > 0).sort();
  const values = [];
  let level = 100;
  dates.forEach((d, i) => {
    if (i > 0) {
      const flow = flows.filter((f) => f.date > dates[i - 1] && f.date <= d).reduce((s, f) => s + (Number(f.amount) || 0), 0);
      const prev = hist[dates[i - 1]];
      if (prev > 0) level *= (hist[d] - flow) / prev;
    }
    values.push(level);
  });
  return { dates, values };
}

/** Kaynak tarih/değerlerini hedef takvime ileri doldurur; kaynağın ilk gününden önce (ve until'den sonra) boş. */
function ffill(srcDates, srcVals, dates, until = null) {
  const out = new Array(dates.length).fill(null);
  let j = 0, last = null;
  for (let i = 0; i < dates.length; i++) {
    while (j < srcDates.length && srcDates[j] <= dates[i]) { if (srcVals[j] != null) last = srcVals[j]; j++; }
    if (until && dates[i] > until) continue;
    out[i] = last;
  }
  return out;
}

/**
 * Günlük karşılaştırma seti: Model Raporu verisinin günlük serileri (fon ve BES modelleri, kıyaslar)
 * + gerçek portföy endeksi, ortak takvimde. Portföy ilk kayıttan önce boştur (veri yok).
 */
async function dailySet(state) {
  const rep = await R.loadModelReport();
  const D = rep?.daily;
  if (!D) return null;
  const pf = portfolioIndex(state);
  const dates = [...new Set([...D.dates, ...pf.dates])].sort();
  const series = {};
  for (const [k, v] of Object.entries(D.series)) series[k] = ffill(D.dates, v, dates);
  const portfolio = pf.dates.length ? ffill(pf.dates, pf.values, dates, pf.dates[pf.dates.length - 1]) : dates.map(() => null);
  const models = rep.models.map((m) => ({ key: m.key, label: m.label, kind: m.kind })).filter((m) => series[m.key]);
  const bench = R.BENCH.filter(([b]) => series[b]).map(([key, label, color]) => ({ key, label, color }));
  return { rep, dates, series, portfolio, models, bench, pfirst: pf.dates[0] || null, plast: pf.dates[pf.dates.length - 1] || null, pdays: pf.dates.length };
}

/** Bir serinin [from, to] arasındaki getirisi (%): from'dan sonraki ilk dolu gün → to'ya kadarki son dolu gün. */
function spanRet(ds, v, from, to) {
  let a = null, b = null;
  for (let i = 0; i < ds.dates.length; i++) {
    const d = ds.dates[i];
    if (d < from || d > to || v[i] == null) continue;
    if (a == null) a = v[i];
    b = v[i];
  }
  return a && b ? (b / a - 1) * 100 : null;
}
const isoMinus = (iso, { days = 0, months = 0 }) => {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  d.setUTCMonth(d.getUTCMonth() - months);
  return d.toISOString().slice(0, 10);
};
const fundGrade = (store, code) => store.byCode.get(code)?.g;

// ------------------------------------------------------------------ boş durum
function emptyState(app, why) {
  app.innerHTML = `<section class="method-intro card">
    <h2>Kişisel portföy <span class="model-tag">ANALİZ</span></h2>
    <p>${why}</p>
    <p>Portföy, <a href="${ANALIZ}#panel" target="_blank" rel="noopener">Analiz</a> sitesindeki hesabından okunur. Bu tarayıcıda
      Analiz'e giriş yapıp <b>Panel</b>'i bir kez açman yeterli: Panel her açılışta ayın pozisyon fotoğrafını hesabına kaydeder,
      bu sayfa da onu kullanır. Portföy bilgisi TEFAS Quant'ın yayımlanan dosyalarına yazılmaz, yalnızca senin tarayıcında görünür.</p>
  </section>`;
}

async function loadAll(app) {
  app.innerHTML = `<div class="loading"><div class="spinner"></div><p>Portföy okunuyor…</p></div>`;
  const ps = await portfolioState();
  if (!ps) { emptyState(app, "Bu tarayıcıda Analiz hesabı ya da kaydı bulunamadı."); return null; }
  const snap = latestSnapshot(ps.state);
  if (!snap) { emptyState(app, "Hesapta henüz aylık pozisyon fotoğrafı yok."); return null; }
  const pos = await positions(snap);
  return { ps, snap, pos };
}

// ------------------------------------------------------------------ Model Simülasyonu (gerçek portföy + modeller)
const WINDOWS = [["1h", "1 Hafta", { days: 7 }], ["1a", "1 Ay", { months: 1 }], ["3a", "3 Ay", { months: 3 }], ["6a", "6 Ay", { months: 6 }],
  ["1y", "1 Yıl", { months: 12 }], ["3y", "3 Yıl", { months: 36 }], ["bas", "Başından Beri", null]];
const st = { win: "bas" };

async function renderCompare(app) {
  const d = await loadAll(app);
  if (!d) return;
  const ds = await dailySet(d.ps.state);
  if (!ds) { app.innerHTML = `<div class="card empty"><h3>Model verisi yüklenemedi</h3></div>`; return; }
  const end = ds.dates[ds.dates.length - 1];
  app.innerHTML = `
  <section class="method-intro card">
    <h2>Model Simülasyonu <span class="model-tag">PORTFÖY · MODELLER</span></h2>
    <p>Gerçek portföyün (Analiz'in günlük değer kaydından, para giriş ve çıkışlarından arındırılmış) Güvenli, Dengeli, Atak fon modelleri,
      BES Koruyucu, Dengeli, Büyüme modelleri ve PPF, TÜFE, altın, dolar, S&P 500 ile aynı günlerde karşılaştırılır.
      Portföy kaydı <b>${dateTR(ds.pfirst)}</b> tarihinde başladı (${ds.pdays} kayıtlı gün); bu tarihten önce portföy için veri yoktur,
      grafikte yalnızca modeller ve kıyaslar görünür.</p>
    <div class="btn-row"><a class="btn btn-primary" href="#/portfoyrapor">▤ Portföy raporu (PDF)</a></div>
  </section>
  <section class="card">
    <div class="card-head"><h2>Birikimli getiri</h2>
      <div class="seg" id="pfWin">${WINDOWS.map(([k, l]) => `<button data-w="${k}" aria-pressed="${k === st.win}">${l}</button>`).join("")}</div></div>
    <div class="chart" id="pfChart"></div>
    <p class="chart-note dim" id="pfNote"></p>
    <div class="table-wrap"><table class="model-table" id="pfStats"></table></div>
  </section>
  <section class="card">
    <div class="card-head"><h2>Aylık getiriler (%)</h2><span class="sub">Portföy kaydının başladığı aydan bu yana</span></div>
    <div class="table-wrap"><table class="model-table" id="pfMonths"></table></div>
  </section>`;

  const draw = () => {
    const w = WINDOWS.find(([k]) => k === st.win);
    const start = w[2] ? isoMinus(end, w[2]) : (ds.pfirst || ds.dates[0]);
    // Model ve kıyaslar dönem başında 100'den başlar. Portföy kaydı dönemin içinde başlıyorsa portföy çizgisi
    // o gün PPF'nin seviyesinden başlatılır (kısa geçmişli fon için yaygın gösterim); hepsi tek noktada sıkışmaz.
    const late = ds.pfirst && ds.pfirst > start;
    const i0 = ds.dates.findIndex((x) => x >= start);
    const dates = ds.dates.slice(i0);
    const rebase = (v, from = start, level = 100) => {
      const w2 = v.slice(i0);
      const ia = dates.findIndex((x, i) => x >= from && w2[i] != null);
      const b = ia >= 0 ? w2[ia] : null;
      return w2.map((x) => (x == null || !b ? null : (x / b) * level));
    };
    const ppf = ds.series.ppf ? rebase(ds.series.ppf) : null;
    const ip = late ? dates.findIndex((x) => x >= ds.pfirst) : -1;
    const pLevel = late && ppf && ip >= 0 ? ppf.slice(0, ip + 1).filter((x) => x != null).pop() || 100 : 100;
    const series = [
      { name: "Portföyüm (gerçek)", d: dates, v: rebase(ds.portfolio, late ? ds.pfirst : start, pLevel), color: "var(--text)" },
      ...ds.models.map((m) => ({ name: m.label, d: dates, v: rebase(ds.series[m.key]), color: SCREEN_COLORS[m.key] || MODEL_COLORS[m.key] })),
      ...ds.bench.map((b) => ({ name: b.label, d: dates, v: rebase(ds.series[b.key]), color: b.color, dashed: true })),
    ];
    lineChart(app.querySelector("#pfChart"), series, { base: 100, height: 330, format: (v) => num(v, 1) });
    app.querySelector("#pfNote").textContent = `${dateTR(dates[0])} – ${dateTR(end)} · dönem başı = 100`
      + (late ? ` · portföy kaydı ${dateTR(ds.pfirst)} tarihinde başladığı için portföy çizgisi o gün PPF'nin seviyesinden başlar; karşılaştırma için tablodaki "Portföy kaydından bu yana" sütununa bak` : "")
      + " · model ve kıyaslar günlük, portföy Analiz'in kayıtlı günleri";
    const from = ds.pfirst && ds.pfirst > start ? ds.pfirst : start;
    const pRet = ds.pfirst ? spanRet(ds, ds.portfolio, from, end) : null;
    const rows = [
      { name: "Portföyüm (gerçek)", self: true, v: ds.portfolio },
      ...ds.models.map((m) => ({ name: m.label, v: ds.series[m.key] })),
      ...ds.bench.map((b) => ({ name: b.label, v: ds.series[b.key], bench: true })),
    ];
    app.querySelector("#pfStats").innerHTML = `<thead><tr><th class="left">Portföy / model / kıyas</th><th>Seçilen dönem</th>
        <th>Portföy kaydından bu yana (${dateTR(from)})</th><th>Portföyüme göre</th></tr></thead>
      <tbody>${rows.map((r) => {
        const t = spanRet(ds, r.v, start, end), c = spanRet(ds, r.v, from, end);
        const diff = r.self || c == null || pRet == null ? null : pRet - c;
        return `<tr class="${r.self ? "is-self" : ""}"><td class="left">${r.self ? `<b>${esc(r.name)}</b>` : esc(r.name)}</td>
          <td class="${R.tone(t)}">${r.self && ds.pfirst > start ? "—" : R.pctS(t, 2)}</td>
          <td class="${R.tone(c)}"><b>${R.pctS(c, 2)}</b></td>
          <td class="${R.tone(diff)}">${r.self ? "—" : diff == null ? "—" : `${diff >= 0 ? "önde " : "geride "}${num(Math.abs(diff), 2)} puan`}</td></tr>`;
      }).join("")}</tbody>`;
  };

  // Aylık tablo: portföy kaydının başladığı aydan bugüne (her ay, önceki ayın son günü → ayın son günü)
  const pm = monthRows(ds);
  const cols = [["Portföyüm", ds.portfolio, true], ...ds.models.map((m) => [m.label, ds.series[m.key]]), ...ds.bench.map((b) => [b.label, ds.series[b.key]])];
  app.querySelector("#pfMonths").innerHTML = pm.length ? `<thead><tr><th class="left">Ay</th>${cols.map(([l]) => `<th>${esc(l)}</th>`).join("")}</tr></thead>
    <tbody>${pm.slice().reverse().map((m) => `<tr><td class="left">${R.monthLong(m.month + "-01")}${m.partial ? ` <span class="dim">(${dateTR(m.to)}'e kadar)</span>` : ""}</td>
      ${cols.map(([, v, self]) => { const x = spanRet(ds, v, m.from, m.to); return `<td class="${R.tone(x)}">${self ? `<b>${R.pctS(x, 2)}</b>` : R.pctS(x, 2)}</td>`; }).join("")}</tr>`).join("")}</tbody>`
    : `<tbody><tr><td class="empty">Henüz portföy kaydı yok.</td></tr></tbody>`;

  app.querySelector("#pfWin").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    st.win = b.dataset.w;
    app.querySelectorAll("#pfWin button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    draw();
  });
  draw();
}

/** Portföy kaydının başladığı aydan bugüne ay dilimleri: ilk ay ilk kayıttan, sonrakiler önceki ayın son gününden başlar. */
function monthRows(ds) {
  if (!ds.pfirst) return [];
  const out = [];
  const end = ds.plast || ds.dates[ds.dates.length - 1];
  let m = ds.pfirst.slice(0, 7);
  while (m <= end.slice(0, 7)) {
    const inMonth = ds.dates.filter((d) => d.startsWith(m) && d <= end);
    const before = ds.dates.filter((d) => d < `${m}-01`).pop();
    const from = m === ds.pfirst.slice(0, 7) ? ds.pfirst : before;
    // Tek günlük ay (ör. ilk kayıt ayın son günüyse) getiri üretmez, atlanır
    if (inMonth.length && inMonth[inMonth.length - 1] > from) out.push({ month: m, from, to: inMonth[inMonth.length - 1], partial: m === PR.istanbulMonth() });
    const [y, mo] = m.split("-").map(Number);
    m = mo === 12 ? `${y + 1}-01` : `${y}-${String(mo + 1).padStart(2, "0")}`;
  }
  return out;
}

// ------------------------------------------------------------------ A4 Portföy Raporu
// Sayfa 1-2: Analiz'in aylık portföy raporu (gerçek kayıtlar: zaman ağırlıklı getiri, değer köprüsü,
// dağılım, katkılar, risk) + aynı günlerde TEFAS Quant fon ve BES modelleri. Sayfa 3: portföy kaydının
// başladığı günden bu yana gerçek portföy, modeller ve kıyaslar.
const pctP = (v, d = 2) => (v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}%${num(Math.abs(v), d)}`);
const pa = {
  block: (title, dot, body) => `<section class="rp-block"><h3><span class="rp-dot ${dot || "brand"}"></span>${title}</h3>${body}</section>`,
  empty: (t) => `<div class="pa-empty">${esc(t)}</div>`,
  kpi: (label, value, sub, tone = "") => `<div class="${tone}"><span>${label}</span><b>${value}</b>${sub ? `<em>${sub}</em>` : ""}</div>`,
  diverging(rows, fmt) {
    const max = Math.max(1e-9, ...rows.filter((r) => !r.total).map((r) => Math.abs(r.value || 0)));
    return `<div class="pa-cats">${rows.map((r) => `<div class="pa-cat${r.main ? " main" : ""}${r.total ? " total" : ""}${r.model ? " model" : ""}">
      <span class="pa-cat-name">${esc(r.label)}</span>
      ${r.total ? "<span></span>" : `<span class="rp-cat-track"><span class="rp-cat-mid"></span>${r.value != null && Math.abs(r.value) > 1e-9
        ? `<i class="${r.value >= 0 ? "up" : "down"}" style="width:${((Math.abs(r.value) / max) * 50).toFixed(1)}%"></i>` : ""}</span>`}
      <span class="pa-cat-val ${r.total ? "" : R.tone(r.value)}">${r.value != null && isFinite(r.value) ? fmt(r.value, r) : "—"}</span></div>`).join("")}</div>`;
  },
};
const ALLOC_COLORS = ["#1f5fbf", "#db2777", "#7c3aed", "#c58b12", "#0b7a45", "#0891b2", "#d6404a", "#64748b", "#ea580c", "#4f46e5"];

const dayFmt = (d) => `${d.slice(8, 10)}.${d.slice(5, 7)}`;
/** Günlük setteki bir serinin verilen günlerdeki değeri (ileri doldurulmuş). */
const valuesOn = (ds, v, days) => ffill(ds.dates, v, days);

function reportPages(rep, ds, store, pos, snap) {
  const m = rep.periods.month;
  const infl = rep.inflation || {};
  const shortNote = `Bu dönem için en az iki kayıtlı gün gerekiyor (ilk kayıt ${dateTR(rep.firstDate)}). Getiri ve kıyaslar sonraki işlem günlerinde dolacak.`;
  // Modeller portföyle aynı günlerde: ay (önceki ayın son kaydı → ayın son kaydı), yılbaşı ve başlangıç (ilk kayıt)
  const span = (k, p) => (p && ds ? spanRet(ds, ds.series[k], p.startDate, p.endDate) : null);
  const models = (ds?.models || []).map((x) => ({ key: x.key, label: x.kind === "fon" ? `${x.label} modeli` : x.label,
    month: span(x.key, rep.periods.month), ytd: span(x.key, rep.periods.ytd), inception: span(x.key, rep.periods.inception) }));
  const real = rep.comparisonRows[0]?.realMonth;
  const change = m ? m.endValue - m.startValue : null;
  const generated = new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium" }).format(new Date());
  const period = `${m ? `${dateTR(m.startDate)} – ${dateTR(m.endDate)}` : rep.label} · ${rep.risk.positionCount || 0} varlık · ilk kayıt ${dateTR(rep.firstDate)}`;
  const total = 3;
  const foot = (n) => `<footer class="rp-footer"><span>Kaynak: Analiz (Midas adet ve fiyatları, günlük değer kaydı), TEFAS, Yahoo Finance ve TCMB. Getiriler zaman ağırlıklıdır; para yatırma/çekme getiri sayılmaz. Model getirileri TEFAS Quant fon ve BES modellerinin portföyle aynı günler arasındaki getirisidir. Yatırım tavsiyesi değildir.</span>
    <span>Oluşturma ${generated} · Sayfa ${n} / ${total}</span></footer>`;
  const cover = (title, sub) => R.cover(rep.complete ? "AYLIK RAPOR" : "ARA RAPOR", title, sub, "KİŞİSEL PORTFÖY RAPORU");

  // Öne çıkanlar (Analiz kuralları + modeller)
  const insights = [];
  const fmt = (v) => pctP(v);
  const pts = (v) => `${num(Math.abs(v), 1)} puan`;
  if (m?.twr != null) {
    insights.push(`Portföy bu ay para giriş/çıkışları hariç ${fmt(m.twr)} getiri sağladı.`);
    for (const row of rep.comparisonRows.slice(1)) {
      if (row.month == null || !["BIST100", "SP500TL", "PARAPIYASASI"].includes(row.key)) continue;
      const diff = m.twr - row.month;
      insights.push(`${row.label} ${fmt(row.month)}; portföy ${pts(diff)} ${diff >= 0 ? "önde" : "geride"}.`);
    }
    const bestModel = models.filter((x) => x.month != null).sort((a, b) => b.month - a.month)[0];
    if (bestModel) {
      const diff = m.twr - bestModel.month;
      insights.push(`Ayın en iyi modeli ${bestModel.label} ${fmt(bestModel.month)}; portföy ${pts(diff)} ${diff >= 0 ? "önde" : "geride"}.`);
    }
    if (infl.month != null) insights.push(`Enflasyon (TÜFE) dönemde ${fmt(infl.month)}; reel getiri ${fmt(real)}.`);
  }
  if (rep.winners[0]) insights.push(`Ayın en çok kazandıranı ${rep.winners[0].code}, en çok kaybettireni ${rep.losers[0]?.code || "—"}.`);

  // ------------------------------------------------ sayfa 1
  const cmpRows = rep.comparisonRows.filter((r) => r.key !== "TUFE" || r.month != null);
  const diverging = [
    { label: "Portföyüm", value: rep.comparisonRows[0]?.month, main: true },
    ...models.map((x) => ({ label: x.label, value: x.month, model: true })),
    ...cmpRows.slice(1).filter((r) => r.month != null).map((r) => ({ label: r.label, value: r.month })),
  ];
  const tableRow = (label, cls, monthV, realV, ytdV, incV, incReal) => `<tr class="${cls}"><td>${esc(label)}</td>
    ${[monthV, realV, ytdV, incV, incReal].map((v) => `<td class="r ${R.tone(v)}">${pctP(v)}</td>`).join("")}</tr>`;
  const bridge = m ? [
    { label: "Ay başı değeri", value: m.startValue, total: true },
    { label: "Yatırılan para", value: m.deposits },
    { label: "Çekilen para", value: -m.withdrawals },
    { label: "Temettü", value: m.dividends },
    { label: "Piyasa etkisi", value: m.market },
    { label: "Ay sonu değeri", value: m.endValue, total: true },
  ] : [];
  const cd = rep.chart.dates;
  const rebase0 = (v) => { const b = v.find((x) => x != null); return v.map((x) => (x == null || !b ? null : (x / b) * 100)); };
  const chartLines = [
    ...rep.chart.series.filter((s) => ["PORTFOY", "PARAPIYASASI", "GRAMALTIN", "BIST100"].includes(s.key)).map((s) => ({
      name: s.key === "PORTFOY" ? "Portföyüm" : s.label, v: s.values,
      color: { PORTFOY: PORT_COLOR, PARAPIYASASI: "#64748b", GRAMALTIN: "#c58b12", BIST100: "#9ca3af" }[s.key],
      w: s.key === "PORTFOY" ? 2.8 : 1.2, dash: s.key !== "PORTFOY" })),
    ...(ds ? ds.models.map((x) => ({ name: x.label, v: rebase0(valuesOn(ds, ds.series[x.key], cd)), color: MODEL_COLORS[x.key], w: 1.5 })) : []),
  ];

  const page1 = `<article class="rp-page">
    ${cover(`${rep.label} Portföy Raporu`, period)}
    <div class="rp-kpis">
      ${pa.kpi("Ay sonu değeri", tl(m?.endValue ?? rep.endTotal), change != null ? `${tlS(change)} değişim` : "ay başı kaydı bekleniyor")}
      ${pa.kpi("Aylık getiri", pctP(m?.twr), "para hareketlerinden arındırılmış", R.tone(m?.twr))}
      ${pa.kpi("Reel getiri", pctP(real), "TÜFE düşülmüş", R.tone(real))}
      ${pa.kpi("Net para girişi", m ? tlS(m.deposits - m.withdrawals) : "—", `temettü ${tl(m?.dividends || 0)}`)}
    </div>
    ${pa.block("Bu ayın getirisi: portföy, TEFAS Quant modelleri ve kıyaslar", "brand",
      m ? pa.diverging(diverging, (v) => pctP(v)) : pa.empty(shortNote))}
    ${pa.block("Dönem tablosu", "brand", `<table class="rp-table pa-table pa-compact">
      <thead><tr><th style="width:30%">Portföy / model / endeks</th><th class="r">Bu ay</th><th class="r">Bu ay reel</th><th class="r">Yılbaşından</th><th class="r">Başlangıçtan</th><th class="r">Başl. reel</th></tr></thead>
      <tbody>
        ${tableRow("Portföyüm", "main", rep.comparisonRows[0]?.month, rep.comparisonRows[0]?.realMonth, rep.comparisonRows[0]?.ytd, rep.comparisonRows[0]?.inception, rep.comparisonRows[0]?.realInception)}
        ${models.map((x) => {
          const rl = (v, t) => (v != null && t != null ? ((1 + v / 100) / (1 + t / 100) - 1) * 100 : null);
          const incT = rep.comparisonRows.find((r) => r.key === "TUFE")?.inception;
          return tableRow(x.label, "model", x.month, rl(x.month, infl.month), x.ytd, x.inception, rl(x.inception, incT));
        }).join("")}
        ${cmpRows.slice(1).map((r) => tableRow(r.label, "", r.month, r.realMonth, r.ytd, r.inception, r.realInception)).join("")}
      </tbody></table>
      <p class="pa-note">Yılbaşı ve başlangıç sütunları ${dateTR(rep.firstDate)} tarihli ilk kayıttan itibaren hesaplanır; modeller portföyle aynı günler arasında ölçülür. TÜFE son açıklanan aya kadardır.</p>`)}
    ${pa.block("Dönem içi seyir (başlangıç = 100)", "brand",
      m && cd.length >= 3 ? R.chart(cd, chartLines, 142, 764, dayFmt)
        : pa.empty(m ? `Grafik için en az 3 kayıtlı gün gerekiyor (şu an ${cd.length}); kayıtlar ${dateTR(rep.firstDate)} tarihinde başladı.` : shortNote))}
    <div class="rp-two">
      ${pa.block("Değer köprüsü", "brand", m ? pa.diverging(bridge, (v, r) => (r.total ? tl(v) : tlS(v))) : pa.empty(shortNote))}
      ${pa.block("Öne çıkanlar", "brand", insights.length ? `<ul class="pa-list">${insights.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : pa.empty("Ay ilerledikçe öne çıkan gelişmeler burada özetlenir."))}
    </div>
    ${foot(1)}
  </article>`;

  // ------------------------------------------------ sayfa 2
  const showStart = rep.hasStartSnapshot;
  const moversNote = showStart ? "Bu ay yok" : "Varlık bazında katkı, önceki ay sonu pozisyon kaydı oluşunca görünür.";
  const allocTotal = rep.allocation.reduce((s, r) => s + r.value, 0);
  const valueMax = Math.max(1, ...rep.positions.map((r) => r.value || 0));
  const movers = (rows, tone) => {
    if (!rows.length) return pa.empty(moversNote);
    const max = Math.max(1, ...rows.map((r) => Math.abs(r.contribution || 0)));
    return `<table class="rp-table"><thead><tr><th>#</th><th>Varlık</th><th class="r">Katkı</th><th class="r">Ay içi</th><th class="bar-col"></th></tr></thead>
      <tbody>${rows.map((r, i) => `<tr><td class="rk">${i + 1}</td><td><b class="mono">${esc(r.code)}</b></td>
        <td class="r ${tone}">${tlS(r.contribution)}</td><td class="r ${R.tone(r.monthPct)}">${pctP(r.monthPct, 1)}</td>
        <td class="bar-col"><span class="rp-bar ${tone}"><i style="width:${Math.min(100, (Math.abs(r.contribution) / max) * 100).toFixed(1)}%"></i></span></td></tr>`).join("")}</tbody></table>`;
  };
  const shown = rep.positions.slice(0, 22), rest = rep.positions.slice(22);
  const risk = rep.risk;
  const page2 = `<article class="rp-page">
    ${cover("Pozisyonlar, Dağılım ve Risk", period)}
    <div class="rp-kpis">
      ${pa.kpi("En büyük pozisyon", esc(risk.largestCode || "—"), risk.largestWeight != null ? `portföyün %${num(risk.largestWeight, 1)}'i` : "")}
      ${pa.kpi("İlk 3 varlık", `%${num(risk.top3Weight, 1)}`, `${risk.positionCount} varlık içinde`)}
      ${pa.kpi("En büyük düşüş", pctP(risk.maxDrawdown), "ay içi, zirveden", R.tone(risk.maxDrawdown))}
      ${pa.kpi("Tahmini stopaj", tl(rep.stopajTotal), "satışta fon kârından")}
    </div>
    ${pa.block("Varlık dağılımı", "brand", rep.allocation.length ? `
      <div class="pa-stack">${rep.allocation.map((r, i) => `<span style="flex:${Math.max(0.001, r.value)};background:${ALLOC_COLORS[i % ALLOC_COLORS.length]}" title="${esc(r.label)}"></span>`).join("")}</div>
      <div class="pa-legend">${rep.allocation.map((r, i) => `<div><i style="background:${ALLOC_COLORS[i % ALLOC_COLORS.length]}"></i><span>${esc(r.label)}</span>
        <b>${allocTotal > 0 ? `%${num((r.value / allocTotal) * 100, 1)}` : "—"}</b>${showStart ? `<em>${r.startWeight != null ? `önceki %${num(r.startWeight, 1)}` : "yeni"}</em>` : ""}</div>`).join("")}</div>`
      : pa.empty("Ay sonu pozisyon kaydı yok. Ay içinde Analiz Panel'i bir kez açmak kaydı oluşturur."))}
    <div class="rp-two">
      ${pa.block("En çok kazandıranlar", "up", movers(rep.winners, "up"))}
      ${pa.block("En çok kaybettirenler", "down", movers(rep.losers, "down"))}
    </div>
    ${pa.block("Pozisyonlar", "brand", rep.positions.length ? `<table class="rp-table pa-pos">
      <thead><tr><th style="width:34%">Varlık</th><th class="r">Adet</th><th class="r">Değer</th><th class="r">Ağırlık</th>
        <th class="r">${showStart ? "Ay içi" : "Toplam K/Z"}</th><th class="r">K/Z %</th><th class="r">Not</th><th class="bar-col"></th></tr></thead>
      <tbody>${shown.map((r) => {
        const g = fundGrade(store, r.code);
        return `<tr><td><b class="mono">${esc(r.code)}</b> <span class="nm">${esc(r.name || r.label || "")}</span></td>
          <td class="r">${num(r.units, r.units < 10 ? 4 : 0)}</td><td class="r">${tl(r.value)}</td><td class="r">${r.weight != null ? `%${num(r.weight, 1)}` : "—"}</td>
          ${showStart ? `<td class="r ${R.tone(r.monthPct)}">${r.frozen ? "sabit" : pctP(r.monthPct, 1)}</td>`
            : `<td class="r ${R.tone(r.totalPLTRY)}">${r.frozen ? "temerrüt" : r.totalPLTRY != null ? tlS(r.totalPLTRY) : "—"}</td>`}
          <td class="r ${R.tone(r.totalPct)}">${r.frozen ? "—" : pctP(r.totalPct, 1)}</td>
          <td class="r">${g ? `<span class="rp-grade g-${g === "A+" ? "ap" : g.toLowerCase()}">${esc(g)}</span>` : ""}</td>
          <td class="bar-col"><span class="rp-bar brand"><i style="width:${(((r.value || 0) / valueMax) * 100).toFixed(1)}%"></i></span></td></tr>`;
      }).join("")}${rest.length ? `<tr><td class="dim">Diğer ${rest.length} varlık</td><td></td><td class="r">${tl(rest.reduce((s, r) => s + r.value, 0))}</td>
        <td class="r">%${num(rest.reduce((s, r) => s + (r.weight || 0), 0), 1)}</td><td colspan="4"></td></tr>` : ""}</tbody>
      ${rep.cash > 0.5 ? `<tfoot><tr><td>Nakit ve bekleyen emirler</td><td></td><td class="r">${tl(rep.cash)}</td>
        <td class="r">${rep.endTotal > 0 ? `%${num((rep.cash / rep.endTotal) * 100, 1)}` : "—"}</td><td colspan="4"></td></tr></tfoot>` : ""}
      </table>`
      : pa.empty("Ay sonu pozisyon kaydı yok."))}
    ${pa.block("Notlar", "brand", `<ul class="pa-list">
      <li>Değerler Analiz hesabına kaydedilen günlük toplamlardan gelir (ilk kayıt ${dateTR(rep.firstDate)}); hafta sonları atlanır.</li>
      ${rep.frozenCodes.length ? `<li>${esc(rep.frozenCodes.join(", "))} temerrüttedir; fiyatı Midas'taki değerde sabittir, getiri ve K/Z hesaplanmaz.</li>` : ""}
      <li>Not sütunu TEFAS fonlarının TEFAS Quant derecesidir (A+ en iyi). Model satırları Güvenli, Dengeli, Atak fon modelleri ile BES Koruyucu, Dengeli ve Büyüme modelleridir.</li>
      <li>Kıyaslar: BIST 100, S&P 500 (TL), gram altın, dolar (Yahoo Finance); PPF ortalaması TEFAS para piyasası fonlarından; TÜFE TCMB/TÜİK verisinden.</li>
      <li>Stopaj tahminidir: hisse yoğun fonlarda %0, diğer fonlarda %17,5; portföy değerini etkilemez.</li></ul>`)}
    ${foot(2)}
  </article>`;

  // ------------------------------------------------ sayfa 3: portföy kaydının başlangıcından bugüne
  let page3 = "";
  const p3cover = R.cover("MODEL KARŞILAŞTIRMASI", "Portföy · Modeller · Kıyaslar",
    ds?.pfirst ? `Gerçek portföy, kaydın başladığı ${dateTR(ds.pfirst)} tarihinden ${dateTR(ds.plast)} tarihine kadar · fon ve BES modelleri, PPF, TÜFE, altın, dolar, S&P 500 ile`
      : "Portföy kaydı henüz yok", "KİŞİSEL PORTFÖY RAPORU");
  const p3foot = `<footer class="rp-footer"><span>Portföy getirisi Analiz'in günlük değer kaydından, para giriş ve çıkışlarından arındırılarak hesaplanır; modeller ve kıyaslar aynı günler arasında ölçülür.
    Kayıt ${ds?.pfirst ? dateTR(ds.pfirst) : "—"} tarihinde başladığı için bu sayfa her gün uzar. Yatırım tavsiyesi değildir.</span>
    <span>Oluşturma ${generated} · Sayfa 3 / ${total}</span></footer>`;
  if (!ds || !ds.pfirst || ds.pdays < 2) {
    page3 = `<article class="rp-page">${p3cover}${pa.block("Portföy ve modeller", "brand", pa.empty("Karşılaştırma için en az iki kayıtlı gün gerekiyor."))}${p3foot}</article>`;
  } else {
    const from = ds.pfirst, to = ds.plast;
    const pR = spanRet(ds, ds.portfolio, from, to);
    const rows = [
      { name: "Portföyüm (gerçek)", self: true, v: ds.portfolio },
      ...ds.models.map((x) => ({ name: x.label, v: ds.series[x.key], key: x.key })),
      ...ds.bench.map((b) => ({ name: b.label, v: ds.series[b.key], bench: true, key: b.key })),
    ];
    const withRet = rows.map((r) => ({ ...r, r: spanRet(ds, r.v, from, to) }));
    const bestM = withRet.filter((r) => !r.self && !r.bench && r.r != null).sort((a, b) => b.r - a.r)[0];
    const ppf = withRet.find((r) => r.key === "ppf")?.r, tufe = withRet.find((r) => r.key === "tufe")?.r;
    const months = monthRows(ds).slice(-6);
    const i0 = ds.dates.findIndex((x) => x >= from), i1 = ds.dates.findIndex((x) => x > to);
    const days = ds.dates.slice(i0, i1 < 0 ? undefined : i1);
    const reb = (v) => { const w = v.slice(i0, i1 < 0 ? undefined : i1), b = w.find((x) => x != null); return w.map((x) => (x == null || !b ? null : (x / b) * 100)); };
    page3 = `<article class="rp-page">
      ${p3cover}
      <div class="rp-kpis">
        <div class="${R.tone(pR)}"><span>Portföy · kayıttan bu yana</span><b>${R.pctS(pR, 2)}</b><em>${ds.pdays} kayıtlı gün</em></div>
        <div class="${R.tone(pR - (bestM?.r ?? 0))}"><span>En iyi model: ${esc(bestM?.name || "—")}</span><b>${R.pctS(bestM?.r, 2)}</b><em>Portföye göre ${R.ptsS(pR - (bestM?.r ?? 0))}</em></div>
        <div class="${R.tone(pR - ppf)}"><span>PPF'ye göre</span><b>${R.ptsS(pR - ppf)}</b><em>PPF ${R.pctS(ppf, 2)}</em></div>
        <div class="${R.tone(pR - tufe)}"><span>TÜFE'ye göre (reel)</span><b>${R.ptsS(pR - tufe)}</b><em>TÜFE ${R.pctS(tufe, 2)}</em></div>
      </div>
      ${pa.block(`Birikimli getiri · ${dateTR(from)} = 100`, "brand", days.length >= 3 ? R.chart(days, [
        { name: "Portföyüm", v: reb(ds.portfolio), color: PORT_COLOR, w: 2.8 },
        ...ds.models.map((x) => ({ name: x.label, v: reb(ds.series[x.key]), color: MODEL_COLORS[x.key], w: 1.5 })),
        ...ds.bench.map((b) => ({ name: b.label.replace(" ortalaması", ""), v: reb(ds.series[b.key]), color: b.color, dash: true })),
      ], 220, 764, dayFmt) : pa.empty(`Grafik için en az 3 kayıtlı gün gerekiyor (şu an ${ds.pdays}).`))}
      ${pa.block("Getiriler (kayıttan bu yana ve aylık)", "brand", `<table class="rp-table mr-sum">
        <thead><tr><th>Portföy / model / kıyas</th>${months.map((x) => `<th class="r">${R.monthLong(x.month + "-01")}${x.partial ? "*" : ""}</th>`).join("")}
          <th class="r">Kayıttan bu yana</th><th class="r">Portföye göre</th></tr></thead>
        <tbody>${withRet.map((r) => {
          const diff = r.self || r.r == null || pR == null ? null : pR - r.r;
          return `<tr class="${r.bench ? "mr-bench" : "mr-self"}"><td><b>${esc(r.name)}</b></td>
            ${months.map((x) => { const v = spanRet(ds, r.v, x.from, x.to); return `<td class="r num ${R.tone(v)}">${R.pctS(v, 2)}</td>`; }).join("")}
            <td class="r num ${R.tone(r.r)}"><b>${R.pctS(r.r, 2)}</b></td>
            <td class="r num ${R.tone(diff)}">${r.self ? "—" : diff == null ? "—" : `${diff >= 0 ? "✓ önde " : "✗ geride "}${num(Math.abs(diff), 2)} puan`}</td></tr>`;
        }).join("")}</tbody></table>
        ${months.some((x) => x.partial) ? `<p class="pa-note">* Süren ay, ${dateTR(to)} tarihine kadar.</p>` : ""}`)}
      ${p3foot}
    </article>`;
  }
  return page1 + page2 + page3;
}

async function renderReport(app, store, route) {
  const d = await loadAll(app);
  if (!d) return;
  const { ps, snap, pos } = d;
  const st8 = ps.state;
  const history = st8.valueHistory || {}, snapshots = st8.monthlySnapshots || {};
  const flows = Array.isArray(st8.cashflows) ? st8.cashflows : [], dividends = Array.isArray(st8.dividends) ? st8.dividends : [];
  const months = PR.reportMonths(history, snapshots);
  const want = route?.params?.get("ay");
  const month = months.includes(want) ? want : PR.defaultMonth(history, snapshots);
  const ds = await dailySet(st8);
  const rep = PR.buildMonthlyReport({ month, history, flows, dividends, snapshots, az: pos.az });

  app.innerHTML = `
  <div class="rp-toolbar no-print">
    <div><h2>Kişisel portföy raporu</h2>
      <p class="dim">Analiz'in aylık portföy raporu + TEFAS Quant model portföyleri · PDF için yazdırma penceresinde "PDF olarak kaydet"</p></div>
    <div class="rp-actions"><a class="btn" href="#/portfoykarsilastir">← Model Simülasyonu</a>
      <select id="prMonth" aria-label="Rapor ayı">${months.map((mo) => `<option value="${mo}" ${mo === month ? "selected" : ""}>${PR.monthLabel(mo)}</option>`).join("")}</select>
      <button class="btn btn-primary" id="prPrint" type="button">⤓ PDF olarak indir</button></div>
  </div>
  <div class="rp-doc">${reportPages(rep, ds, store, pos, snap)}</div>`;
  app.querySelector("#prMonth")?.addEventListener("change", (e) => { location.hash = `#/portfoyrapor?ay=${e.target.value}`; });
  app.querySelector("#prPrint").addEventListener("click", () => {
    const prev = document.title;
    document.title = `TEFAS-Quant-Portfoy-Raporu-${month}`;  // PDF dosya adı
    window.print();
    setTimeout(() => (document.title = prev), 500);
  });
}

export async function render(app, route, store) {
  window.__TQ_READY__ = false;
  try {
    if (route.view === "portfoyrapor") await renderReport(app, store, route);
    else await renderCompare(app, store);
  } finally {
    window.__TQ_READY__ = true;  // CI PDF basımı bu bayrağı bekler
  }
}
