import { esc, num, pct, pctCell, money, dateTR, gradeBadge, signalPill, codeChip, scoreBar, COMPONENT_LABELS, RETURN_LABELS } from "../util.js";
import { lineChart, rebase } from "../chart.js";
import { bindRows } from "./common.js";

const PERIODS = [
  { key: "6a", label: "6A", days: 182 },
  { key: "1y", label: "1Y", days: 365 },
  { key: "3y", label: "3Y", days: 1100 },
];

function ring(score) {
  const r = 52, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, score || 0));
  return `<svg class="ring" viewBox="0 0 128 128" aria-label="Skor ${num(score, 1)}">
    <circle cx="64" cy="64" r="${r}" class="ring-bg"/>
    <circle cx="64" cy="64" r="${r}" class="ring-fg" stroke-dasharray="${(c * v) / 100} ${c}" transform="rotate(-90 64 64)"/>
    <text x="64" y="62" text-anchor="middle" class="ring-val">${num(score, 1)}</text>
    <text x="64" y="82" text-anchor="middle" class="ring-cap">/ 100</text></svg>`;
}

function waterfall(f, weights) {
  const rows = Object.entries(weights).map(([k, w]) =>
    `<tr><td>${COMPONENT_LABELS[k]} <span class="dim">× %${num(w * 100, 0)}</span></td><td class="score-cell">${scoreBar(f.b[k])}</td><td class="num">${num(f.b[k] * w, 1)}</td></tr>`);
  const pen = [
    ["Az yatırımcı cezası", -f.p.investor],
    ["Net nakit çıkışı cezası", -f.p.outflow],
    ["Getiri anomalisi cezası", -f.p.anomaly],
    ["Veri güveni ayarı", f.adj.confidence],
    ["Yatırımcı istikrarı ayarı", f.adj.stability],
  ].map(([label, v]) =>
    `<tr class="${v ? "" : "muted"}"><td>${label}</td><td></td><td class="num ${v > 0 ? "up" : v < 0 ? "down" : "dim"}">${v ? (v > 0 ? "+" : "−") + num(Math.abs(v), 1) : "0"}</td></tr>`);
  return `<table class="waterfall">
    <tbody>${rows.join("")}
      <tr class="subtotal"><td>Bileşen skoru</td><td></td><td class="num">${num(f.abs, 1)}</td></tr>
      ${pen.join("")}
      <tr class="total"><td>Final skor</td><td></td><td class="num">${num(f.s, 1)}</td></tr>
    </tbody></table>`;
}

