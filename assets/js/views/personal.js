// Kişisel portföy: Analiz'deki gerçek portföy (Modellerle Karşılaştır sayfası ve A4 Portföy Raporu).
//
// Portföy herkese açık siteye hiç yazılmaz. Sayfa açıldığında tarayıcıda okunur:
//   1. Analiz hesabı: aynı kökende (valaiso.github.io) Analiz'in Supabase oturumu paylaşılır,
//      portfolio_state satırı kullanıcının kendi yetkisiyle (RLS) çekilir.
//   2. Bu tarayıcıdaki Analiz kaydı (localStorage "tefas-portfoy-v1").
//   3. Aylık e-postada CI, portföyü sayfaya window.__TQ_PORTFOLIO__ olarak verir.
// Pozisyonlar Analiz Panel'in kaydettiği son aylık fotoğraftan (monthlySnapshots), fiyat geçmişleri
// Analiz'in yayımladığı dosyalardan gelir. Karşılaştırma bugünkü pozisyonları geriye doğru tutar.
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
const histCache = new Map();
function history(code) {
  if (!histCache.has(code)) {
    histCache.set(code, fetch(`${ANALIZ}data/history/${encodeURIComponent(code)}.json`)
      .then((r) => (r.ok ? r.json() : null)).catch(() => null)
      .then((h) => {
        if (!h?.p?.length) return null;
        const p = [];
        let last = null;
        for (const v of h.p) { if (v != null && v > 0) last = v; p.push(last); }
        return { i: h.i | 0, p };
      }));
  }
  return histCache.get(code);
}
const priceAt = (h, idx) => (h && idx >= h.i ? h.p[Math.min(idx - h.i, h.p.length - 1)] : null);
/** Takvimde verilen güne kadarki son indeks. */
function idxOn(cal, iso) {
  let lo = 0, hi = cal.length - 1, ans = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (cal[m] <= iso) { ans = m; lo = m + 1; } else hi = m - 1; }
  return ans;
}

/**
 * Pozisyonlar: fotoğraftaki satırlar + Analiz'den ad, tür ve fiyat geçmişi.
 * Nakit ayrı bir satır olarak eklenir (değeri sabit kalır).
 */
async function positions(snap) {
  const az = await analiz();
  const rows = snap.rows.filter((r) => r.value > 0).map((r) => {
    const m = az.meta.get(r.code) || {};
    const usd = r.currency === "USD" || ["US_ETF", "CRYPTO"].includes(m.kind);
    return { code: r.code, name: m.name || r.label || r.code, group: r.group || "Diğer", label: r.label || m.cat || "",
      value: r.value, pl: r.totalPLTRY, plPct: r.totalPct, usd, kind: m.kind, frozen: r.frozen };
  });
  if (snap.cash > 0) rows.push({ code: "NAKİT", name: "Nakit (TL)", group: "Nakit", label: "", value: snap.cash, cash: true });
  const total = rows.reduce((s, r) => s + r.value, 0);
  for (const r of rows) r.w = total ? (r.value / total) * 100 : 0;
  await Promise.all(rows.filter((r) => !r.cash).map(async (r) => { r.hist = await history(r.code); }));
  return { rows: rows.sort((a, b) => b.value - a.value), total, az };
}

/**
 * Bugünkü pozisyonların verilen günlerdeki değeri (TL): her varlık fotoğraf günündeki değerinden
 * kendi fiyatı (ve dolar varlıklarında dolar/TL) oranıyla geriye taşınır. Geçmişi olmayan sabit kalır.
 */
function holdValues(pos, dates, snapDate) {
  const { cal, bench } = pos.az;
  const usd = bench.USDTRY?.values || [];
  const fxAt = (i) => { for (let k = i; k >= 0; k--) if (usd[k] > 0) return usd[k]; return null; };
  const a = idxOn(cal, snapDate || cal[cal.length - 1]);
  return dates.map((d) => {
    const i = idxOn(cal, d);
    if (i < 0) return null;
    let v = 0;
    for (const r of pos.rows) {
      const p0 = priceAt(r.hist, a), p1 = priceAt(r.hist, i);
      let f = r.cash || !p0 || !p1 ? 1 : p1 / p0;
      if (r.usd && !r.cash) { const x0 = fxAt(a), x1 = fxAt(i); if (x0 && x1) f *= x1 / x0; }
      v += r.value * f;
    }
    return v;
  });
}

