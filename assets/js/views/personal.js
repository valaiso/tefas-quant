// Kişisel portföy: Analiz'deki gerçek portföy (Portföy Özeti, Portföy Karşılaştırması, A4 Portföy Raporu).
//
// Portföy herkese açık siteye hiç yazılmaz. Sayfa açıldığında tarayıcıda okunur:
//   1. Analiz hesabı: aynı kökende (valaiso.github.io) Analiz'in Supabase oturumu paylaşılır,
//      portfolio_state satırı kullanıcının kendi yetkisiyle (RLS) çekilir.
//   2. Bu tarayıcıdaki Analiz kaydı (localStorage "tefas-portfoy-v1").
//   3. Aylık e-postada CI, portföyü sayfaya window.__TQ_PORTFOLIO__ olarak verir.
// Pozisyonlar Analiz Panel'in kaydettiği son aylık fotoğraftan (monthlySnapshots), fiyat geçmişleri
// Analiz'in yayımladığı dosyalardan gelir. Karşılaştırma bugünkü pozisyonları geriye doğru tutar.
import { esc, num, dateTR, monthLabel, codeChip } from "../util.js";
import { lineChart } from "../chart.js";
import * as R from "./modelreport.js";

const ANALIZ = new URL("/Analiz/", "https://valaiso.github.io").href;
const SUPABASE_URL = "https://jqmfvinbzgqyitqquzdc.supabase.co";
const SUPABASE_KEY = "sb_publishable_uw979hCwS6xyLRTexQX55A_ZqgWidDs";  // tarayıcı anahtarı; veriyi RLS korur
const LOCAL_KEY = "tefas-portfoy-v1";
const GROUP_COLORS = { Fon: "#1f5fbf", Hisse: "#db2777", ETF: "#7c3aed", Kripto: "#c58b12", Nakit: "#64748b", Diğer: "#0891b2" };
const MODEL_COLORS = { guvenli: "#0b7a45", dengeli: "#1f5fbf", atak: "#db2777", bes: "#0891b2" };
const PORT_COLOR = "#0b2a5b";
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
  return { rep, ref, portfolio, models: rep.models.map((m) => (m === ref ? m : align(m))) };
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

