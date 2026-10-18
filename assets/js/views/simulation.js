import { esc, num, pct, dateTR, codeChip } from "../util.js";
import { lineChart } from "../chart.js";

const COLORS = {
  aplus_public: "var(--brand-3)", aplus: "var(--brand-3)",
  universe_public: "var(--text-dim)", universe: "var(--text-dim)",
  ppf: "var(--c6)", gold: "var(--c7, #ca8a04)", tufe: "var(--c2)", usd: "var(--c4)",
};
const state = { qualified: false, cat: null, month: null, period: "all" };
const PERIODS = [["1a", "1A", 1], ["3a", "3A", 3], ["6a", "6A", 6], ["1y", "1Y", 12], ["2y", "2Y", 24], ["3y", "3Y", 36], ["all", "Tümü", null]];

/** Seçilen dönemin başlangıç noktası (aylık noktalar; son nokta bugün). */
function startIndex(dates, months) {
  if (!months) return 0;
  const end = new Date(dates[dates.length - 1]);
  const from = new Date(end); from.setMonth(from.getMonth() - months);
  const iso = from.toISOString().slice(0, 10);
  let i = dates.findIndex((d) => d >= iso);
  if (i < 0 || i >= dates.length - 1) i = dates.length - 2;  // en az bir aralık
  return Math.max(0, i);
}

/** Seriyi i0'dan itibaren 100'e oranlar. */
function windowed(v, i0) {
  const base = v[i0];
  return v.slice(i0).map((x) => (x == null || !base ? null : (x / base) * 100));
}

/** Pencere için istatistikler (aylık noktalardan). */
function windowStats(dates, lvl, ppf) {
  const pts = lvl.map((v, i) => [dates[i], v]).filter(([, v]) => v != null);
  if (pts.length < 2) return null;
  const first = pts[0][1], last = pts[pts.length - 1][1];
  const total = (last / first - 1) * 100;
  const years = (Date.parse(pts[pts.length - 1][0]) - Date.parse(pts[0][0])) / (365.25 * 86400000);
  let peak = -Infinity, mdd = 0;
  for (const [, v] of pts) { peak = Math.max(peak, v); mdd = Math.min(mdd, (v / peak - 1) * 100); }
  const rets = pts.slice(1).map(([, v], i) => v / pts[i][1] - 1);
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
  const vol = rets.length > 2 ? Math.sqrt(rets.reduce((a, r) => a + (r - mean) ** 2, 0) / (rets.length - 1)) * Math.sqrt(12) * 100 : null;
  let beat = null;
  if (ppf) {
    const pr = ppf.slice(1).map((v, i) => (v != null && ppf[i] != null ? v / ppf[i] - 1 : null));
    const pairs = rets.map((r, i) => [r, pr[i]]).filter(([, b]) => b != null);
    beat = pairs.length ? (pairs.filter(([a, b]) => a > b).length / pairs.length) * 100 : null;
  }
  return {
    total, cagr: years > 0.95 ? ((last / first) ** (1 / years) - 1) * 100 : null, mdd, vol,
    best: Math.max(...rets) * 100, worst: Math.min(...rets) * 100,
    positive: (rets.filter((r) => r > 0).length / rets.length) * 100, beatPpf: beat,
  };
}
let cache = null;

async function load() {
  if (!cache) {
    const r = await fetch(`data/simulation.json?v=${Date.now().toString(36).slice(0, -3)}`);
    if (!r.ok) throw new Error(`simulation.json: ${r.status}`);
    cache = await r.json();
  }
  return cache;
}

const statRow = (label, st, cls = "") => !st ? "" : `<tr class="${cls}">
  <td class="left">${label}</td>
  <td class="${st.total >= 0 ? "up" : "down"}"><b>${pct(st.total, 1)}</b></td>
  <td>${pct(st.cagr, 1)}</td>
  <td class="down">${st.mdd ? pct(st.mdd, 1) : "—"}</td>
  <td>${st.vol != null ? "%" + num(st.vol, 1) : "—"}</td>
  <td>${pct(st.worst, 1)} / ${pct(st.best, 1)}</td>
  <td>%${num(st.positive, 0)}</td>
  <td>${st.beatPpf != null ? "%" + num(st.beatPpf, 0) : "—"}</td>
</tr>`;