// ------------------------------------------------------------------ karşılaştırma verisi
/** Portföy, modeller ve kıyaslar aynı aylık noktalarda (Model Rapor'un ay başı noktaları). */
async function compareSet(pos, snap) {
  const rep = await R.loadModelReport();
  if (!rep?.models?.length) return null;
  const ref = rep.models.find((m) => m.kind === "fon") || rep.models[0];
  const pv = holdValues(pos, ref.dates, snap.date);
  const portfolio = { key: "portfoy", label: "Portföyüm", kind: "portfoy", dates: ref.dates, series: { ...ref.series, model: pv } };
  const pointKey = (d, i) => d[i].slice(0, 7) + (i === d.length - 1 && !R.isMonthStart(d, i) ? "+" : "");
  const align = (m) => {
    const map = new Map(m.dates.map((_, i) => [pointKey(m.dates, i), m.series.model[i]]));
    return { ...m, dates: ref.dates, series: { ...ref.series, model: ref.dates.map((_, i) => map.get(pointKey(ref.dates, i)) ?? null) } };
  };
  const list = rep.besProfiles?.length ? [...rep.models.filter((m) => m.kind === "fon"), ...rep.besProfiles] : rep.models;
  return { rep, ref, portfolio, models: list.map((m) => (m === ref ? m : align(m))) };
}

