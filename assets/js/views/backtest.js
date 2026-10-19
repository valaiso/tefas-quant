import { esc, num, pct, pctCell, dateTR, codeChip } from "../util.js";

const LABELS = { "1a": "1 Ay", "3a": "3 Ay", "6a": "6 Ay", "1y": "1 Yıl", "2y": "2 Yıl", "3y": "3 Yıl" };
const GRADE_CLASS = { "A+": "sig-aplus", A: "sig-a", B: "sig-b", C: "sig-c", D: "sig-d" };
const state = { horizon: "1y", date: null, sort: "mean" };
let cache = null;

async function load() {
  if (!cache) {
    const r = await fetch(`data/backtest.json?v=${Date.now().toString(36).slice(0, -3)}`);
    if (!r.ok) throw new Error(`backtest.json: ${r.status}`);
    cache = await r.json();
  }
  return cache;
}

// Renk mutlak getiriye değil kategoriye göredir: kategori medyanının altında kalan sonuç kırmızı.
const vsCls = (d) => (d == null ? "" : d >= 0 ? "up" : "down");
const hitCls = (h) => (h == null ? "" : h >= 55 ? "up" : h < 50 ? "down" : "");

function kpi(h, v) {
  if (!v) {
    return `<div class="card bt-kpi muted"><div class="bt-h">${LABELS[h]}</div>
      <div class="bt-na">Henüz veri yok</div><div class="dim small-note">Veri penceresi bu vadeyi ölçmeye yetmiyor</div></div>`;
  }
  return `<div class="card bt-kpi">
    <div class="bt-h">${LABELS[h]} sonra</div>
    <div class="bt-main ${vsCls(v.excessMean)}">${pct(v.mean, 1)}</div>
    <div class="bt-sub">A+ ortalaması · medyan ${pct(v.median, 1)}</div>
    <div class="bt-rows">
      <div><span title="Aynı tarih ve kategorideki tüm fonların medyan getirisi, A+ gözlemleri üzerinden ortalama">Kategori kıyası</span><b>${pct(v.catMean, 1)}</b></div>
      <div><span>Kategoriye göre fark</span><b class="${vsCls(v.excessMean)}">${pct(v.excessMean, 2)}</b></div>
      <div><span>Kategoriyi geçme</span><b class="${hitCls(v.hit)}">%${num(v.hit, 0)}</b></div>
      <div><span>Gözlem</span><b>${num(v.n, 0)} <span class="dim">· ${v.dates} ay</span></b></div>
    </div>
  </div>`;
}

