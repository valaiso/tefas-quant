import { esc, num, pct, dateTR, codeChip } from "../util.js";
import { lineChart } from "../chart.js";

const COLORS = {
  aplus_public: "var(--brand-3)", aplus: "var(--brand-3)",
  universe_public: "var(--text-dim)", universe: "var(--text-dim)",
  ppf: "var(--c6)", gold: "var(--c7, #ca8a04)", tufe: "var(--c2)", usd: "var(--c4)",
};
const state = { qualified: false, cat: null, month: null };
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
    <div class="card-head"><h2>A+ sepeti, altın, TÜFE, PPF ve dolar</h2><span class="sub">Aynı tarihlerde, başlangıç = 100</span></div>
    <div class="chart" id="simChart"></div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Karşılaştırma</h2><span class="sub">Aylık getirilerden</span></div>
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

  const drawMain = () => {
    const q = state.qualified;
    const keys = [q ? "aplus" : "aplus_public", q ? "universe" : "universe_public", "ppf", "gold", "tufe", "usd"];
    const series = keys.filter((k) => sim.series[k]).map((k) => ({
      name: sim.series[k].label.replace(" (nitelikli dahil)", ""),
      d: sim.dates, v: sim.series[k].v, color: COLORS[k], dashed: k.startsWith("universe"),
    }));
    lineChart(app.querySelector("#simChart"), series, { base: 100, height: 320, format: (v) => num(v, 0) });
    app.querySelector("#simStats").innerHTML = `
      <thead><tr><th class="left">Sepet / varlık</th><th>Toplam</th><th>Yıllık</th><th>Maks. düşüş</th><th>Oynaklık</th>
        <th>En kötü / en iyi ay</th><th>Pozitif ay</th><th>PPF'yi geçen ay</th></tr></thead>
      <tbody>${keys.map((k, i) => statRow(sim.series[k]?.label.replace(" (nitelikli dahil)", "") || k, sim.stats[k], i === 0 ? "is-self" : "")).join("")}</tbody>`;
  };

  const drawCat = () => {
    const c = sim.byCategory[state.cat];
    lineChart(app.querySelector("#catChart"), [
      { name: `${state.cat} · A+ sepeti`, d: sim.dates, v: c.aplus, color: "var(--brand-3)" },
      { name: `${state.cat} · tüm fonlar`, d: sim.dates, v: c.universe, color: "var(--text-dim)", dashed: true },
    ], { base: 100, height: 260, format: (v) => num(v, 0) });
    const a = c.stats.aplus, u = c.stats.universe;
    app.querySelector("#catSummary").innerHTML = `
      <thead><tr><th class="left">${esc(state.cat)}</th><th>Toplam</th><th>Yıllık</th><th>Maks. düşüş</th><th>Kategoriyi geçen ay</th></tr></thead>
      <tbody>
        <tr class="is-self"><td class="left">A+ sepeti</td><td><b class="${a.total >= u.total ? "up" : "down"}">${pct(a.total, 1)}</b></td><td>${pct(a.cagr, 1)}</td><td class="down">${pct(a.mdd, 1)}</td><td>%${num(c.beat, 0)}</td></tr>
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
  app.querySelector("#simCat").addEventListener("change", (e) => { state.cat = e.target.value; drawCat(); });
  app.querySelector("#simMonth").addEventListener("change", (e) => { state.month = e.target.value; drawHoldings(); });
  drawMain();
  drawCat();
  drawHoldings();
}