const missingNote = (pos) => {
  const miss = pos.rows.filter((r) => !r.cash && !r.hist).map((r) => r.code);
  return miss.length ? ` Fiyat geçmişi bulunamayan ${miss.length} varlık (${esc(miss.join(", "))}) sabit değerde tutuldu.` : "";
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

// Gerçek getiri: Analiz'in günlük değer kaydından (para giriş/çıkışından arındırılmış)
const realFirst = (state) => Object.keys(state?.valueHistory || {}).filter((k) => state.valueHistory[k] > 0).sort()[0] || null;
function realBlock(d) {
  const st8 = d.ps.state, hist = st8.valueHistory || {};
  const dates = Object.keys(hist).filter((k) => hist[k] > 0).sort();
  if (dates.length < 2) {
    return `<section class="card"><div class="card-head"><h2>Gerçek getirim</h2></div>
      <div class="empty">Gerçek getiri için en az iki günlük kayıt gerekiyor (ilk kayıt ${dateTR(dates[0])}).</div></section>`;
  }
  const flows = Array.isArray(st8.cashflows) ? st8.cashflows : [];
  const twr = PR.realReturn(hist, flows)?.twr;
  const a = dates[0], b = dates[dates.length - 1];
  const { cal, bench } = d.pos.az;
  const at = (key, iso) => { const v = bench[key]?.values || []; for (let i = idxOn(cal, iso); i >= 0; i--) if (v[i] > 0) return v[i]; return null; };
  const br = (key) => { const x = at(key, a), y = at(key, b); return x && y ? (y / x - 1) * 100 : null; };
  const rows = PR.BENCHMARK_ORDER.filter(([k]) => bench[k]).map(([k, l]) => [l, br(k)]);
  return `<section class="card">
    <div class="card-head"><h2>Gerçek getirim</h2><span class="sub">${dateTR(a)} – ${dateTR(b)} · ${dates.length} kayıtlı gün · para giriş/çıkışı hariç</span></div>
    <div class="kpi-row">
      <div><span>Portföyüm (gerçek)</span><b class="${R.tone(twr)}">${R.pctS(twr, 2)}</b></div>
      ${rows.map(([l, v]) => `<div><span>${esc(l)}</span><b class="${R.tone(v)}">${R.pctS(v, 2)}</b></div>`).join("")}
    </div>
    <p class="chart-note dim">Kayıt ${dateTR(a)} tarihinde başladığı için bu kutu şimdilik kısa bir dönemi kapsar; her işlem günü uzar. Model portföylerle
      gerçek karşılaştırma aylık olarak Portföy Raporu'nda yapılır.</p>
  </section>`;
}

// ------------------------------------------------------------------ Portföy Karşılaştırması
const WINDOWS = [["3", "3 Ay"], ["6", "6 Ay"], ["12", "1 Yıl"]];
const st = { win: "12" };

async function renderCompare(app) {
  const d = await loadAll(app);
  if (!d) return;
  const cs = await compareSet(d.pos, d.snap);
  if (!cs) { app.innerHTML = `<div class="card empty"><h3>Model verisi yüklenemedi</h3></div>`; return; }
  app.innerHTML = `
  <section class="method-intro card">
    <h2>Modellerle Karşılaştır <span class="model-tag">PORTFÖY · MODELLER</span></h2>
    <p><b>İki ayrı ölçü var.</b> Gerçek getirin, Analiz'in günlük değer kaydı başladığı ${dateTR(realFirst(d.ps.state))} tarihinden itibaren hesaplanır (aşağıda ilk kutu).
      Daha uzun dönemler için bugünkü pozisyonların (${dateTR(d.snap.date)} fotoğrafı) seçilen dönemin başında alınıp tutulduğu varsayılır ve
      Güvenli, Dengeli, Atak fon modelleri ile BES Öneri'ye ve PPF, TÜFE, altın, dolar, S&P 500 kıyaslarına karşı aylık izlenir.
      Bu, dağılımının geçmişte nasıl davranacağını gösterir; gerçek alım-satım geçmişini değil.${missingNote(d.pos)}</p>
    <div class="btn-row"><a class="btn btn-primary" href="#/portfoyrapor">▤ Portföy raporu (PDF)</a></div>
  </section>
  ${realBlock(d)}
  <section class="card">
    <div class="card-head"><h2>Bugünkü dağılımım · geriye dönük birikimli getiri</h2>
      <div class="seg" id="pfWin">${WINDOWS.map(([k, l]) => `<button data-w="${k}" aria-pressed="${k === st.win}">${l}</button>`).join("")}</div></div>
    <div class="chart" id="pfChart"></div>
    <div class="table-wrap"><table class="model-table" id="pfStats"></table></div>
  </section>
  <section class="card">
    <div class="card-head"><h2>Aylık getiriler (%)</h2><span class="sub">Portföyüm, modeller ve kıyaslar · son 12 tamamlanmış ay</span></div>
    <div class="table-wrap"><table class="model-table" id="pfMonths"></table></div>
  </section>`;

  const draw = () => {
    const k = +st.win, all = [cs.portfolio, ...cs.models];
    const eF = R.lastFull(cs.ref), n = cs.ref.dates.length - 1, i0 = Math.max(0, eF - k);
    const dates = cs.ref.dates.slice(i0);
    const rebase = (v) => { const w = v.slice(i0), b = w.find((x) => x != null); return w.map((x) => (x == null || !b ? null : (x / b) * 100)); };
    const series = [
      { name: "Bugünkü dağılımım", d: dates, v: rebase(cs.portfolio.series.model), color: "var(--text)" },
      ...cs.models.map((m) => ({ name: m.label, d: dates, v: rebase(m.series.model), color: SCREEN_COLORS[m.key] || MODEL_COLORS[m.key] })),
      ...R.BENCH.filter(([b]) => cs.ref.series[b]).map(([b, l, c]) => ({ name: l, d: dates, v: rebase(cs.ref.series[b]), color: c, dashed: true })),
    ];
    lineChart(app.querySelector("#pfChart"), series, { base: 100, height: 320, format: (v) => num(v, 0) });
    const pRet = R.ret(cs.portfolio.series.model, i0, n);
    const rows = [
      ...all.map((m) => ({ name: m.kind === "portfoy" ? "Bugünkü dağılımım" : m.label, self: m.kind === "portfoy", s: m.series.model })),
      ...R.BENCH.filter(([b]) => cs.ref.series[b]).map(([b, l]) => ({ name: l, s: cs.ref.series[b], bench: true })),
    ];
    app.querySelector("#pfStats").innerHTML = `<thead><tr><th class="left">Portföy / model / kıyas</th><th>Dönem getirisi</th><th>Dağılımıma göre</th><th>Pozitif ay</th></tr></thead>
      <tbody>${rows.map((r) => {
        const t = R.ret(r.s, i0, n);
        const diff = r.self || t == null || pRet == null ? null : pRet - t;
        const mm = []; for (let i = i0 + 1; i <= eF; i++) { const x = R.ret(r.s, i - 1, i); if (x != null) mm.push(x); }
        return `<tr class="${r.self ? "is-self" : ""}"><td class="left">${r.self ? "<b>Bugünkü dağılımım</b>" : esc(r.name)}</td>
          <td class="${R.tone(t)}"><b>${R.pctS(t)}</b></td>
          <td class="${R.tone(diff)}">${r.self ? "—" : diff == null ? "—" : `${diff >= 0 ? "önde " : "geride "}${num(Math.abs(diff), 1)} puan`}</td>
          <td>${mm.filter((x) => x > 0).length} / ${mm.length}</td></tr>`;
      }).join("")}</tbody>`;
  };
  // Aylık tablo: son 12 tamamlanmış ay, yeniden eskiye
  const eF = R.lastFull(cs.ref);
  const keys = cs.ref.dates.slice(Math.max(0, eF - 12), eF + 1);
  const mr = (s) => keys.slice(1).map((_, j) => R.ret(s, cs.ref.dates.indexOf(keys[j]), cs.ref.dates.indexOf(keys[j + 1])));
  const cols = [["Bugünkü dağılımım", mr(cs.portfolio.series.model), true], ...cs.models.map((m) => [m.label, mr(m.series.model)]),
    ...R.BENCH.filter(([b]) => cs.ref.series[b]).map(([b, l]) => [l, mr(cs.ref.series[b])])];
  app.querySelector("#pfMonths").innerHTML = `<thead><tr><th class="left">Ay</th>${cols.map(([l]) => `<th>${esc(l)}</th>`).join("")}</tr></thead>
    <tbody>${keys.slice(0, -1).map((k, j) => ({ k, j })).reverse().map(({ k, j }) => `<tr><td class="left">${R.monthLong(k)}</td>
      ${cols.map(([, v, self]) => `<td class="${R.tone(v[j])}">${self ? `<b>${R.pctS(v[j])}</b>` : R.pctS(v[j])}</td>`).join("")}</tr>`).join("")}</tbody>`;

  app.querySelector("#pfWin").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    st.win = b.dataset.w;
    app.querySelectorAll("#pfWin button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    draw();
  });
  draw();
}