export async function render(app, route, store) {
  const f = store.byCode.get(route.arg);
  if (!f) {
    const ex = store.meta.excluded.find((x) => x.code === route.arg);
    app.innerHTML = ex
      ? `<div class="card notice-card warn"><h3>${esc(ex.code)} derecelendirilmiyor</h3>
          <p>${esc(ex.name)}</p><p>Neden: <b>${esc(ex.reason)}</b> · Son fiyat: ${dateTR(ex.lastDate)}</p>
          <p class="dim">İşlemleri durdurulmuş, fiyatı ${store.meta.config.stalePriceDays} günden uzun süredir yayımlanmayan ya da pay adedi ve yatırımcı sayısı donmuş fonlar alınıp satılamadığı için sıralamaya alınmaz.</p></div>`
      : `<div class="card empty"><h3>Fon bulunamadı</h3><p>${esc(route.arg || "")} kodlu fon derecelendirilen fonlar arasında yok.</p></div>`;
    return;
  }

  const peers = store.funds.filter((x) => x.k === f.k).sort((a, b) => a.rk - b.rk);
  const around = peers.slice(0, 8);
  if (!around.includes(f)) around.push(f);
  const totalPenalty = f.p.investor + f.p.outflow + f.p.anomaly;

  app.innerHTML = `
  <section class="fund-hero">
    <div class="fund-hero-main">
      <div class="fund-hero-tags"><span class="tag">${esc(f.k)}</span>${f.q ? `<span class="tag tag-warn">Nitelikli yatırımcı</span>` : ""}
        ${signalPill(f.sig)}</div>
      <h2><span class="mono">${esc(f.c)}</span> ${esc(f.n)}</h2>
      <div class="fund-hero-figs">
        <div><span>Kategori sırası</span><b>${f.rk} / ${f.ct}</b></div>
        <div><span>Genel sıra</span><b>${f.or} / ${store.funds.length}</b></div>
        <div><span>Kategori yüzdeliği</span><b>%${num(f.pc, 0)}</b></div>
        <div><span>Veri güveni</span><b>%${num(f.cf, 0)}</b></div>
        <div><span>Fon büyüklüğü</span><b>${money(f.aum)}</b></div>
        <div><span>Yatırımcı</span><b>${num(f.inv, 0)}</b></div>
      </div>
    </div>
    <div class="fund-hero-score">${ring(f.s)}<div class="fund-grade">${gradeBadge(f)}<span>${esc(f.sig)}</span></div></div>
  </section>

  ${f.p.anomaly > 0 ? `<div class="notice warn">⚠ <b>Getiri anomalisi:</b> 1 yıllık getirisi (${pct(f.r["1y"], 1)}) kategorisinin çok üstünde,
    bu yüzden −${num(f.p.anomaly, 1)} puan ceza aldı. Pürüzsüz ve olağan dışı yüksek getiri, değerlemesi zor ya da likit olmayan
    varlıklara işaret edebilir; portföy dağılımını ve KAP bildirimlerini kontrol edin.</div>` : ""}

  <div class="grid grid-2">
    <section class="card">
      <div class="card-head"><h2>Skor nasıl oluştu?</h2><span class="sub">${totalPenalty ? `Toplam ceza −${num(totalPenalty, 1)}` : "Ceza yok"}</span></div>
      ${waterfall(f, store.meta.config.weights)}
    </section>
    <section class="card">
      <div class="card-head"><h2>Fiyat performansı</h2>
        <div class="seg" id="periodSeg">${PERIODS.map((p) => `<button data-k="${p.key}" aria-pressed="${p.key === "1y"}">${p.label}</button>`).join("")}</div>
      </div>
      <div class="chart" id="priceChart"><div class="loading"><div class="spinner"></div></div></div>
      <p class="chart-note dim">Haftalık kapanış, dönem başı = 100. Kesik çizgi: ${esc(f.k)} kategorisi eşit ağırlıklı ortalaması.</p>
    </section>
  </div>

  <div class="grid grid-3">
    <section class="card">
      <div class="card-head"><h2>Getiriler</h2></div>
      <table class="kv">${Object.entries(RETURN_LABELS).map(([k, l]) => `<tr><td>${l}</td><td>${pctCell(f.r[k])}</td></tr>`).join("")}
        <tr><td>Yıllık bileşik (CAGR)</td><td>${pctCell(f.m.cagr)}</td></tr></table>
    </section>
    <section class="card">
      <div class="card-head"><h2>Risk</h2><span class="sub">Son 1 yıl</span></div>
      <table class="kv">
        <tr><td>Volatilite (yıllık)</td><td>%${num(f.m.vol, 1)}</td></tr>
        <tr><td>Maksimum düşüş</td><td class="down">−%${num(f.m.mdd, 1)}</td></tr>
        <tr><td>Sharpe</td><td>${num(f.m.sharpe)}</td></tr>
        <tr><td>Sortino</td><td>${num(f.m.sortino)}</td></tr>
        <tr><td>Calmar</td><td>${num(f.m.calmar)}</td></tr>
        <tr><td title="Günlük getirilerin otokorelasyonu; yüksekse fiyat olağan dışı pürüzsüz">Pürüzsüzlük (otokorelasyon)</td><td>${num(f.m.ac1)}</td></tr>
        <tr><td>Beta (kategoriye göre, ${store.meta.config.historyYears}Y)</td><td>${num(f.m.beta)}</td></tr>
        <tr><td>Alfa (yıllık)</td><td>${pctCell(f.m.alpha)}</td></tr>
        <tr><td>Bilgi oranı</td><td>${num(f.m.ir)}</td></tr>
      </table>
    </section>
    <section class="card">
      <div class="card-head"><h2>Yatırımcı & akış</h2></div>
      <table class="kv">
        <tr><td>Yatırımcı sayısı</td><td>${num(f.inv, 0)}</td></tr>
        <tr><td>Yatırımcı değişimi (1A)</td><td>${pctCell(f.ig, 1)}</td></tr>
        <tr><td>Net akış (1 hafta)</td><td class="${f.fl["1w"] >= 0 ? "up" : "down"}">${money(f.fl["1w"])}</td></tr>
        <tr><td>Net akış (1 ay)</td><td class="${f.fl["1m"] >= 0 ? "up" : "down"}">${money(f.fl["1m"])}</td></tr>
        <tr><td>Net akış (3 ay)</td><td class="${f.fl["3m"] >= 0 ? "up" : "down"}">${money(f.fl["3m"])}</td></tr>
        <tr><td>Büyüklük değişimi (1A)</td><td>${pctCell(f.ag, 1)}</td></tr>
        <tr><td>3A akış / büyüklük</td><td>${pctCell(f.fr3, 1)}</td></tr>
        <tr><td>Yönetim ücreti</td><td>%${num(f.fee)}</td></tr>
        <tr><td>Stopaj</td><td>${f.st == null ? "—" : "%" + num(f.st, 1)}</td></tr>
      </table>
    </section>
  </div>

  <section class="card">
    <div class="card-head"><h2>${esc(f.k)} kategorisinde ilk sıralar</h2>
      <a class="btn btn-sm" href="#/karsilastir?f=${[f.c, ...peers.filter((x) => x !== f).slice(0, 2).map((x) => x.c)].join(",")}">Liderlerle karşılaştır →</a></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Sıra</th><th class="left">Fon</th><th>Not</th><th>Skor</th><th>3 Ay</th><th>1 Yıl</th><th>Volatilite</th></tr></thead>
      <tbody>${around.map((x) => `<tr class="row-link ${x === f ? "is-self" : ""}" data-href="#/fon/${encodeURIComponent(x.c)}">
        <td>${x.rk}</td><td class="fund-cell left">${codeChip(x.c)}<span class="name">${esc(x.n)}</span></td>
        <td>${gradeBadge(x)}</td><td class="score-cell">${scoreBar(x.s)}</td>
        <td>${pctCell(x.r["3a"])}</td><td>${pctCell(x.r["1y"])}</td><td>%${num(x.m.vol, 1)}</td></tr>`).join("")}
      </tbody></table></div>
  </section>`;

  bindRows(app);

  const hist = await store.history(f.c);
  const cat = store.categories[f.k];
  const chartEl = app.querySelector("#priceChart");
  const draw = (key) => {
    if (!hist) { chartEl.innerHTML = `<div class="empty">Fiyat geçmişi yok</div>`; return; }
    const days = PERIODS.find((p) => p.key === key).days;
    const from = new Date(Date.parse(store.meta.lastDataDate) - days * 86400000).toISOString().slice(0, 10);
    const fund = rebase(hist.d, hist.p, from);
    const series = [{ name: f.c, ...fund }];
    if (cat) series.push({ name: `${f.k} ort.`, ...rebase(cat.d, cat.v, fund.d[0]), dashed: true, color: "var(--text-dim)" });
    lineChart(chartEl, series, { base: 100, format: (v) => num(v, 0) });
  };
  draw("1y");
  app.querySelector("#periodSeg").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    app.querySelectorAll("#periodSeg button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    draw(b.dataset.k);
  });
}