// ------------------------------------------------------------------ Portföy Özeti
async function renderSummary(app, store) {
  const d = await loadAll(app);
  if (!d) return;
  const { ps, snap, pos } = d;
  const groups = groupBy(pos.rows);
  const pl = pos.rows.reduce((s, r) => s + (r.pl || 0), 0);
  const hist = Object.entries(ps.state.valueHistory || {}).filter(([, v]) => v > 0).sort(([a], [b]) => a.localeCompare(b));
  const src = { hesap: "Analiz hesabı", "tarayıcı": "bu tarayıcıdaki Analiz kaydı", rapor: "rapor verisi" }[ps.source];

  app.innerHTML = `
  <section class="method-intro card">
    <h2>Portföy Özeti <span class="model-tag">ANALİZ</span></h2>
    <p>Gerçek portföyün, ${esc(src)} üzerinden ${dateTR(snap.date)} tarihli pozisyon fotoğrafından okundu
      (Analiz Panel'i her açışında güncellenir). Bu bilgi yalnızca senin tarayıcında görünür.</p>
    <div class="btn-row"><a class="btn btn-primary" href="#/portfoyrapor">▤ Portföy raporu (PDF)</a>
      <a class="btn" href="#/portfoykarsilastir">⇆ Modellerle karşılaştır</a>
      <a class="btn" href="${ANALIZ}#panel" target="_blank" rel="noopener">Analiz Panel ↗</a></div>
  </section>

  <section class="card">
    <div class="kpi-row">
      <div><span>Toplam değer</span><b>${tl(pos.total)}</b></div>
      <div><span>Pozisyon</span><b>${pos.rows.filter((r) => !r.cash).length}</b></div>
      <div><span>Nakit</span><b>${tl(snap.cash || 0)}</b></div>
      <div><span>Toplam kâr / zarar</span><b class="${R.tone(pl)}">${tlS(pl)}</b></div>
      <div><span>En büyük pozisyon</span><b>${esc(pos.rows[0]?.code || "—")} · %${num(pos.rows[0]?.w, 1)}</b></div>
    </div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Varlık sınıfları</h2><span class="sub">Toplam değere göre pay</span></div>
    ${classBar(groups)}
  </section>

  <section class="card">
    <div class="card-head"><h2>Pozisyonlar</h2><span class="sub">TEFAS fonlarında Quant notu ve fon sayfası bağlantısı</span></div>
    <div class="table-wrap"><table class="model-table">
      <thead><tr><th class="left">Varlık</th><th class="left">Sınıf</th><th>Değer</th><th>Ağırlık</th><th>Toplam K/Z</th><th>K/Z %</th><th>Quant notu</th></tr></thead>
      <tbody>${pos.rows.map((r) => {
        const g = fundGrade(store, r.code);
        return `<tr><td class="left">${store.byCode.has(r.code) ? codeChip(r.code) : `<span class="code-chip muted-chip">${esc(r.code)}</span>`}
            <span class="fund-name">${esc(r.name)}</span></td>
          <td class="left dim">${esc(r.group)}${r.label && r.label !== r.group ? ` · ${esc(r.label)}` : ""}</td>
          <td><b>${tl(r.value)}</b></td><td>%${num(r.w, 1)}</td>
          <td class="${R.tone(r.pl)}">${r.pl == null ? "—" : tlS(r.pl)}</td><td class="${R.tone(r.plPct)}">${r.plPct == null ? "—" : R.pctS(r.plPct)}</td>
          <td>${g ? `<span class="grade ${g === "A+" ? "sig-aplus" : `sig-${g.toLowerCase()}`}">${esc(g)}</span>` : `<span class="dim">—</span>`}</td></tr>`;
      }).join("")}</tbody></table></div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Kayıtlı gerçek değer</h2><span class="sub">Analiz Panel'in günlük kaydettiği toplam değer</span></div>
    ${hist.length >= 2 ? `<div class="chart" id="pfHist"></div>` : `<div class="empty">Henüz ${hist.length} günlük kayıt var; grafik kayıt biriktikçe görünür.</div>`}
    <p class="chart-note dim">Gerçek değer kaydı para girişi ve çıkışlarını da içerir; getiri karşılaştırması için Modellerle Karşılaştır sayfasına bakın.</p>
  </section>`;
  if (hist.length >= 2) {
    lineChart(app.querySelector("#pfHist"), [{ name: "Portföy değeri", d: hist.map(([k]) => k), v: hist.map(([, v]) => v), color: "var(--brand-3)" }],
      { height: 240, format: (v) => `${num(v / 1000, 0)} bin ₺` });
  }
}

function groupBy(rows) {
  const m = new Map();
  for (const r of rows) {
    const g = m.get(r.group) || { name: r.group, value: 0, w: 0, n: 0 };
    g.value += r.value; g.w += r.w; g.n += 1;
    m.set(r.group, g);
  }
  return [...m.values()].sort((a, b) => b.value - a.value);
}