// ------------------------------------------------------------------ A4 Portföy Raporu
// Sayfa 1-2: Analiz'in aylık portföy raporu (gerçek kayıtlar: zaman ağırlıklı getiri, değer köprüsü,
// dağılım, katkılar, risk) + aynı ayda TEFAS Quant model portföyleri. Sayfa 3: bugünkü dağılımın son
// 12 ayı modeller ve kıyaslarla.
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

/** Modelin rapor ayındaki ve yılbaşından getirisi (Model Rapor'un ay başı noktalarından). */
function modelMonth(m, month) {
  const row = R.months(m).find((r) => r.start.slice(0, 7) === month);
  if (!row) return { month: null, ytd: null };
  const iEnd = m.dates.indexOf(row.end);
  const iY = m.dates.findIndex((d) => d.slice(0, 4) === month.slice(0, 4));
  return { month: row.r.model, ytd: iY >= 0 && iY < iEnd ? R.ret(m.series.model, iY, iEnd) : null, partial: row.partial };
}

function reportPages(rep, cs, store, pos, snap) {
  const m = rep.periods.month;
  const infl = rep.inflation || {};
  const shortNote = `Bu dönem için en az iki kayıtlı gün gerekiyor (ilk kayıt ${dateTR(rep.firstDate)}). Getiri ve kıyaslar sonraki işlem günlerinde dolacak.`;
  const models = (cs?.models || []).map((x) => ({ key: x.key, label: `${x.label} modeli`, ...modelMonth(x, rep.month) }));
  const real = rep.comparisonRows[0]?.realMonth;
  const change = m ? m.endValue - m.startValue : null;
  const generated = new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium" }).format(new Date());
  const period = `${m ? `${dateTR(m.startDate)} – ${dateTR(m.endDate)}` : rep.label} · ${rep.risk.positionCount || 0} varlık · ilk kayıt ${dateTR(rep.firstDate)}`;
  const total = cs ? 3 : 2;
  const foot = (n) => `<footer class="rp-footer"><span>Kaynak: Analiz (Midas adet ve fiyatları, günlük değer kaydı), TEFAS, Yahoo Finance ve TCMB. Getiriler zaman ağırlıklıdır; para yatırma/çekme getiri sayılmaz. Model getirileri TEFAS Quant model portföylerinin ay başından ay başına getirisidir. Yatırım tavsiyesi değildir.</span>
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
  if (rep.risk.largestWeight > 40) insights.push(`Tek varlığın (${rep.risk.largestCode}) portföydeki payı %${Math.round(rep.risk.largestWeight)}; yoğunlaşma yüksek.`);
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
  const dayFmt = (d) => `${d.slice(8, 10)}.${d.slice(5, 7)}`;
  const chartLines = rep.chart.series.map((s, i) => ({
    name: s.label, v: s.values, color: s.key === "PORTFOY" ? PORT_COLOR : ["#db2777", "#7c3aed", "#c58b12", "#0f8a50", "#64748b"][(i - 1) % 5],
    w: s.key === "PORTFOY" ? 2.6 : 1.3, dash: s.key === "PARAPIYASASI",
  }));

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
    ${pa.block("Dönem tablosu", "brand", `<table class="rp-table pa-table">
      <thead><tr><th style="width:30%">Portföy / model / endeks</th><th class="r">Bu ay</th><th class="r">Bu ay reel</th><th class="r">Yılbaşından</th><th class="r">Başlangıçtan</th><th class="r">Başl. reel</th></tr></thead>
      <tbody>
        ${tableRow("Portföyüm", "main", rep.comparisonRows[0]?.month, rep.comparisonRows[0]?.realMonth, rep.comparisonRows[0]?.ytd, rep.comparisonRows[0]?.inception, rep.comparisonRows[0]?.realInception)}
        ${models.map((x) => {
          const r = x.month != null && infl.month != null ? ((1 + x.month / 100) / (1 + infl.month / 100) - 1) * 100 : null;
          return tableRow(x.label, "model", x.month, r, x.ytd, null, null);
        }).join("")}
        ${cmpRows.slice(1).map((r) => tableRow(r.label, "", r.month, r.realMonth, r.ytd, r.inception, r.realInception)).join("")}
      </tbody></table>
      <p class="pa-note">Yılbaşı ve başlangıç sütunları ${dateTR(rep.firstDate)} tarihli ilk kayıttan itibaren hesaplanır; modellerde yılbaşından getiri, model portföyün kendi geçmişinden gelir. TÜFE son açıklanan aya kadardır.</p>`)}
    ${pa.block("Dönem içi seyir (başlangıç = 100)", "brand",
      m && rep.chart.dates.length > 1 ? R.chart(rep.chart.dates, chartLines, 160, 764, dayFmt) : pa.empty(shortNote))}
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
      </table>${risk.largestWeight > 40 ? `<div class="pa-alert">Portföyün %${Math.round(risk.largestWeight)} kadarı tek varlıkta (${esc(risk.largestCode)}); bu varlıktaki bir gelişme portföyün tamamını belirgin şekilde etkiler.</div>` : ""}`
      : pa.empty("Ay sonu pozisyon kaydı yok."))}
    ${pa.block("Notlar", "brand", `<ul class="pa-list">
      <li>Değerler Analiz hesabına kaydedilen günlük toplamlardan gelir (ilk kayıt ${dateTR(rep.firstDate)}); hafta sonları atlanır.</li>
      ${rep.frozenCodes.length ? `<li>${esc(rep.frozenCodes.join(", "))} temerrüttedir; fiyatı Midas'taki değerde sabittir, getiri ve K/Z hesaplanmaz.</li>` : ""}
      <li>Not sütunu TEFAS fonlarının TEFAS Quant derecesidir (A+ en iyi). Model satırları Güvenli, Dengeli, Atak fon modelleri ve BES Öneri'dir.</li>
      <li>Kıyaslar: BIST 100, S&P 500 (TL), gram altın, dolar (Yahoo Finance); PPF ortalaması TEFAS para piyasası fonlarından; TÜFE TCMB/TÜİK verisinden.</li>
      <li>Stopaj tahminidir: hisse yoğun fonlarda %0, diğer fonlarda %17,5; portföy değerini etkilemez.</li></ul>`)}
    ${foot(2)}
  </article>`;

  // ------------------------------------------------ sayfa 3: bugünkü dağılım, son 12 ay, modellerle
  let page3 = "";
  if (cs) {
    const pY = R.lastYear(cs.portfolio);
    const n = pY.dates.length - 1;
    const p12 = R.ret(pY.series.model, 0, n);
    const e = R.lastFull(cs.ref);
    const lastMonth = cs.ref.dates[e - 1];
    const per = (x, s) => { const k = R.lastFull(x); return [R.ret(s, k - 1, k), R.ret(s, k - 3, k), R.ret(s, k - 6, k), R.ret(s, k - 12, k)]; };
    const rows = [
      { name: "Portföyüm (bugünkü dağılım)", self: true, v: per(cs.portfolio, cs.portfolio.series.model) },
      ...cs.models.map((x) => ({ name: x.label, v: per(x, x.series.model) })),
      ...R.BENCH.filter(([b]) => cs.ref.series[b]).map(([b, l]) => ({ name: l, v: per(cs.ref, cs.ref.series[b]), bench: true })),
    ];
    const keys = cs.ref.dates.slice(Math.max(0, e - 12), e).map((x) => x.slice(0, 7));
    const byMonth = (x, k) => {
      const map = new Map(R.months(x).filter((r) => !r.partial).map((r) => [r.start.slice(0, 7), r.r[k]]));
      return keys.map((mk) => map.get(mk) ?? null);
    };
    const heat = [
      { name: "Portföyüm", v: byMonth(cs.portfolio, "model"), self: true },
      ...cs.models.map((x) => ({ name: x.label, v: byMonth(x, "model"), self: true })),
      ...R.BENCH.filter(([b]) => cs.ref.series[b]).map(([b, l]) => ({ name: l, v: byMonth(cs.ref, b) })),
    ];
    const ys = cs.models.map((x) => R.lastYear(x));
    const best = cs.models.map((x, i) => ({ x, r: R.ret(ys[i].series.model, 0, ys[i].dates.length - 1) })).sort((a, b) => b.r - a.r)[0];
    const ppf12 = R.ret(pY.series.ppf, 0, n), tufe12 = R.ret(pY.series.tufe, 0, n);
    const full = R.months(pY).filter((r) => !r.partial);
    page3 = `<article class="rp-page">
      ${R.cover("MODEL KARŞILAŞTIRMASI", "Bugünkü Dağılım · Modeller · Kıyaslar",
        `Bugünkü pozisyonların (${dateTR(snap.date)}) son 12 ayı (${R.monthLong(pY.dates[0])} – ${R.monthLong(lastMonth)}) · Güvenli, Dengeli, Atak, BES Öneri ve PPF, TÜFE, altın, dolar, S&P 500 ile`, "KİŞİSEL PORTFÖY RAPORU")}
      <div class="rp-kpis">
        <div class="${R.tone(p12)}"><span>Bugünkü dağılım · 12 ay</span><b>${R.pctS(p12)}</b><em>Pozitif ay ${full.filter((r) => r.r.model > 0).length} / ${full.length}</em></div>
        <div class="${R.tone(p12 - best.r)}"><span>En iyi model: ${esc(best.x.label)}</span><b>${R.pctS(best.r)}</b><em>Portföye göre ${R.ptsS(p12 - best.r)}</em></div>
        <div class="${R.tone(p12 - ppf12)}"><span>PPF'ye göre</span><b>${R.ptsS(p12 - ppf12)}</b><em>PPF ${R.pctS(ppf12)}</em></div>
        <div class="${R.tone(p12 - tufe12)}"><span>TÜFE'ye göre (reel)</span><b>${R.ptsS(p12 - tufe12)}</b><em>TÜFE ${R.pctS(tufe12)}</em></div>
      </div>
      ${pa.block(`Birikimli getiri · son 12 ay (${monthLabel(pY.dates[0])} = 100)`, "brand", R.chart(pY.dates, [
        { name: "Portföyüm", v: pY.series.model, color: PORT_COLOR, w: 2.8 },
        ...cs.models.map((x, i) => ({ name: x.label, v: ys[i].series.model, color: MODEL_COLORS[x.key], w: 1.6 })),
        ...R.BENCH.filter(([b]) => pY.series[b]).map(([b, l, c]) => ({ name: l.replace(" ortalaması", ""), v: pY.series[b], color: c, dash: true })),
      ], 210))}
      ${pa.block("Dönemsel getiriler (tamamlanmış aylar)", "brand", `<table class="rp-table mr-sum">
        <thead><tr><th>Portföy / model / kıyas</th><th class="r">${R.MONTHS_LONG[+lastMonth.slice(5, 7) - 1]}</th><th class="r">3 ay</th><th class="r">6 ay</th><th class="r">12 ay</th><th class="r">12 ayda portföye göre</th></tr></thead>
        <tbody>${rows.map((r) => {
          const diff = r.self || r.v[3] == null || p12 == null ? null : p12 - r.v[3];
          return `<tr class="${r.bench ? "mr-bench" : "mr-self"}"><td><b>${esc(r.name)}</b></td>${r.v.map((x) => `<td class="r num ${R.tone(x)}">${R.pctS(x)}</td>`).join("")}
            <td class="r num ${R.tone(diff)}">${r.self ? "—" : diff == null ? "—" : `${diff >= 0 ? "✓ önde " : "✗ geride "}${num(Math.abs(diff), 1)} puan`}</td></tr>`;
        }).join("")}</tbody></table>`)}
      ${pa.block("Son 12 ay · aylık getiri ısı haritası (%)", "brand", `<table class="rp-table mr-heatmap">
        <thead><tr><th>Portföy / model / kıyas</th>${keys.map((mk) => `<th class="r">${monthLabel(mk + "-01")}</th>`).join("")}</tr></thead>
        <tbody>${heat.map((h) => `<tr class="${h.self ? "mr-self" : "mr-bench"}"><td><b>${esc(h.name)}</b></td>${h.v.map(R.heatCell).join("")}</tr>`).join("")}</tbody></table>`)}
      <footer class="rp-footer"><span>Bu sayfa bugünkü pozisyonların 12 ay önce alınıp tutulduğunu varsayar (geriye dönük); gerçek alım-satım geçmişi değildir, gerçek getiri 1. sayfadadır. Fiyatlar Analiz'in TEFAS, borsa ve kripto verilerinden; dolar varlıklar dolar/TL ile çevrilir.${missingNote(pos)} Yatırım tavsiyesi değildir.</span>
        <span>Oluşturma ${generated} · Sayfa 3 / ${total}</span></footer>
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
  const [cs] = await Promise.all([compareSet(pos, snap)]);
  const rep = PR.buildMonthlyReport({ month, history, flows, dividends, snapshots, az: pos.az });

  app.innerHTML = `
  <div class="rp-toolbar no-print">
    <div><h2>Kişisel portföy raporu</h2>
      <p class="dim">Analiz'in aylık portföy raporu + TEFAS Quant model portföyleri · PDF için yazdırma penceresinde "PDF olarak kaydet"</p></div>
    <div class="rp-actions"><a class="btn" href="#/portfoykarsilastir">← Modellerle Karşılaştır</a>
      <select id="prMonth" aria-label="Rapor ayı">${months.map((mo) => `<option value="${mo}" ${mo === month ? "selected" : ""}>${PR.monthLabel(mo)}</option>`).join("")}</select>
      <button class="btn btn-primary" id="prPrint" type="button">⤓ PDF olarak indir</button></div>
  </div>
  <div class="rp-doc">${reportPages(rep, cs, store, pos, snap)}</div>`;
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
