import { esc, num, pct, dateTR, codeChip, gradeBadge } from "../util.js";
import { lineChart } from "../chart.js";
import { startIndex, windowed, windowStats, statRow } from "./simulation.js";

const COLORS = { model: "var(--brand-3)", ppf: "var(--c6)", gold: "var(--c7, #ca8a04)", tufe: "var(--c2)", usd: "var(--c4)" };
const LABELS = { model: "Model sepeti", ppf: "PPF ortalaması", gold: "Gram altın", tufe: "TÜFE", usd: "Dolar/TL" };
const SLICE = ["#0f766e", "#2563eb", "#ca8a04", "#7c3aed", "#db2777", "#0891b2", "#65a30d", "#ea580c", "#475569", "#9333ea"];
const PERIODS = [["6a", "6A", 6], ["1y", "1Y", 12], ["2y", "2Y", 24], ["all", "Tümü", null]];
const state = { period: "all", month: null };
let cache = null;

async function load() {
  if (!cache) {
    const r = await fetch(`data/model.json?v=${Date.now().toString(36).slice(0, -3)}`);
    if (!r.ok) throw new Error(`model.json: ${r.status}`);
    cache = await r.json();
  }
  return cache;
}


export async function render(app, _route, store) {
  app.innerHTML = `<div class="loading"><div class="spinner"></div><p>Model yükleniyor…</p></div>`;
  const m = await load();
  const R = m.rules;
  const basket = m.basket;
  const bt = m.backtest;
  const months = m.history.map((h) => h.date);
  if (!state.month || !months.includes(state.month)) state.month = months[months.length - 1];

  const bar = basket.map((b, i) => `<span style="width:${b.w}%;background:${SLICE[i % SLICE.length]}" title="${esc(b.c)} %${b.w}">${esc(b.c)} %${b.w}</span>`).join("");
  const rows = basket.map((b, i) => `<tr>
      <td class="left"><span class="mdl-swatch" style="background:${SLICE[i % SLICE.length]}"></span>${codeChip(b.c)}
        <span class="fund-name">${esc(b.n)}</span></td>
      <td class="left dim">${esc(b.k || "—")}</td>
      <td><b class="weight">%${b.w}</b></td>
      <td>${num(b.score, 0)}</td>
      <td>${store.byCode.has(b.c) ? gradeBadge(store.byCode.get(b.c)) : "—"}</td>
      <td>${pct(b.r["1y"], 1)}</td><td>${pct(b.r["2y"], 1)}</td><td>${pct(b.r["3y"], 1)}</td>
      <td>%${num(b.win, 0)}</td>
      <td class="down">${pct(b.mdd, 1)}</td>
      <td>%${num(b.vol, 1)}</td>
    </tr>`).join("");

  app.innerHTML = `
  <section class="method-intro card">
    <h2>Model Portföy <span class="model-tag">${basket.length} fon</span></h2>
    <p>Her kategoriden bir fon vermek yerine, son <b>1-2-3 yılda istikrarlı</b> getiri vermiş ve getirisi tek bir sıçramaya dayanmayan
      ${R.minFunds}–${R.maxFunds} fondan oluşan, ağırlıklı bir sepet. Sepet her işlem günü ${dateTR(m.asOf)} verisiyle yeniden kurulur.
      ${m.candidates} aday fondan ${m.clean} tanesi istikrar ve sıçrama filtrelerini geçti.</p>
  </section>

  <section class="card">
    <div class="card-head"><h2>Bugünkü sepet</h2><span class="sub">${dateTR(m.asOf)} · ağırlıklar 5'in katı</span></div>
    <div class="weight-bar">${bar}</div>
    <div class="table-wrap"><table class="model-table">
      <thead><tr><th class="left">Fon</th><th class="left">Kategori</th><th>Ağırlık</th><th title="Model puanı (0-100, adaylar arasında yüzdelik)">Puan</th><th>Not</th>
        <th title="Yıllık bileşik">1Y</th><th title="Yıllık bileşik">2Y yıllık</th><th title="Yıllık bileşik">3Y yıllık</th>
        <th title="Son 2 yılda, 12 aylık dönemlerin kaçında PPF'yi geçti">PPF'yi geçen 12A</th><th>Maks. düşüş (2Y)</th><th>Oynaklık (1Y)</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot>
        <tr class="is-self"><td class="left"><b>Sepet (ağırlıklı)</b></td><td></td><td><b>%100</b></td><td></td><td></td>
          <td><b>${pct(m.portfolio["1y"], 1)}</b></td><td><b>${pct(m.portfolio["2y"], 1)}</b></td><td><b>${pct(m.portfolio["3y"], 1)}</b></td><td colspan="3"></td></tr>
        <tr><td class="left dim">PPF ortalaması</td><td></td><td></td><td></td><td></td>
          <td>${pct(m.ppf["1y"], 1)}</td><td>${pct(m.ppf["2y"], 1)}</td><td>${pct(m.ppf["3y"], 1)}</td><td colspan="3"></td></tr>
      </tfoot>
    </table></div>
    <div class="notice warn">Bu sayfa bir <b>model çıktısıdır, yatırım tavsiyesi değildir</b>. Geçmiş getiri gelecek getirinin göstergesi değildir;
      kişisel risk tercihin, vaden ve vergi durumun dikkate alınmadı. Getiriler stopaj ve fon giriş/çıkış kuralları hariçtir.</div>
  </section>

  ${bt.available ? `<section class="card">
    <div class="card-head"><h2>Model geçmişte nasıl sonuç verdi?</h2>
      <div class="seg" id="mdlPeriod">${PERIODS.map(([k, l]) => `<button data-p="${k}" aria-pressed="${k === state.period}">${l}</button>`).join("")}</div>
    </div>
    <div class="chart" id="mdlChart"></div>
    <p class="chart-note dim" id="mdlRange"></p>
    <div class="table-wrap"><table id="mdlStats"></table></div>
    <div class="notice">Her ay sonunda sepet <b>yalnızca o gün bilinen fiyatlarla</b> aynı kurallarla yeniden kuruldu, ertesi işlem günü (T+1)
      alındı ve bir ay tutuldu. Geçmişte o günkü skor bayrakları (anomali, kurucu riski vb.) bilinemediği için yalnızca fiyat, büyüklük ve
      yatırımcı filtreleri uygulandı. Model 3 yıllık geçmiş istediğinden ${dateTR(bt.dates[0])} tarihinde başlıyor.</div>
  </section>` : ""}

  ${months.length ? `<section class="card">
    <div class="card-head"><h2>Geçmiş aylık sepetler</h2>
      <select id="mdlMonth">${months.slice().reverse().map((d) => `<option value="${d}" ${d === state.month ? "selected" : ""}>${dateTR(d)}</option>`).join("")}</select>
    </div>
    <div id="mdlHoldings"></div>
  </section>` : ""}

  ${m.spiky.length ? `<section class="card">
    <div class="card-head"><h2>Sıçrama nedeniyle alınmayan fonlar</h2><span class="sub">Getirisi PPF'yi geçtiği hâlde tek sıçramaya dayalı görünenler</span></div>
    <div class="table-wrap"><table class="compact">
      <thead><tr><th class="left">Fon</th><th class="left">Kategori</th><th>2Y yıllık</th><th class="left">Neden</th></tr></thead>
      <tbody>${m.spiky.map((s) => `<tr><td class="left">${store.byCode.has(s.c) ? codeChip(s.c) : esc(s.c)} <span class="fund-name">${esc(s.n)}</span></td>
        <td class="left dim">${esc(s.k || "—")}</td><td>${pct(s.r2, 1)}</td><td class="left">${esc(s.why)}</td></tr>`).join("")}</tbody>
    </table></div>
  </section>` : ""}

  <section class="card">
    <div class="card-head"><h2>Model kuralları</h2></div>
    <ol class="rule-list">
      <li><b>Aday havuzu:</b> halka açık (nitelikli/özel değil), en az 3 yıl geçmiş, ≥${num(R.minAum / 1e6, 0)}m TL büyüklük, ≥${num(R.minInvestors, 0)} yatırımcı,
        fiyatı güncel; skorda dışlanan, getiri anomalisi, kurucu riski, kuyruk riski veya sıcak para bayrağı olan fonlar alınmaz.</li>
      <li><b>Sıçrama filtresi:</b> 2 yıllık getirinin %${num(R.spikeShare * 100, 0)}'ından fazlası tek aydan geliyorsa, son 3 ay kendi geçmişine göre
        aşırıysa (z &gt; ${num(R.spikeZ, 1)}) ya da son 1 yılda tek günde ±%${num(R.spikeDay * 100, 0)}'ten büyük hareket varsa fon elenir.</li>
      <li><b>İstikrar şartı:</b> 1Y, 2Y ve 3Y yıllık getirinin <b>hepsinde</b> PPF ortalamasını geçmiş olmalı; son 2 yıldaki 12 aylık dönemlerin
        en az %${num(R.minWin * 100, 0)}'ında PPF'yi geçmeli.</li>
      <li><b>Puan:</b> getiri ${R.weights.ret} (1Y/2Y/3Y), istikrar ${R.weights.win} (PPF'yi geçen 12 aylık dönem oranı), Sharpe ${R.weights.sharpe} (2 yıl),
        düşüş ${R.weights.mdd} (2 yıllık azami düşüş); hepsi adaylar arasında yüzdelik.</li>
      <li><b>Seçim:</b> puan sırasıyla; aynı kategoriden en fazla ${R.maxPerCategory}, seçilmiş bir fonla haftalık getiri korelasyonu &gt; ${num(R.maxCorr, 2)}
        olan fon alınmaz; puanı ${R.minScore}'ın altına inen fon alınmaz; en az ${R.minFunds}, en fazla ${R.maxFunds} fon (yeterli fon yoksa nakit ayağı olarak para piyasası fonu eklenir).</li>
      <li><b>Ağırlık:</b> puan ve düşük oynaklıkla orantılı; her fon %${num(R.minW * 100, 0)}–%${num(R.maxW * 100, 0)} aralığında, 5'in katlarına yuvarlanır.</li>
    </ol>
  </section>`;

  if (bt.available) {
    const keys = Object.keys(bt.series);
    const periodMonths = () => PERIODS.find(([k]) => k === state.period)[2];
    const draw = () => {
      const i0 = startIndex(bt.dates, periodMonths());
      const d = bt.dates.slice(i0);
      lineChart(app.querySelector("#mdlChart"), keys.map((k) => ({ name: LABELS[k] || k, d, v: windowed(bt.series[k], i0), color: COLORS[k] })),
        { base: 100, height: 300, format: (v) => num(v, 0) });
      app.querySelector("#mdlRange").textContent = `${dateTR(d[0])} – ${dateTR(d[d.length - 1])} · dönem başı = 100 · aylık yeniden kurulum`;
      const ppfW = bt.series.ppf ? windowed(bt.series.ppf, i0) : null;
      app.querySelector("#mdlStats").innerHTML = `
        <thead><tr><th class="left">Sepet / varlık</th><th>Toplam</th><th>Yıllık</th><th>Maks. düşüş</th><th>Oynaklık</th>
          <th>En kötü / en iyi ay</th><th>Pozitif ay</th><th>PPF'yi geçen ay</th></tr></thead>
        <tbody>${keys.map((k, i) => statRow(LABELS[k] || k, windowStats(d, windowed(bt.series[k], i0), k === "ppf" ? null : ppfW), i === 0 ? "is-self" : "")).join("")}</tbody>`;
    };
    app.querySelector("#mdlPeriod").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      state.period = b.dataset.p;
      app.querySelectorAll("#mdlPeriod button").forEach((x) => x.setAttribute("aria-pressed", x === b));
      draw();
    });
    draw();
  }

  if (months.length) {
    const drawHoldings = () => {
      const h = m.history.find((x) => x.date === state.month);
      app.querySelector("#mdlHoldings").innerHTML = `<p class="dim">${dateTR(h.date)} sonunda kurulan ${h.items.length} fonluk sepet.</p>
        <div class="chip-cloud">${h.items.map(([c, w]) => `<span class="hold-chip">${store.byCode.has(c) ? codeChip(c) : `<span class="code-chip muted-chip" title="Bugün derecelendirilmiyor">${esc(c)}</span>`}<b>%${w}</b></span>`).join("")}</div>`;
    };
    app.querySelector("#mdlMonth").addEventListener("change", (e) => { state.month = e.target.value; drawHoldings(); });
    drawHoldings();
  }
}
