// Değer: kendi yatırım fonu / BES dağılımını sitenin modelleriyle karşılaştır ve fonlarını değerlendir.
import { esc, num, pct, pctCell, money, dateTR, gradeBadge } from "../util.js";
import { lineChart } from "../chart.js";
import { fundHistory, benchData, basketSeries, rebaseFrom, weeklyStats } from "../portfolio.js";

const KEY = "tq_deger";
const PERIODS = [["1y", "1Y", 12], ["2y", "2Y", 24], ["3y", "3Y", 36], ["5y", "5Y", 60]];
const MODELS = [
  ["befas", "BEFAS BES modeli", "var(--brand-3)"],
  ["guvenli", "Güvenli model", "#0f766e"],
  ["dengeli", "Dengeli model", "#2563eb"],
  ["atak", "Atak model", "#c2410c"],
];
let cache = null;

const getJson = (p) => fetch(`${p}?v=${Date.now().toString(36).slice(0, -3)}`).then((r) => (r.ok ? r.json() : null)).catch(() => null);

function load() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "null");
    if (v && Array.isArray(v.rows)) return { showNow: false, ...v };
  } catch { /* depolama kapalı olabilir */ }
  return { rows: [{ c: "CFA", w: 50 }, { c: "YZD", w: 50 }], rebal: "2m", period: "5y", showNow: false };
}
function save(v) {
  try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* yok say */ }
}

async function loadAll(store) {
  if (!cache) {
    const [bes, besModel, model] = await Promise.all([getJson("data/bes.json"), getJson("data/bes_model.json"), getJson("data/model.json")]);
    cache = { besFunds: bes?.funds || [], besModel, model };
  }
  const besBy = new Map(cache.besFunds.map((f) => [f.c, f]));
  return { ...cache, besBy, fonBy: store.byCode };
}

/** Kodun türü: yatırım fonu önce, sonra BES. */
function lookup(code, ctx) {
  if (ctx.fonBy.has(code)) return { kind: "fon", f: ctx.fonBy.get(code) };
  if (ctx.besBy.has(code)) return { kind: "bes", f: ctx.besBy.get(code) };
  return null;
}

/** Sitenin modelleri: gerçek (o günkü veriyle) geçmiş + bugünkü sepet. */
function models(ctx) {
  const out = [];
  const B = ctx.besModel?.befas;
  if (B) out.push({ key: "befas", basket: B.basket.map((b) => ({ c: b.c, w: b.w, kind: "bes" })), bt: B.backtest });
  for (const k of ["guvenli", "dengeli", "atak"]) {
    const p = ctx.model?.profiles?.[k];
    if (p) out.push({ key: k, basket: p.basket.map((b) => ({ c: b.c, w: b.w, kind: "fon" })), bt: p.backtest });
  }
  return out;
}

function flagsOf(item) {
  const { kind, f } = item;
  const out = [];
  if (f.fk) out.push(["danger", "kurucu riski"]);
  if ((f.p?.anomaly || 0) > 0) out.push(["warn", "getiri anomalisi"]);
  if (f.rk2?.tail) out.push(["warn", "kuyruk riski"]);
  if (f.rk2?.hot) out.push(["warn", "sıcak para"]);
  if ((f.p?.drawdown || 0) > 0) out.push(["warn", "sert düşüş"]);
  if (f.rk2?.conc) out.push(["info", "yoğunlaşma"]);
  if (["C", "D"].includes(f.g)) out.push(["warn", `not ${f.g}`]);
  if (kind === "fon" && f.q) out.push(["info", "nitelikli yatırımcı"]);
  if (kind === "bes" && f.bf) out.push(["info", `BEFAS'ta yok (${f.bf})`]);
  if (kind === "bes" && f.ax) out.push(["info", f.ax]);
  return out;
}