export async function render(app, _route, store) {
  app.innerHTML = `<div class="loading"><div class="spinner"></div><p>Backtest yükleniyor…</p></div>`;
  const bt = await load();
  const hs = Object.keys(bt.horizons);
  const dates = bt.byDate.map((d) => d.date);
  if (!state.date || !dates.includes(state.date)) state.date = dates[Math.max(0, dates.length - 13)] || dates[0];

  app.innerHTML = `
  <section class="method-intro card">
    <h2>QuantBacktest <span class="model-tag">A+ · GÜÇLÜ AL</span></h2>
    <p>Her ay sonunda (${dateTR(bt.signalDates[0])} – ${dateTR(bt.signalDates[bt.signalDates.length - 1])}, ${bt.signalDates.length} ay)
      skorlar <b>yalnızca o güne kadar bilinen veriyle</b> yeniden üretildi. O tarihte A+ notu alan her fon, sonradan notu düşse,
      çökse ya da listeden çıksa bile, ertesi işlem günü fiyatından (T+1) alınmış sayılıp sonraki getirisi ölçüldü.
      Toplam ${num(bt.observations, 0)} A+ gözlemi. Kıyas ölçüsü: aynı ay, aynı kategorideki tüm fonların medyan getirisi.
      A+ canlı sitedeki sıkı kuralla verildi (üst %5, kalite şartları, 2 ay süreklilik, kurucu riski yok); ilk A+ sinyali
      ${dateTR(bt.byDate[0]?.date)}. Renkler kategoriye göredir: kategori kıyasının altında kalan sonuç kırmızı gösterilir.</p>
  </section>

  <div class="grid bt-grid">${hs.map((h) => kpi(h, bt.overall[h])).join("")}</div>

  <section class="card">
    <div class="card-head"><h2>Notlar gerçekten ayırt ediyor mu?</h2>
      <span class="sub">Her not için kategori medyanını geçme oranı ve medyana göre fark</span></div>
    <div class="table-wrap"><table class="bt-grades">
      <thead><tr><th>Not</th>${hs.map((h) => `<th>${LABELS[h]}</th>`).join("")}</tr></thead>
      <tbody>${Object.entries(bt.byGrade).map(([g, row]) => `<tr>
        <td><span class="grade ${GRADE_CLASS[g]}">${g}</span></td>
        ${hs.map((h) => row[h] ? `<td><b>%${num(row[h].hit, 0)}</b> <span class="${row[h].excess >= 0 ? "up" : "down"} small-note">${pct(row[h].excess, 1)}</span></td>` : `<td class="dim">—</td>`).join("")}
      </tr>`).join("")}</tbody>
    </table></div>
    <p class="chart-note dim">Hücre: kategori medyanını geçen gözlem oranı · küçük sayı: kategori medyanına göre medyan fark.
      %50 rastgele seçimdir; A+'tan D'ye düzenli düşüş notların bilgi taşıdığını gösterir.</p>
  </section>

  <section class="card">
    <div class="card-head"><h2>Kategori bazında A+ getirileri</h2>
      <div class="seg" id="hSeg">${hs.filter((h) => bt.overall[h]).map((h) => `<button data-h="${h}" aria-pressed="${h === state.horizon}">${LABELS[h]}</button>`).join("")}</div>
    </div>
    <div class="table-wrap"><table id="catTable"></table></div>
  </section>

  <section class="card">
    <div class="card-head"><h2>O ay A+ olan fonlar</h2>
      <label class="field inline"><span>Sinyal tarihi</span>
        <select id="dateSel">${dates.slice().reverse().map((d) => `<option value="${d}" ${d === state.date ? "selected" : ""}>${dateTR(d)}</option>`).join("")}</select>
      </label>
    </div>
    <div class="table-wrap"><table id="dateTable"></table></div>
  </section>

  <div class="notice">
    <b>Sınırlar:</b> Yönetim ücreti ve kategori bugünkü değerlerdir. Fiyatı yayımlanmayı bırakan bir fon son yayımlanan
    fiyatla değerlenir (gerçekte çıkış mümkün olmayabilir, kayıp eksik ölçülebilir). Veri penceresi ${store.meta.config.historyYears} yıl
    olduğu için uzun vadelerde gözlem sayısı az (3 yıl: ${num(bt.overall["3y"]?.n || 0, 0)} gözlem, ${bt.overall["3y"]?.dates || 0} ay);
    bu vadelerde kategoriyi geçme oranı %50'ye yakınsa fark istatistiksel olarak anlamlı sayılmamalı. Geçmiş sonuçlar geleceği garanti etmez.
  </div>`;

  const drawCats = () => {
    const h = state.horizon;
    const rows = Object.entries(bt.byCategory)
      .map(([cat, v]) => [cat, v[h]])
      .filter(([, v]) => v)
      .sort((a, b) => b[1][state.sort] - a[1][state.sort]);
    const head = [["cat", "Kategori"], ["mean", "A+ ortalama"], ["catMean", "Kategori kıyası"], ["excessMean", "Fark"],
      ["median", "A+ medyan"], ["hit", "Kategoriyi geçme"], ["n", "Gözlem"]];
    app.querySelector("#catTable").innerHTML = `
      <thead><tr>${head.map(([k, l], i) => `<th class="${i === 0 ? "left" : "sortable"}" data-k="${k}">${l}${k === state.sort ? " ↓" : ""}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(([cat, v]) => `<tr>
        <td class="left"><a href="#/siralama?k=${encodeURIComponent(cat)}">${esc(cat)}</a></td>
        <td class="${vsCls(v.excessMean)}">${pct(v.mean, 1)}</td><td class="dim">${pct(v.catMean, 1)}</td>
        <td class="${vsCls(v.excessMean)}">${pct(v.excessMean, 2)}</td><td>${pct(v.median, 1)}</td>
        <td class="${hitCls(v.hit)}">%${num(v.hit, 0)}</td><td class="dim">${num(v.n, 0)} · ${v.dates} ay</td>
      </tr>`).join("")}</tbody>`;
    app.querySelectorAll("#catTable th.sortable").forEach((th) => th.addEventListener("click", () => {
      state.sort = th.dataset.k;
      drawCats();
    }));
  };

  const drawDate = () => {
    const d = bt.byDate.find((x) => x.date === state.date);
    const list = (d?.funds || []).slice().sort((a, b) => (b[2 + hs.indexOf("1y")] ?? -1e9) - (a[2 + hs.indexOf("1y")] ?? -1e9));
    app.querySelector("#dateTable").innerHTML = `
      <thead><tr><th>Fon</th><th class="left">Kategori</th>${hs.map((h) => `<th>${LABELS[h]}</th>`).join("")}</tr></thead>
      <tbody>${list.map(([code, cat, ...r]) => `<tr>
        <td>${store.byCode.has(code) ? codeChip(code) : `<span class="code-chip muted-chip" title="Bugün derecelendirilmiyor">${esc(code)}</span>`}</td>
        <td class="left dim">${esc(cat)}</td>
        ${r.map((v, i) => {
          if (v == null) return `<td class="dim">—</td>`;
          const cm = d.cat?.[cat]?.[i];
          return `<td class="${cm == null ? "" : vsCls(v - cm)}" title="Kategori medyanı ${pct(cm, 1)}">${pct(v, 1)}</td>`;
        }).join("")}
      </tr>`).join("")}</tbody>
      <caption class="chart-note dim" style="caption-side:bottom;text-align:left">Renk, aynı tarihteki kategori medyanına göredir (üzerine gelince medyan görünür).</caption>`;
  };

  app.querySelector("#hSeg").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state.horizon = b.dataset.h;
    app.querySelectorAll("#hSeg button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    drawCats();
  });
  app.querySelector("#dateSel").addEventListener("change", (e) => { state.date = e.target.value; drawDate(); });
  drawCats();
  drawDate();
}