function classBar(groups) {
  return `<div class="pf-bar">${groups.map((g) => `<i style="width:${g.w.toFixed(2)}%;background:${GROUP_COLORS[g.name] || "#94a3b8"}" title="${esc(g.name)} %${num(g.w, 1)}"></i>`).join("")}</div>
    <div class="pf-legend">${groups.map((g) => `<span><i style="background:${GROUP_COLORS[g.name] || "#94a3b8"}"></i>${esc(g.name)} <b>%${num(g.w, 1)}</b> <em>${tl(g.value)}</em></span>`).join("")}</div>`;
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
    <p>Bugünkü pozisyonların (${dateTR(d.snap.date)} fotoğrafı) seçilen dönemin başında alınıp tutulduğu varsayılır ve
      Güvenli, Dengeli, Atak fon modelleri ile BES Öneri'ye ve PPF, TÜFE, altın, dolar, S&P 500 kıyaslarına karşı aylık izlenir.
      Bu, dağılımının geçmişte nasıl davranacağını gösterir; gerçek alım-satım geçmişini değil.${missingNote(d.pos)}</p>
    <div class="btn-row"><a class="btn btn-primary" href="#/portfoyrapor">▤ Portföy raporu (PDF)</a></div>
  </section>
  <section class="card">
    <div class="card-head"><h2>Birikimli getiri</h2>
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
      { name: "Portföyüm", d: dates, v: rebase(cs.portfolio.series.model), color: PORT_COLOR },
      ...cs.models.map((m) => ({ name: m.label, d: dates, v: rebase(m.series.model), color: MODEL_COLORS[m.key] })),
      ...R.BENCH.filter(([b]) => cs.ref.series[b]).map(([b, l, c]) => ({ name: l, d: dates, v: rebase(cs.ref.series[b]), color: c, dashed: true })),
    ];
    lineChart(app.querySelector("#pfChart"), series, { base: 100, height: 320, format: (v) => num(v, 0) });
    const pRet = R.ret(cs.portfolio.series.model, i0, n);
    const rows = [
      ...all.map((m) => ({ name: m.label, self: m.kind === "portfoy", s: m.series.model })),
      ...R.BENCH.filter(([b]) => cs.ref.series[b]).map(([b, l]) => ({ name: l, s: cs.ref.series[b], bench: true })),
    ];
    app.querySelector("#pfStats").innerHTML = `<thead><tr><th class="left">Portföy / model / kıyas</th><th>Dönem getirisi</th><th>Portföyüme göre</th><th>Pozitif ay</th></tr></thead>
      <tbody>${rows.map((r) => {
        const t = R.ret(r.s, i0, n);
        const diff = r.self || t == null || pRet == null ? null : pRet - t;
        const mm = []; for (let i = i0 + 1; i <= eF; i++) { const x = R.ret(r.s, i - 1, i); if (x != null) mm.push(x); }
        return `<tr class="${r.self ? "is-self" : ""}"><td class="left">${r.self ? "<b>Portföyüm</b>" : esc(r.name)}</td>
          <td class="${R.tone(t)}"><b>${R.pctS(t)}</b></td>
          <td class="${R.tone(diff)}">${r.self ? "—" : diff == null ? "—" : `${diff >= 0 ? "önde " : "geride "}${num(Math.abs(diff), 1)} puan`}</td>
          <td>${mm.filter((x) => x > 0).length} / ${mm.length}</td></tr>`;
      }).join("")}</tbody>`;
  };
  // Aylık tablo: son 12 tamamlanmış ay, yeniden eskiye
  const eF = R.lastFull(cs.ref);
  const keys = cs.ref.dates.slice(Math.max(0, eF - 12), eF + 1);
  const mr = (s) => keys.slice(1).map((_, j) => R.ret(s, cs.ref.dates.indexOf(keys[j]), cs.ref.dates.indexOf(keys[j + 1])));
  const cols = [["Portföyüm", mr(cs.portfolio.series.model), true], ...cs.models.map((m) => [m.label, mr(m.series.model)]),
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
async function renderReport(app, store) {
  const d = await loadAll(app);
  if (!d) return;
  const { snap, pos } = d;
  const cs = await compareSet(pos, snap);
  const groups = groupBy(pos.rows);
  const asOf = cs?.rep.asOf || snap.date;
  const total = 2;
  const pl = pos.rows.reduce((s, r) => s + (r.pl || 0), 0);

  // Karşılaştırma: son 12 tamamlanmış ay
  const pY = cs && R.lastYear(cs.portfolio);
  const n = pY ? pY.dates.length - 1 : 0;
  const p12 = pY && R.ret(pY.series.model, 0, n);
  const e = cs ? R.lastFull(cs.ref) : 0;
  const lastMonth = cs ? cs.ref.dates[e - 1] : snap.date;
  const p1 = cs && R.ret(cs.portfolio.series.model, e - 1, e);
  const maxW = Math.max(...groups.map((g) => g.w), 1);
  const rowsShown = pos.rows.slice(0, 26), rest = pos.rows.slice(26);

  const page1 = `<article class="rp-page">
    ${R.cover("KİŞİSEL RAPOR", "Kişisel Portföy Raporu",
      `${dateTR(snap.date)} pozisyon fotoğrafı · ${pos.rows.filter((r) => !r.cash).length} pozisyon · kaynak: Analiz`, "KİŞİSEL PORTFÖY RAPORU")}
    <div class="rp-kpis">
      <div><span>Toplam değer</span><b>${tl(pos.total)}</b><em>Nakit ${tl(snap.cash || 0)}</em></div>
      <div class="${R.tone(pl)}"><span>Toplam kâr / zarar</span><b>${tlS(pl)}</b><em>Pozisyonların maliyetine göre</em></div>
      <div class="${R.tone(p1)}"><span>${cs ? R.MONTHS_LONG[+lastMonth.slice(5, 7) - 1] : "Son ay"} · bugünkü dağılım</span><b>${R.pctS(p1)}</b><em>Son 12 ayda ${R.pctS(p12)}</em></div>
      <div><span>En büyük pozisyon</span><b class="sm">${esc(pos.rows[0]?.code || "—")} · %${num(pos.rows[0]?.w, 1)}</b><em>${esc(pos.rows[0]?.group || "")}</em></div>
    </div>
    <section class="rp-block">
      <h3><span class="rp-dot brand"></span>Varlık sınıflarına göre dağılım</h3>
      <div class="pr-classes">${groups.map((g) => `<div class="pr-class"><span class="pr-class-name"><i style="background:${GROUP_COLORS[g.name] || "#94a3b8"}"></i>${esc(g.name)}</span>
        <span class="rp-bar"><i style="width:${((g.w / maxW) * 100).toFixed(1)}%;background:${GROUP_COLORS[g.name] || "#94a3b8"}"></i></span>
        <span class="num"><b>%${num(g.w, 1)}</b></span><span class="num dim">${tl(g.value)}</span></div>`).join("")}</div>
    </section>
    <section class="rp-block">
      <h3><span class="rp-dot brand"></span>Pozisyonlar</h3>
      <table class="rp-table pr-pos">
        <thead><tr><th>#</th><th>Varlık</th><th>Sınıf</th><th class="r">Değer</th><th class="r">Ağırlık</th><th class="r">Toplam K/Z</th><th class="r">K/Z %</th><th class="r">Not</th></tr></thead>
        <tbody>${rowsShown.map((r, i) => {
          const g = fundGrade(store, r.code);
          return `<tr><td class="rk">${i + 1}</td><td><b class="mono">${esc(r.code)}</b> <span class="nm">${esc(r.name)}</span></td>
            <td class="ct-cell">${esc(r.label && r.label !== r.group ? r.label : r.group)}</td>
            <td class="r num"><b>${tl(r.value)}</b></td><td class="r num">%${num(r.w, 1)}</td>
            <td class="r num ${R.tone(r.pl)}">${r.pl == null ? "—" : tlS(r.pl)}</td><td class="r num ${R.tone(r.plPct)}">${r.plPct == null ? "—" : R.pctS(r.plPct)}</td>
            <td class="r">${g ? `<span class="rp-grade g-${g === "A+" ? "ap" : g.toLowerCase()}">${esc(g)}</span>` : ""}</td></tr>`;
        }).join("")}${rest.length ? `<tr><td></td><td colspan="2" class="dim">Diğer ${rest.length} pozisyon</td>
          <td class="r num">${tl(rest.reduce((s, r) => s + r.value, 0))}</td><td class="r num">%${num(rest.reduce((s, r) => s + r.w, 0), 1)}</td><td colspan="3"></td></tr>` : ""}</tbody>
      </table>
    </section>
    ${R.footer("Pozisyonlar Analiz Panel'in kaydettiği aylık fotoğraftan alınır; Not sütunu TEFAS fonlarının TEFAS Quant derecesidir.", asOf, 1, total)}
  </article>`;

  let page2 = "";
  if (cs) {
    const eM = (m) => R.lastFull(m);
    const per = (m, s) => { const x = eM(m); return [R.ret(s, x - 1, x), R.ret(s, x - 3, x), R.ret(s, x - 6, x), R.ret(s, x - 12, x)]; };
    const rows = [
      { name: "Portföyüm", self: true, v: per(cs.portfolio, cs.portfolio.series.model) },
      ...cs.models.map((m) => ({ name: m.label, v: per(m, m.series.model), model: true })),
      ...R.BENCH.filter(([b]) => cs.ref.series[b]).map(([b, l]) => ({ name: l, v: per(cs.ref, cs.ref.series[b]), bench: true })),
    ];
    const keys = cs.ref.dates.slice(Math.max(0, e - 12), e).map((x) => x.slice(0, 7));
    const byMonth = (m, k) => {
      const map = new Map(R.months(m).filter((r) => !r.partial).map((r) => [r.start.slice(0, 7), r.r[k]]));
      return keys.map((mk) => map.get(mk) ?? null);
    };
    const heat = [
      { name: "Portföyüm", v: byMonth(cs.portfolio, "model"), self: true },
      ...cs.models.map((m) => ({ name: m.label, v: byMonth(m, "model"), self: true })),
      ...R.BENCH.filter(([b]) => cs.ref.series[b]).map(([b, l]) => ({ name: l, v: byMonth(cs.ref, b) })),
    ];
    const ys = cs.models.map((m) => R.lastYear(m));
    const best = cs.models.map((m, i) => ({ m, r: R.ret(ys[i].series.model, 0, ys[i].dates.length - 1) })).sort((a, b) => b.r - a.r)[0];
    const ppf12 = R.ret(pY.series.ppf, 0, n), tufe12 = R.ret(pY.series.tufe, 0, n);
    const pos12 = R.months(pY).filter((r) => !r.partial && r.r.model > 0).length;
    page2 = `<article class="rp-page">
      ${R.cover("KİŞİSEL RAPOR", "Portföy · Modeller · Kıyaslar",
        `Bugünkü dağılımın son 12 ayı (${R.monthLong(pY.dates[0])} – ${R.monthLong(lastMonth)}) · Güvenli, Dengeli, Atak, BES Öneri ve PPF, TÜFE, altın, dolar, S&P 500 ile`, "KİŞİSEL PORTFÖY RAPORU")}
      <div class="rp-kpis">
        <div class="${R.tone(p12)}"><span>Portföy · son 12 ay</span><b>${R.pctS(p12)}</b><em>Pozitif ay ${pos12} / ${R.months(pY).filter((r) => !r.partial).length}</em></div>
        <div class="${R.tone(p12 - best.r)}"><span>En iyi model: ${esc(best.m.label)}</span><b>${R.pctS(best.r)}</b><em>Portföye göre ${R.ptsS(p12 - best.r)}</em></div>
        <div class="${R.tone(p12 - ppf12)}"><span>PPF'ye göre</span><b>${R.ptsS(p12 - ppf12)}</b><em>PPF ${R.pctS(ppf12)}</em></div>
        <div class="${R.tone(p12 - tufe12)}"><span>TÜFE'ye göre (reel)</span><b>${R.ptsS(p12 - tufe12)}</b><em>TÜFE ${R.pctS(tufe12)}</em></div>
      </div>
      <section class="rp-block">
        <h3><span class="rp-dot brand"></span>Birikimli getiri · son 12 ay (${monthLabel(pY.dates[0])} = 100)</h3>
        ${R.chart(pY.dates, [
          { name: "Portföyüm", v: pY.series.model, color: PORT_COLOR, w: 2.8 },
          ...cs.models.map((m, i) => ({ name: m.label, v: ys[i].series.model, color: MODEL_COLORS[m.key], w: 1.6 })),
          ...R.BENCH.filter(([b]) => pY.series[b]).map(([b, l, c]) => ({ name: l.replace(" ortalaması", ""), v: pY.series[b], color: c, dash: true })),
        ], 210)}
      </section>
      <section class="rp-block">
        <h3><span class="rp-dot brand"></span>Dönemsel getiriler (tamamlanmış aylar)</h3>
        <table class="rp-table mr-sum">
          <thead><tr><th>Portföy / model / kıyas</th><th class="r">${R.MONTHS_LONG[+lastMonth.slice(5, 7) - 1]}</th><th class="r">3 ay</th><th class="r">6 ay</th><th class="r">12 ay</th><th class="r">12 ayda portföye göre</th></tr></thead>
          <tbody>${rows.map((r) => {
            const diff = r.self || r.v[3] == null || p12 == null ? null : p12 - r.v[3];
            return `<tr class="${r.bench ? "mr-bench" : "mr-self"}"><td><b>${esc(r.name)}</b></td>${r.v.map((x) => `<td class="r num ${R.tone(x)}">${R.pctS(x)}</td>`).join("")}
              <td class="r num ${R.tone(diff)}">${r.self ? "—" : diff == null ? "—" : `${diff >= 0 ? "✓ önde " : "✗ geride "}${num(Math.abs(diff), 1)} puan`}</td></tr>`;
          }).join("")}</tbody>
        </table>
      </section>
      <section class="rp-block">
        <h3><span class="rp-dot brand"></span>Son 12 ay · aylık getiri ısı haritası (%)</h3>
        <table class="rp-table mr-heatmap">
          <thead><tr><th>Portföy / model / kıyas</th>${keys.map((mk) => `<th class="r">${monthLabel(mk + "-01")}</th>`).join("")}</tr></thead>
          <tbody>${heat.map((h) => `<tr class="${h.self ? "mr-self" : "mr-bench"}"><td><b>${esc(h.name)}</b></td>${h.v.map(R.heatCell).join("")}</tr>`).join("")}</tbody>
        </table>
      </section>
      ${R.footer(`Karşılaştırma bugünkü pozisyonların dönem başında alınıp tutulduğunu varsayar (geriye dönük); gerçek alım-satım geçmişi değildir. Fiyatlar Analiz'in TEFAS, borsa ve kripto verilerinden, dolar varlıklar dolar/TL ile çevrilir.${missingNote(pos)}`, asOf, 2, total)}
    </article>`;
  }

  app.innerHTML = `
  <div class="rp-toolbar no-print">
    <div><h2>Kişisel portföy raporu</h2>
      <p class="dim">${dateTR(snap.date)} pozisyon fotoğrafı · modeller ve kıyaslarla son 12 ay</p></div>
    <div class="rp-actions"><a class="btn" href="#/portfoy">← Portföy Özeti</a><button class="btn btn-primary" id="prPrint" type="button">⤓ PDF olarak indir</button></div>
  </div>
  <div class="rp-doc">${page1}${page2}</div>`;
  app.querySelector("#prPrint").addEventListener("click", () => {
    const prev = document.title;
    document.title = `TEFAS-Quant-Portfoy-Raporu-${snap.date}`;  // PDF dosya adı
    window.print();
    setTimeout(() => (document.title = prev), 500);
  });
}

export async function render(app, route, store) {
  window.__TQ_READY__ = false;
  try {
    if (route.view === "portfoykarsilastir") await renderCompare(app, store);
    else if (route.view === "portfoyrapor") await renderReport(app, store);
    else await renderSummary(app, store);
  } finally {
    window.__TQ_READY__ = true;  // CI PDF basımı bu bayrağı bekler
  }
}