export async function render(app, _route, store) {
  app.innerHTML = `<div class="loading"><div class="spinner"></div><p>Değerlendirme hazırlanıyor…</p></div>`;
  const ctx = await loadAll(store);
  const st = load();
  const opts = [
    ...store.funds.map((f) => `<option value="${esc(f.c)}">${esc(f.c)} · Fon · ${esc(f.k)} · ${esc(f.n.slice(0, 50))}</option>`),
    ...ctx.besFunds.filter((f) => !f.ax).map((f) => `<option value="${esc(f.c)}">${esc(f.c)} · BES · ${esc(f.co)} · ${esc(f.k)}</option>`),
  ].join("");

  app.innerHTML = `
  <section class="method-intro card">
    <h2>Değer <span class="model-tag">Fon + BES</span></h2>
    <p>Kendi yatırım fonu ve BES dağılımını yüzdeleriyle gir; sitenin modelleriyle (BEFAS BES modeli, Güvenli, Dengeli, Atak) ve altın, TÜFE,
      dolar, PPF ile <b>5 yıla kadar</b> aynı tarihlerde karşılaştırılır. Altta dağılımındaki her fonun notu, skoru ve cezaları görünür.
      Girdiğin dağılım yalnızca bu tarayıcıda saklanır.</p>
  </section>

  <section class="card">
    <div class="card-head"><h2>Dağılımım</h2>
      <div class="seg" id="dgPeriod">${PERIODS.map(([k, l]) => `<button data-p="${k}" aria-pressed="${k === st.period}">${l}</button>`).join("")}</div></div>
    <datalist id="dgCodes">${opts}</datalist>
    <div class="cmp-rows" id="dgRows"></div>
    <div class="btn-row cmp-actions">
      <button class="btn btn-sm" id="dgAdd" type="button">+ Fon ekle</button>
      <label class="field inline"><span>Yeniden dengeleme</span><select id="dgRebal">
        <option value="2m" ${st.rebal === "2m" ? "selected" : ""}>2 ayda bir hedef yüzdelere dön</option>
        <option value="12m" ${st.rebal === "12m" ? "selected" : ""}>Yılda bir</option>
        <option value="hold" ${st.rebal === "hold" ? "selected" : ""}>Hiç (al ve tut)</option></select></label>
      <label class="switch"><input type="checkbox" id="dgNow" ${st.showNow ? "checked" : ""}><span class="switch-ui" aria-hidden="true"></span>
        <span>Modellerin bugünkü sepetlerini geriye dönük de göster</span></label>
      <span class="dim" id="dgSum"></span>
    </div>
    <div class="chart" id="dgChart"></div>
    <p class="chart-note dim" id="dgNote"></p>
    <div class="table-wrap"><table id="dgStats"></table></div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Dağılımımdaki fonların değerlendirmesi</h2><span class="sub">Not, skor ve cezalar fonun kendi kategorisi içindedir</span></div>
    <div class="kpi-row" id="dgKpi"></div>
    <div class="table-wrap"><table class="model-table" id="dgEval"></table></div>
    <div id="dgWarn"></div>
  </section>`;

  const rowsEl = app.querySelector("#dgRows");
  const items = () => st.rows.map((r) => ({ r, hit: lookup((r.c || "").toUpperCase(), ctx) }));
  const drawRows = () => {
    rowsEl.innerHTML = items().map(({ r, hit }, i) => `<div class="cmp-row">
        <input class="cmp-code" data-i="${i}" list="dgCodes" value="${esc(r.c)}" placeholder="Fon kodu" maxlength="3">
        <input class="cmp-w" data-i="${i}" type="number" min="0" max="100" step="5" value="${r.w}"><span>%</span>
        <span class="cmp-name ${hit || !r.c ? "" : "down"}">${hit ? `<span class="${hit.kind === "bes" ? "ch-tag" : "fx-tag"}">${hit.kind === "bes" ? "BES" : "FON"}</span>
          ${esc(hit.kind === "bes" ? hit.f.co + " · " : "")}${esc(hit.f.k)} · ${esc(hit.f.n.replace(/^.*?A\.Ş\.\s*/, "").slice(0, 60))}` : r.c ? "Kod bulunamadı" : ""}</span>
        <button class="btn btn-sm cmp-del" data-i="${i}" type="button" title="Kaldır">✕</button></div>`).join("");
  };

  const drawEval = () => {
    const list = items().filter((x) => x.hit && +x.r.w > 0);
    const tw = list.reduce((a, x) => a + +x.r.w, 0) || 1;
    const pen = (f) => (f.p?.investor || 0) + (f.p?.outflow || 0) + (f.p?.anomaly || 0) + (f.p?.founder || 0) + (f.p?.drawdown || 0);
    const wavg = (fn) => list.reduce((a, x) => a + (fn(x.hit.f) ?? 0) * +x.r.w, 0) / tw;
    const good = list.filter((x) => ["A+", "A"].includes(x.hit.f.g)).reduce((a, x) => a + +x.r.w, 0) / tw * 100;
    const flagged = list.filter((x) => flagsOf(x.hit).some(([t]) => t !== "info")).reduce((a, x) => a + +x.r.w, 0) / tw * 100;
    const weakest = list.slice().sort((a, b) => a.hit.f.s - b.hit.f.s)[0];
    app.querySelector("#dgKpi").innerHTML = list.length ? `
      <div><span>Ağırlıklı skor</span><b>${num(wavg((f) => f.s), 1)}</b></div>
      <div><span>Ağırlıklı ceza</span><b class="${wavg(pen) > 0 ? "down" : ""}">−${num(wavg(pen), 1)}</b></div>
      <div><span>A / A+ notlu fon payı</span><b>%${num(good, 0)}</b></div>
      <div><span>Uyarılı fon payı</span><b class="${flagged > 0 ? "down" : "up"}">%${num(flagged, 0)}</b></div>
      <div><span>En zayıf fon</span><b>${weakest ? esc(weakest.hit.f.c) + " · " + num(weakest.hit.f.s, 0) : "—"}</b></div>` : "";
    app.querySelector("#dgEval").innerHTML = list.length ? `
      <thead><tr><th class="left">Fon</th><th>Tür</th><th>Ağırlık</th><th class="left">Kategori</th><th>Not</th><th>Skor</th><th>Kat. sırası</th>
        <th title="Az yatırımcı">Yatırımcı c.</th><th title="Net nakit çıkışı">Çıkış c.</th><th title="Getiri anomalisi">Anomali c.</th>
        <th title="Kurucu riski">Kurucu c.</th><th title="Son 3 ayda sert düşüş">Düşüş c.</th><th>Toplam ceza</th>
        <th>1Y</th><th>3Y</th><th>Oynaklık</th><th>Maks. düşüş</th><th class="left">Uyarılar</th></tr></thead>
      <tbody>${list.map(({ r, hit }) => {
        const f = hit.f, p = f.p || {};
        const href = hit.kind === "bes" ? `#/bes/${encodeURIComponent(f.c)}` : `#/fon/${encodeURIComponent(f.c)}`;
        const c = (v) => (v ? `<span class="down">−${num(v, 1)}</span>` : `<span class="dim">0</span>`);
        return `<tr><td class="left"><a class="code-chip" href="${href}">${esc(f.c)}</a><span class="fund-name">${esc(f.n)}</span></td>
          <td>${hit.kind === "bes" ? "BES" : "Fon"}</td><td><b>%${num(+r.w / tw * 100, 0)}</b></td><td class="left dim">${esc(f.k)}</td>
          <td>${gradeBadge(f)}</td><td>${num(f.s, 1)}</td><td>${f.rk}/${f.ct}</td>
          <td>${c(p.investor)}</td><td>${c(p.outflow)}</td><td>${c(p.anomaly)}</td><td>${c(p.founder)}</td><td>${c(p.drawdown)}</td>
          <td>${c(pen(f))}</td><td>${pctCell(f.r?.["1y"], 1)}</td><td>${pctCell(f.r?.["3y"], 1)}</td>
          <td>%${num(f.m?.vol, 1)}</td><td class="down">−%${num(f.m?.mdd, 1)}</td>
          <td class="left">${flagsOf(hit).map(([t, l]) => `<span class="${t === "danger" ? "warn-tag danger-tag" : t === "warn" ? "warn-tag" : "fx-tag"}">${esc(l)}</span>`).join(" ") || `<span class="dim">—</span>`}</td></tr>`;
      }).join("")}</tbody>` : `<tbody><tr><td class="empty">Değerlendirilecek fon yok</td></tr></tbody>`;
    const bad = list.filter((x) => flagsOf(x.hit).some(([t]) => t === "danger") || ["D"].includes(x.hit.f.g));
    app.querySelector("#dgWarn").innerHTML = bad.length ? `<div class="notice warn"><b>Dikkat:</b> ${bad.map((x) => `${esc(x.hit.f.c)} (${flagsOf(x.hit).map(([, l]) => l).join(", ") || "not " + x.hit.f.g})`).join("; ")}.
      Skor ve cezaların nasıl oluştuğunu görmek için fon koduna tıkla.</div>` : "";
  };

  const months = () => PERIODS.find(([k]) => k === st.period)[2];
  const drawChart = async () => {
    save(st);
    const total = st.rows.reduce((a, r) => a + (+r.w || 0), 0);
    app.querySelector("#dgSum").innerHTML = `Toplam: <b class="${Math.abs(total - 100) < 0.01 ? "" : "down"}">%${num(total, 0)}</b>${Math.abs(total - 100) < 0.01 ? "" : " (oranlar 100'e ölçeklenir)"}`;
    const mine = {}, kindOf = {};
    items().forEach(({ r, hit }) => { if (hit && +r.w > 0) { mine[hit.f.c] = (mine[hit.f.c] || 0) + +r.w; kindOf[hit.f.c] = hit.kind; } });
    const mdl = models(ctx);
    const need = new Map(Object.entries(kindOf));
    if (st.showNow) mdl.forEach((m) => m.basket.forEach((b) => need.set(b.c, b.kind)));
    const hists = Object.fromEntries(await Promise.all([...need].map(async ([c, k]) => [c, await fundHistory(c, k)])));
    const bench = await benchData();
    const lastDate = [...Object.values(hists).filter(Boolean).map((h) => h.d[h.d.length - 1]), bench?.d?.[bench.d.length - 1]].filter(Boolean).sort().pop();
    if (!lastDate) { app.querySelector("#dgChart").innerHTML = `<div class="empty">Fiyat verisi yok</div>`; return; }
    const endD = new Date(lastDate); endD.setMonth(endD.getMonth() - months());
    const from = endD.toISOString().slice(0, 10);
    const rw = st.rebal === "2m" ? 9 : st.rebal === "12m" ? 52 : 0;
    const my = Object.keys(mine).length ? basketSeries(mine, hists, from, rw) : null;
    const start = [from, my?.d[0]].filter(Boolean).sort().pop();
    const at = (s, d) => { let v = null; s.d.forEach((x, i) => { if (x <= d && s.v[i] != null) v = s.v[i]; }); return v; };

    const series = [];
    let mySer = null;
    if (my) { mySer = { key: "mine", name: "Benim dağılımım", ...rebaseFrom(my.d, my.v, start), color: "#db2777" }; series.push(mySer); }
    for (const m of mdl) {
      const [, label, color] = MODELS.find(([k]) => k === m.key);
      if (m.bt?.available) {
        const r = rebaseFrom(m.bt.dates, m.bt.series.model, start);
        if (r) {
          const anchor = mySer ? at(mySer, r.d[0]) : 100;
          series.push({ key: m.key, name: `${label} (${dateTR(r.d[0])}'den)`, d: r.d, v: r.v.map((x) => (x == null ? null : (x / 100) * (anchor || 100))), color });
        }
      }
      if (st.showNow) {
        const w = Object.fromEntries(m.basket.map((b) => [b.c, b.w]));
        const s = basketSeries(w, hists, start, rw);
        const r = s && rebaseFrom(s.d, s.v, s.d[0]);
        if (r) {
          const anchor = mySer ? at(mySer, r.d[0]) : 100;
          series.push({ key: `${m.key}-now`, name: `${label} · bugünkü sepet (geriye dönük)`, d: r.d, v: r.v.map((x) => (x / 100) * (anchor || 100)), color, dashed: true });
        }
      }
    }
    if (bench) {
      for (const [k, label, color] of [["gold", "Gram altın", "var(--c7, #ca8a04)"], ["tufe", "TÜFE", "var(--c2)"], ["usd", "Dolar/TL", "var(--c4)"], ["ppf", "PPF ortalaması", "var(--c6)"]]) {
        const sr = bench.s[k];
        const r = sr && rebaseFrom(bench.d, sr.v, start);
        if (r) series.push({ key: k, name: label, ...r, color, dashed: k === "ppf" });
      }
    }
    lineChart(app.querySelector("#dgChart"), series, { base: 100, height: 340, format: (v) => num(v, 0) });
    app.querySelector("#dgNote").textContent = `${dateTR(start)} – ${dateTR(lastDate)} · başlangıç = 100 · ${st.rebal === "hold" ? "al ve tut" : st.rebal === "12m" ? "yılda bir yeniden dengeleme" : "2 ayda bir yeniden dengeleme"}.`
      + (my && my.d[0] > from ? ` Dağılımındaki en genç fonun verisi ${dateTR(my.d[0])}'de başladığı için karşılaştırma oradan başlıyor.` : "")
      + " Modellerin çizgisi, gerçek geçmişlerinin başladığı tarihte senin dağılımınla aynı noktadan çizilir; tablo her satırı kendi başlangıcından ve aynı dönemdeki senin getirinle verir.";

    const rows = series.map((s) => {
      const stt = weeklyStats(s);
      if (!stt) return "";
      const mineSame = mySer && s.key !== "mine" ? weeklyStats(rebaseFrom(mySer.d, mySer.v, stt.from) || mySer) : null;
      const diff = mineSame ? mineSame.total - stt.total : null;
      return `<tr class="${s.key === "mine" ? "is-self" : ""}"><td class="left">${esc(s.name)}</td><td>${dateTR(stt.from)}</td>
        <td class="${stt.total >= 0 ? "up" : "down"}"><b>${pct(stt.total, 1)}</b></td><td>${pct(stt.cagr, 1)}</td><td class="down">${pct(stt.mdd, 1)}</td>
        <td>%${num(stt.vol, 1)}</td><td>${mineSame ? pct(mineSame.total, 1) : "—"}</td>
        <td class="${diff == null ? "" : diff >= 0 ? "up" : "down"}">${diff == null ? "—" : (diff >= 0 ? "+" : "") + num(diff, 1) + " puan"}</td></tr>`;
    }).join("");
    app.querySelector("#dgStats").innerHTML = `<thead><tr><th class="left">Sepet / varlık</th><th>Başlangıç</th><th>Toplam</th><th>Yıllık</th><th>Maks. düşüş</th>
      <th>Oynaklık</th><th>Benim dağılımım (aynı dönem)</th><th>Benim farkım</th></tr></thead><tbody>${rows}</tbody>`;
  };

  const redraw = () => { drawRows(); drawEval(); drawChart(); };
  rowsEl.addEventListener("change", (e) => {
    const i = +e.target.dataset.i;
    if (e.target.classList.contains("cmp-code")) st.rows[i].c = e.target.value.toUpperCase().trim();
    if (e.target.classList.contains("cmp-w")) st.rows[i].w = parseFloat(e.target.value) || 0;
    redraw();
  });
  rowsEl.addEventListener("click", (e) => {
    const b = e.target.closest(".cmp-del");
    if (!b) return;
    st.rows.splice(+b.dataset.i, 1);
    if (!st.rows.length) st.rows.push({ c: "", w: 100 });
    redraw();
  });
  app.querySelector("#dgAdd").addEventListener("click", () => {
    if (st.rows.length >= 15) return;
    st.rows.push({ c: "", w: 0 });
    drawRows();
  });
  app.querySelector("#dgRebal").addEventListener("change", (e) => { st.rebal = e.target.value; drawChart(); });
  app.querySelector("#dgNow").addEventListener("change", (e) => { st.showNow = e.target.checked; drawChart(); });
  app.querySelector("#dgPeriod").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    st.period = b.dataset.p;
    app.querySelectorAll("#dgPeriod button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    drawChart();
  });
  redraw();
}