export async function render(app, _route, store) {
  app.innerHTML = `<div class="loading"><div class="spinner"></div><p>Simülasyon yükleniyor…</p></div>`;
  const sim = await load();
  if (!sim.available) {
    app.innerHTML = `<div class="card empty"><h3>Simülasyon için yeterli A+ geçmişi yok</h3></div>`;
    return;
  }
  const cats = Object.keys(sim.byCategory);
  if (!state.cat || !cats.includes(state.cat)) state.cat = cats[0];
  const months = sim.holdings.map((h) => h.date);
  if (!state.month || !months.includes(state.month)) state.month = months[months.length - 1];

  app.innerHTML = `
  <section class="method-intro card">
    <h2>Portföy Simülasyonu <span class="model-tag">Aylık A+ sepeti</span></h2>
    <p>${dateTR(sim.dates[0])} – ${dateTR(sim.dates[sim.dates.length - 1])}: her ay sonunda, o gün bilinen veriyle <b>A+ (GÜÇLÜ AL)</b> notu alan
      fonlardan eşit ağırlıklı bir sepet kuruldu, ertesi işlem günü fiyatından (T+1) alındı ve bir ay tutulup yenilendi. Başlangıç = 100.
      Komisyon yok (TEFAS), stopaj hesaba katılmadı. Sıkı A+ kuralı 1 yıllık geçmiş istediği için simülasyon Kasım 2024'te başlıyor.</p>
  </section>

  <div class="toolbar"><label class="switch"><input type="checkbox" id="simQ" ${state.qualified ? "checked" : ""}>
    <span class="switch-ui" aria-hidden="true"></span><span>Nitelikli yatırımcı fonlarını dahil et</span></label></div>

  <section class="card">
    <div class="card-head"><h2>A+ sepeti, altın, TÜFE, PPF ve dolar</h2>
      <div class="seg" id="simPeriod">${PERIODS.map(([k, l, m]) => {
        const avail = !m || m <= Math.round((Date.parse(sim.dates[sim.dates.length - 1]) - Date.parse(sim.dates[0])) / (30.44 * 86400000)) + 1;
        return `<button data-p="${k}" aria-pressed="${k === state.period}" ${avail ? "" : `disabled title="Simülasyon ${dateTR(sim.dates[0])} tarihinde başlıyor; bu dönem için yeterli geçmiş yok"`}>${l}</button>`;
      }).join("")}</div>
    </div>
    <div class="chart" id="simChart"></div>
    <p class="chart-note dim" id="simRange"></p>
  </section>

  <section class="card">
    <div class="card-head"><h2>Karşılaştırma</h2><span class="sub" id="simStatsSub">Aylık getirilerden</span></div>
    <div class="table-wrap"><table id="simStats"></table></div>
    <div class="notice">
      <b>Nasıl okunmalı?</b> Notlar fonları <b>kendi kategorisi içinde</b> sıralar; sepet ise hisse, altın, para piyasası gibi her kategoriden
      A+ fonları karıştırır. Bu yüzden altın ya da PPF ile karşılaştırma, aynı zamanda "o dönem hangi varlık sınıfı kazandı" sorusunu da ölçer.
      Notların başarısını en doğru gösteren kıyas <b>"Tüm fonlar"</b> sepeti (aynı karışım, not seçimi yok) ve aşağıdaki kategori içi karşılaştırmadır.
    </div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Kategori içinde: A+ sepeti, kategorinin tüm fonlarına karşı</h2>
      <select id="simCat">${cats.map((c) => `<option ${c === state.cat ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
    </div>
    <div class="chart" id="catChart"></div>
    <div class="table-wrap"><table id="catSummary" class="compact"></table></div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Aylık sepetler</h2>
      <select id="simMonth">${months.slice().reverse().map((m) => `<option value="${m}" ${m === state.month ? "selected" : ""}>${dateTR(m)}</option>`).join("")}</select>
    </div>
    <div id="simHoldings"></div>
  </section>`;

  const periodMonths = () => PERIODS.find(([k]) => k === state.period)[2];
  const drawMain = () => {
    const q = state.qualified;
    const i0 = startIndex(sim.dates, periodMonths());
    const d = sim.dates.slice(i0);
    const keys = [q ? "aplus" : "aplus_public", q ? "universe" : "universe_public", "ppf", "gold", "tufe", "usd"].filter((k) => sim.series[k]);
    const series = keys.map((k) => ({
      name: sim.series[k].label.replace(" (nitelikli dahil)", ""),
      d, v: windowed(sim.series[k].v, i0), color: COLORS[k], dashed: k.startsWith("universe"),
    }));
    lineChart(app.querySelector("#simChart"), series, { base: 100, height: 320, format: (v) => num(v, 0) });
    app.querySelector("#simRange").textContent = `${dateTR(d[0])} – ${dateTR(d[d.length - 1])} · dönem başı = 100 · aylık yeniden dengeleme`;
    app.querySelector("#simStatsSub").textContent = `${dateTR(d[0])} – ${dateTR(d[d.length - 1])} · aylık getirilerden${periodMonths() && periodMonths() < 12 ? " · yıllık getiri 1 yıldan kısa dönemde gösterilmez" : ""}`;
    const ppfW = sim.series.ppf ? windowed(sim.series.ppf.v, i0) : null;
    const stats = Object.fromEntries(keys.map((k) => [k, windowStats(d, windowed(sim.series[k].v, i0), k === "ppf" ? null : ppfW)]));
    app.querySelector("#simStats").innerHTML = `
      <thead><tr><th class="left">Sepet / varlık</th><th>Toplam</th><th>Yıllık</th><th>Maks. düşüş</th><th>Oynaklık</th>
        <th>En kötü / en iyi ay</th><th>Pozitif ay</th><th>PPF'yi geçen ay</th></tr></thead>
      <tbody>${keys.map((k, i) => statRow(sim.series[k]?.label.replace(" (nitelikli dahil)", "") || k, stats[k], i === 0 ? "is-self" : "")).join("")}</tbody>`;
  };

  const drawCat = () => {
    const c = sim.byCategory[state.cat];
    const i0 = startIndex(sim.dates, periodMonths());
    const d = sim.dates.slice(i0);
    const va = windowed(c.aplus, i0), vu = windowed(c.universe, i0);
    lineChart(app.querySelector("#catChart"), [
      { name: `${state.cat} · A+ sepeti`, d, v: va, color: "var(--brand-3)" },
      { name: `${state.cat} · tüm fonlar`, d, v: vu, color: "var(--text-dim)", dashed: true },
    ], { base: 100, height: 260, format: (v) => num(v, 0) });
    const a = windowStats(d, va), u = windowStats(d, vu);
    const ra = va.slice(1).map((v, i) => v / va[i] - 1), ru = vu.slice(1).map((v, i) => v / vu[i] - 1);
    c.beatWindow = ra.length ? (ra.filter((r, i) => r > ru[i]).length / ra.length) * 100 : null;
    app.querySelector("#catSummary").innerHTML = `
      <thead><tr><th class="left">${esc(state.cat)}</th><th>Toplam</th><th>Yıllık</th><th>Maks. düşüş</th><th>Kategoriyi geçen ay</th></tr></thead>
      <tbody>
        <tr class="is-self"><td class="left">A+ sepeti</td><td><b class="${a.total >= u.total ? "up" : "down"}">${pct(a.total, 1)}</b></td><td>${pct(a.cagr, 1)}</td><td class="down">${pct(a.mdd, 1)}</td><td>%${num(c.beatWindow, 0)}</td></tr>
        <tr><td class="left">Kategorinin tüm fonları</td><td>${pct(u.total, 1)}</td><td>${pct(u.cagr, 1)}</td><td class="down">${pct(u.mdd, 1)}</td><td>—</td></tr>
      </tbody>`;
  };

  const drawHoldings = () => {
    const h = sim.holdings.find((x) => x.date === state.month);
    const codes = state.qualified ? h.codesAll : h.codes;
    app.querySelector("#simHoldings").innerHTML = `
      <p class="dim">${dateTR(h.date)} sonunda A+ olan ${codes.length} fon; her birine eşit ağırlık verildi.</p>
      <div class="chip-cloud">${codes.map((c) => store.byCode.has(c) ? codeChip(c) : `<span class="code-chip muted-chip" title="Bugün derecelendirilmiyor">${esc(c)}</span>`).join("")}</div>`;
  };

  app.querySelector("#simQ").addEventListener("change", (e) => { state.qualified = e.target.checked; drawMain(); drawHoldings(); });
  app.querySelector("#simPeriod").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || b.disabled) return;
    state.period = b.dataset.p;
    app.querySelectorAll("#simPeriod button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    drawMain();
    drawCat();
  });
  app.querySelector("#simCat").addEventListener("change", (e) => { state.cat = e.target.value; drawCat(); });
  app.querySelector("#simMonth").addEventListener("change", (e) => { state.month = e.target.value; drawHoldings(); });
  drawMain();
  drawCat();
  drawHoldings();
}
