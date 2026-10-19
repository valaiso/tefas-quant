import { esc, num, pct, pctCell, money, dateTR, gradeBadge, scoreBar, SIGNALS, trUpper, debounce } from "../util.js";
import { lineChart } from "../chart.js";
import { startIndex, windowed, windowStats, statRow } from "./simulation.js";
import { besHistory, benchData, basketSeries, rebaseFrom, weeklyStats } from "../portfolio.js";
import * as fund from "./fund.js";

const PAGE = 50;
const TEFAS = (c) => `https://www.tefas.gov.tr/FonAnaliz.aspx?FonKod=${encodeURIComponent(c)}`;
const chip = (c) => `<a class="code-chip" href="#/bes/${encodeURIComponent(c)}" title="Fon detayı">${esc(c)}</a>`;
const ACCESS = {
  DK: "Devlet katkısı fonu: katkı payı otomatik yatırılır, serbestçe seçilemez",
  OKS: "Otomatik katılım (OKS) fonu: yalnızca işveren üzerinden otomatik katılım sözleşmesinde",
  GRUP: "Grup emeklilik fonu: yalnızca işverenin grup sözleşmesiyle",
};
const COLORS = { model: "var(--brand-3)", universe: "var(--text-dim)", gold: "var(--c7, #ca8a04)", usd: "var(--c4)", tufe: "var(--c2)", ppf: "var(--c6)" };
const LABELS = { gold: "Gram altın", usd: "Dolar/TL", tufe: "TÜFE", ppf: "PPF ortalaması (yatırım fonu)" };
const SLICE = ["#0f766e", "#2563eb", "#ca8a04", "#7c3aed", "#db2777", "#0891b2"];
const PERIODS = [["1y", "1Y", 12], ["2y", "2Y", 24], ["3y", "3Y", 36], ["5y", "5Y", 60], ["all", "Tümü", null]];
const COLUMNS = [
  { key: "rk", label: "Sıra", get: (f) => f.rk },
  { key: "c", label: "Fon", get: (f) => f.c, left: true },
  { key: "co", label: "Şirket", get: (f) => f.co, left: true },
  { key: "k", label: "Kategori", get: (f) => f.k, left: true },
  { key: "g", label: "Not", get: (f) => f.s },
  { key: "s", label: "Skor", get: (f) => f.s },
  { key: "r1a", label: "1 Ay", get: (f) => f.r["1a"] },
  { key: "r1y", label: "1 Yıl", get: (f) => f.r["1y"] },
  { key: "r3y", label: "3 Yıl", get: (f) => f.r["3y"] },
  { key: "r5y", label: "5 Yıl", get: (f) => f.r["5y"] },
  { key: "vol", label: "Volatilite", get: (f) => f.m.vol },
  { key: "inv", label: "Katılımcı", get: (f) => f.inv },
  { key: "aum", label: "Büyüklük", get: (f) => f.aum },
];
const state = { tab: "siralama", q: "", co: "", cat: "", sig: "", ax: "open", sort: "s", dir: -1, page: 0, company: null, period: "all", month: {} };
let cacheFunds = null, cacheModel = null;

const get = async (p) => {
  const r = await fetch(`${p}?v=${Date.now().toString(36).slice(0, -3)}`);
  if (!r.ok) throw new Error(`${p}: ${r.status}`);
  return r.json();
};

function badges(f) {
  let out = "";
  out += f.bf
    ? `<span class="ax-tag" title="BEFAS'tan alınamaz (${esc(f.bf)}); yalnızca ${esc(f.co)} sözleşmesiyle">ŞİRKET İÇİ</span>`
    : `<span class="ch-tag" title="BEFAS'a açık: hangi emeklilik şirketinde olursan ol, kendi şirketinin uygulamasından alabilirsin">BEFAS</span>`;
  if (f.ax) out += `<span class="ax-tag" title="${esc(ACCESS[f.ax] || "")}">${esc(f.ax)}</span>`;
  if (f.fx) out += `<span class="fx-tag" title="Yabancı / döviz ağırlıklı (ünvandan)">YABANCI</span>`;
  if (f.tk) out += `<span class="fx-tag" title="Teknoloji sektörü fonu (yerli ya da yabancı; ünvandan)">TEKNOLOJİ</span>`;
  return out;
}

let cacheCats = null;

/** Fon detay sayfası (fund.js) için BES verisiyle kurulmuş store. */
async function besStore(main) {
  if (!cacheCats) cacheCats = await get("data/bes_categories.json").catch(() => ({}));
  const { meta, funds } = cacheFunds;
  return {
    meta: { ...main.meta, ...meta, config: main.meta.config },
    funds, byCode: new Map(funds.map((f) => [f.c, f])), categories: cacheCats,
    history: (c) => besHistory(c), benchmarks: () => main.benchmarks(),
  };
}

export async function render(app, route, main) {
  app.innerHTML = `<div class="loading"><div class="spinner"></div><p>BES fonları yükleniyor…</p></div>`;
  if (route.params.has("tab")) state.tab = route.params.get("tab");
  if (!cacheFunds) cacheFunds = await get("data/bes.json").catch(() => null);
  if (cacheFunds && route.arg) {
    document.getElementById("pageTitle").textContent = route.arg;
    await fund.render(app, route, await besStore(main), { base: "#/bes/", bes: true });
    return;
  }
  if (!cacheFunds) {
    app.innerHTML = `<div class="card empty"><h3>BES verisi henüz hazır değil</h3><p>Emeklilik fonlarının geçmişi ilk çalışmalarda dolduruluyor.</p></div>`;
    return;
  }
  const { meta, funds } = cacheFunds;

  app.innerHTML = `
  <section class="method-intro card">
    <h2>Bireysel Emeklilik (BES) <span class="model-tag">${num(meta.fundCount, 0)} fon</span></h2>
    <p>Tüm emeklilik yatırım fonları, yatırım fonlarıyla aynı kurallarla <b>kendi kategorisi içinde</b> puanlanır ve A+…D notu alır.
      <b>BEFAS</b> sayesinde başka şirketlerin fonlarını da kendi sözleşmenden alabilirsin: <b>BEFAS</b> etiketli fonlar her şirketten,
      <b>ŞİRKET İÇİ</b> etiketli fonlar (grup, "yabancı" ibareli, para piyasası, katkı, başlangıç) yalnızca kendi şirketinin sözleşmesiyle alınır. Birikim döneminde fon getirisinden stopaj kesilmez ve fon işletim gideri fiyata yansır; gösterilen getiriler
      bu yüzden ücret sonrası ve vergi öncesidir.</p>
    <p class="dim">Son fiyat: ${dateTR(meta.lastDataDate)} · Veri penceresi: ${dateTR(meta.firstDataDate)} – ${dateTR(meta.lastDataDate)}</p>
  </section>
  <div class="seg seg-lg" id="besTabs">
    <button data-t="siralama" aria-pressed="${state.tab === "siralama"}">Sıralama</button>
    <button data-t="model" aria-pressed="${state.tab === "model"}">Model</button>
  </div>
  <div id="besBody"></div>`;

  const body = app.querySelector("#besBody");
  const show = async () => {
    if (state.tab === "model") await renderModel(body);
    else renderRanking(body, funds);
  };
  app.querySelector("#besTabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-t]");
    if (!b) return;
    state.tab = b.dataset.t;
    app.querySelectorAll("#besTabs button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    show();
  });
  await show();
}

function renderRanking(body, funds) {
  const companies = [...new Set(funds.map((f) => f.co))].sort((a, b) => a.localeCompare(b, "tr"));
  const cats = [...new Set(funds.map((f) => f.k))].sort((a, b) => a.localeCompare(b, "tr"));
  body.innerHTML = `
  <section class="card">
    <div class="card-head"><h2>Not dağılımı</h2><span class="sub" id="distSub"></span></div>
    <div class="dist-bar" id="distBar"></div>
    <div class="dist-legend" id="distLegend"></div>
  </section>
  <section class="card filters">
    <div class="filter-grid">
      <label class="field"><span>Ara</span><input id="bq" type="search" placeholder="Kod veya ünvan" value="${esc(state.q)}"></label>
      <label class="field"><span>Emeklilik şirketi</span><select id="bco"><option value="">Tüm şirketler</option>
        ${companies.map((c) => `<option ${c === state.co ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>
      <label class="field"><span>Kategori</span><select id="bcat"><option value="">Tüm kategoriler</option>
        ${cats.map((c) => `<option ${c === state.cat ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>
      <label class="field"><span>Not</span><select id="bsig"><option value="">Tüm notlar</option>
        ${SIGNALS.map((s) => `<option value="${s.key}" ${s.key === state.sig ? "selected" : ""}>${s.grade} · ${s.key}</option>`).join("")}</select></label>
      <label class="field"><span>Erişim</span><select id="bax">
        <option value="open" ${state.ax === "open" ? "selected" : ""}>Serbestçe seçilebilenler</option>
        <option value="" ${state.ax === "" ? "selected" : ""}>Tümü (DK, OKS, grup dahil)</option></select></label>
    </div>
  </section>
  <section class="card">
    <div class="card-head"><h2 id="bcount">—</h2><span class="sub">Kod TEFAS sayfasını açar · BEFAS: her şirketten alınabilir · ŞİRKET İÇİ: yalnızca kendi şirketinin sözleşmesiyle · DK / OKS / GRUP: serbestçe seçilemez</span></div>
    <div class="table-wrap"><table class="ranking">
      <thead><tr>${COLUMNS.map((c) => `<th class="sortable ${c.left ? "left" : ""}" data-key="${c.key}">${c.label}<span class="sort-ind"></span></th>`).join("")}</tr></thead>
      <tbody id="bbody"></tbody>
    </table></div>
    <div class="pagination" id="bpager"></div>
  </section>`;

  const tbody = body.querySelector("#bbody");
  const draw = () => {
    const q = trUpper(state.q.trim());
    const base = funds.filter((f) => (!state.ax || !f.ax) && (!state.co || f.co === state.co) && (!state.cat || f.k === state.cat)
      && (!q || f.c.includes(q) || trUpper(f.n).includes(q)));
    // Not dağılımı: filtrelenmiş evren (not filtresi hariç)
    const counts = Object.fromEntries(SIGNALS.map((s) => [s.key, 0]));
    base.forEach((f) => { counts[f.sig] = (counts[f.sig] || 0) + 1; });
    const total = base.length || 1;
    body.querySelector("#distSub").textContent = `${state.co || "Tüm şirketler"}${state.cat ? " · " + state.cat : ""} · ${num(base.length, 0)} fon`;
    body.querySelector("#distBar").innerHTML = SIGNALS.map((s) => `<span class="${s.cls}" style="flex:${counts[s.key] || 0.0001}" title="${s.key}: ${counts[s.key]}"></span>`).join("");
    body.querySelector("#distLegend").innerHTML = SIGNALS.map((s) => `<button class="dist-item" data-sig="${esc(s.key)}" aria-pressed="${state.sig === s.key}">
      <span class="grade ${s.cls}">${s.grade}</span><span>${s.key}</span><b class="num">${num(counts[s.key], 0)}</b>
      <span class="dim num">%${num((counts[s.key] / total) * 100, 0)}</span></button>`).join("");

    const rows = base.filter((f) => !state.sig || f.sig === state.sig);
    const col = COLUMNS.find((c) => c.key === state.sort);
    rows.sort((a, b) => {
      const x = col.get(a), y = col.get(b);
      if (x == null) return 1;
      if (y == null) return -1;
      return (typeof x === "string" ? x.localeCompare(y, "tr") : x - y) * state.dir;
    });
    const pages = Math.max(1, Math.ceil(rows.length / PAGE));
    state.page = Math.min(state.page, pages - 1);
    body.querySelector("#bcount").textContent = `${num(rows.length, 0)} BES fonu`;
    tbody.innerHTML = rows.slice(state.page * PAGE, state.page * PAGE + PAGE).map((f) => `<tr>
        <td class="num"><b>${f.rk}</b><span class="dim">/${f.ct}</span></td>
        <td class="fund-cell left">${chip(f.c)}${badges(f)}<span class="name">${esc(f.n)}</span></td>
        <td class="left dim">${esc(f.co)}</td>
        <td class="left dim cat-cell">${esc(f.k)}</td>
        <td>${gradeBadge(f)}</td>
        <td class="score-cell">${scoreBar(f.s)}</td>
        <td>${pctCell(f.r["1a"])}</td><td>${pctCell(f.r["1y"])}</td><td>${pctCell(f.r["3y"])}</td><td>${pctCell(f.r["5y"])}</td>
        <td>%${num(f.m.vol, 1)}</td><td>${num(f.inv, 0)}</td><td>${money(f.aum)}</td>
      </tr>`).join("") || `<tr><td colspan="${COLUMNS.length}" class="empty">Filtreye uyan fon yok</td></tr>`;
    body.querySelectorAll("th.sortable").forEach((th) => {
      th.querySelector(".sort-ind").textContent = th.dataset.key === state.sort ? (state.dir < 0 ? " ↓" : " ↑") : "";
    });
    body.querySelector("#bpager").innerHTML = `<span class="dim">Sayfa ${state.page + 1} / ${pages}</span>
      <div class="pagination-controls">
        <button class="btn btn-sm" data-page="-1" ${state.page === 0 ? "disabled" : ""}>← Önceki</button>
        <button class="btn btn-sm" data-page="1" ${state.page >= pages - 1 ? "disabled" : ""}>Sonraki →</button>
      </div>`;
  };
  const on = (id, ev, fn) => body.querySelector(id).addEventListener(ev, fn);
  on("#bq", "input", debounce((e) => { state.q = e.target.value; state.page = 0; draw(); }, 150));
  on("#bco", "change", (e) => { state.co = e.target.value; state.page = 0; draw(); });
  on("#bcat", "change", (e) => { state.cat = e.target.value; state.page = 0; draw(); });
  on("#bsig", "change", (e) => { state.sig = e.target.value; state.page = 0; draw(); });
  on("#bax", "change", (e) => { state.ax = e.target.value; state.page = 0; draw(); });
  on("#distLegend", "click", (e) => {
    const b = e.target.closest("[data-sig]");
    if (!b) return;
    state.sig = state.sig === b.dataset.sig ? "" : b.dataset.sig;
    body.querySelector("#bsig").value = state.sig;
    state.page = 0;
    draw();
  });
  body.querySelectorAll("th.sortable").forEach((th) => th.addEventListener("click", () => {
    const key = th.dataset.key;
    state.dir = state.sort === key ? -state.dir : (["rk", "c", "co", "k", "vol"].includes(key) ? 1 : -1);
    state.sort = key;
    draw();
  }));
  on("#bpager", "click", (e) => {
    const b = e.target.closest("[data-page]");
    if (b) { state.page += +b.dataset.page; draw(); }
  });
  draw();
}

// ------------------------------------------------------------------ karşılaştırma
// Kullanıcının kendi BES dağılımı ile BEFAS modelini haftalık fiyatlardan karşılaştırır.
const CMP_KEY = "tq_bes_compare";
const CMP_PERIODS = [["1y", "1Y", 12], ["2y", "2Y", 24], ["3y", "3Y", 36], ["5y", "5Y", 60]];

function loadCmp() {
  try {
    const v = JSON.parse(localStorage.getItem(CMP_KEY) || "null");
    if (v && Array.isArray(v.rows)) return v;
  } catch { /* depolama kapalı olabilir */ }
  return { rows: [{ c: "CFA", w: 50 }, { c: "YZD", w: 50 }], rebal: "2m", period: "5y" };
}
function saveCmp(v) {
  try { localStorage.setItem(CMP_KEY, JSON.stringify(v)); } catch { /* yok say */ }
}
function comparatorHtml(cmp, funds) {
  const opts = funds.map((f) => `<option value="${esc(f.c)}">${esc(f.c)} · ${esc(f.co)} · ${esc(f.n.replace(/^.*?A\.Ş\.\s*/, "").slice(0, 60))}</option>`).join("");
  return `<section class="card">
    <div class="card-head"><h2>Kendi BES dağılımını modelle karşılaştır</h2>
      <div class="seg" id="cmpPeriod">${CMP_PERIODS.map(([k, l]) => `<button data-p="${k}" aria-pressed="${k === cmp.period}">${l}</button>`).join("")}</div></div>
    <p class="dim">Kendi fonlarını ve yüzdelerini gir; dağılımın, BEFAS modelinin bugünkü sepeti ve modelin gerçek (her dönem o günkü veriyle kurulan) geçmişiyle
      aynı tarihlerde karşılaştırılır. Fiyatlar haftalık, 5 yıla kadar. Girdiğin dağılım yalnızca bu tarayıcıda saklanır.</p>
    <datalist id="besCodes">${opts}</datalist>
    <div class="cmp-rows" id="cmpRows"></div>
    <div class="btn-row cmp-actions">
      <button class="btn btn-sm" id="cmpAdd" type="button">+ Fon ekle</button>
      <label class="field inline"><span>Yeniden dengeleme</span><select id="cmpRebal">
        <option value="2m" ${cmp.rebal === "2m" ? "selected" : ""}>2 ayda bir hedef yüzdelere dön</option>
        <option value="12m" ${cmp.rebal === "12m" ? "selected" : ""}>Yılda bir</option>
        <option value="hold" ${cmp.rebal === "hold" ? "selected" : ""}>Hiç (al ve tut)</option></select></label>
      <span class="dim" id="cmpSum"></span>
    </div>
    <div class="chart" id="cmpChart"></div>
    <p class="chart-note dim" id="cmpNote"></p>
    <div class="table-wrap"><table id="cmpStats"></table></div>
  </section>`;
}

function bindComparator(body, m, funds) {
  const cmp = loadCmp();
  const byCode = new Map(funds.map((f) => [f.c, f]));
  const B = m.befas;
  const rowsEl = body.querySelector("#cmpRows");
  const drawRows = () => {
    rowsEl.innerHTML = cmp.rows.map((r, i) => {
      const f = byCode.get((r.c || "").toUpperCase());
      return `<div class="cmp-row">
        <input class="cmp-code" data-i="${i}" list="besCodes" value="${esc(r.c)}" placeholder="Fon kodu" maxlength="3">
        <input class="cmp-w" data-i="${i}" type="number" min="0" max="100" step="5" value="${r.w}"><span>%</span>
        <span class="cmp-name ${f ? "" : "down"}">${f ? `${esc(f.co)} · ${esc(f.k)}${f.bf ? ` · <span class="ax-tag">ŞİRKET İÇİ</span>` : ""}` : r.c ? "Kod bulunamadı" : ""}</span>
        <button class="btn btn-sm cmp-del" data-i="${i}" type="button" title="Kaldır">✕</button></div>`;
    }).join("");
  };
  const months = () => CMP_PERIODS.find(([k]) => k === cmp.period)[2];
  const draw = async () => {
    saveCmp(cmp);
    const total = cmp.rows.reduce((a, r) => a + (+r.w || 0), 0);
    body.querySelector("#cmpSum").innerHTML = `Toplam: <b class="${Math.abs(total - 100) < 0.01 ? "" : "down"}">%${num(total, 0)}</b>${Math.abs(total - 100) < 0.01 ? "" : " (oranlar 100'e ölçeklenir)"}`;
    const mine = {};
    cmp.rows.forEach((r) => { const c = (r.c || "").toUpperCase(); if (byCode.has(c) && +r.w > 0) mine[c] = (mine[c] || 0) + +r.w; });
    const modelW = Object.fromEntries((B?.basket || []).map((b) => [b.c, b.w]));
    const codes = [...new Set([...Object.keys(mine), ...Object.keys(modelW)])];
    const hists = Object.fromEntries(await Promise.all(codes.map(async (c) => [c, await besHistory(c)])));
    const bench = await benchData();
    const lastDate = Object.values(hists).filter(Boolean).map((h) => h.d[h.d.length - 1]).sort().pop();
    if (!lastDate) { body.querySelector("#cmpChart").innerHTML = `<div class="empty">Fiyat verisi yok</div>`; return; }
    const end = new Date(lastDate); end.setMonth(end.getMonth() - months());
    const from = end.toISOString().slice(0, 10);
    const rw = cmp.rebal === "2m" ? 9 : cmp.rebal === "12m" ? 52 : 0;

    const my = Object.keys(mine).length ? basketSeries(mine, hists, from, rw) : null;
    const mdl = basketSeries(modelW, hists, from, rw);
    const start = [from, my?.d[0], mdl?.d[0]].filter(Boolean).sort().pop();
    const at = (s, d) => { let v = null; s.d.forEach((x, i) => { if (x <= d && s.v[i] != null) v = s.v[i]; }); return v; };
    const series = [];
    if (my) series.push({ key: "mine", name: "Benim dağılımım", ...rebaseFrom(my.d, my.v, start), color: "#db2777" });
    if (mdl) series.push({ key: "now", name: "BEFAS modeli · bugünkü sepet (geriye dönük)", ...rebaseFrom(mdl.d, mdl.v, start), color: "var(--brand-3)", dashed: true });
    if (bench) {
      for (const [k, label, color] of [["gold", "Gram altın", "var(--c7, #ca8a04)"], ["tufe", "TÜFE", "var(--c2)"], ["usd", "Dolar/TL", "var(--c4)"]]) {
        const sr = bench.s[k];
        const r = sr && rebaseFrom(bench.d, sr.v, start);
        if (r) series.push({ key: k, name: label, ...r, color });
      }
    }
    // Gerçek model geçmişi: kendi başladığı tarihte "benim dağılımım" ile aynı noktadan çizilir
    let real = null;
    if (B?.backtest.available) {
      const r = rebaseFrom(B.backtest.dates, B.backtest.series.model, start);
      if (r) {
        const anchor = series[0] ? at(series[0], r.d[0]) : 100;
        real = { key: "real", name: `BEFAS modeli · gerçek geçmiş (${dateTR(r.d[0])}'den)`, d: r.d, v: r.v.map((x) => (x == null ? null : (x / 100) * (anchor || 100))),
          color: "var(--brand-3)" };
        series.splice(2, 0, real);
      }
    }
    lineChart(body.querySelector("#cmpChart"), series, { base: 100, height: 320, format: (v) => num(v, 0) });
    const firsts = [my && ["dağılımındaki fonlar", my.d[0]], mdl && ["model sepetindeki fonlar", mdl.d[0]]].filter(Boolean);
    const late = start > from ? ` Seçilen dönemin başında ${firsts.filter(([, d]) => d >= start).map(([n]) => n).join(" ve ")} için veri olmadığından karşılaştırma ${dateTR(start)}'den başlıyor.` : "";
    body.querySelector("#cmpNote").textContent = `${dateTR(start)} – ${dateTR(lastDate)} · başlangıç = 100 · ${cmp.rebal === "hold" ? "al ve tut" : cmp.rebal === "12m" ? "yılda bir yeniden dengeleme" : "2 ayda bir yeniden dengeleme"}.${late}`
      + " Bugünkü sepet geriye dönük gösterimdir (o tarihte bilinmiyordu); gerçek geçmiş, modelin her dönem yalnızca o günkü veriyle kurduğu sepetlerdir.";

    const row = (s, from2) => {
      const r = from2 ? rebaseFrom(s.d, s.v, from2) : s;
      const st = r && weeklyStats(r);
      return st ? `<tr class="${s.key === "mine" ? "is-self" : ""}"><td class="left">${esc(s.name)}</td>
        <td class="${st.total >= 0 ? "up" : "down"}"><b>${pct(st.total, 1)}</b></td><td>${pct(st.cagr, 1)}</td><td class="down">${pct(st.mdd, 1)}</td>
        <td>%${num(st.vol, 1)}</td></tr>` : "";
    };
    const head = (t) => `<tr class="group-row"><td class="left" colspan="5"><b>${t}</b></td></tr>`;
    let html = `<thead><tr><th class="left">Sepet / varlık</th><th>Toplam</th><th>Yıllık</th><th>Maks. düşüş</th><th>Oynaklık</th></tr></thead><tbody>`
      + head(`Seçilen dönem: ${dateTR(start)} – ${dateTR(lastDate)}`) + series.filter((s) => s.key !== "real").map((s) => row(s)).join("");
    if (real) {
      const r0 = real.d[0];
      const uni = B.backtest.series.universe ? { key: "uni", name: "BEFAS evreni (uygun tüm fonlar, eşit)", d: B.backtest.dates, v: B.backtest.series.universe } : null;
      html += head(`Modelin gerçek geçmiş dönemi: ${dateTR(r0)} – ${dateTR(lastDate)}`)
        + [series.find((s) => s.key === "mine"), real, uni, ...series.filter((s) => ["gold", "tufe", "usd"].includes(s.key))]
          .filter(Boolean).map((s) => row(s, r0)).join("");
    }
    body.querySelector("#cmpStats").innerHTML = html + "</tbody>";
  };
  const sync = (e) => {
    const i = +e.target.dataset.i;
    if (e.target.classList.contains("cmp-code")) cmp.rows[i].c = e.target.value.toUpperCase().trim();
    if (e.target.classList.contains("cmp-w")) cmp.rows[i].w = parseFloat(e.target.value) || 0;
  };
  rowsEl.addEventListener("change", (e) => { sync(e); drawRows(); draw(); });
  rowsEl.addEventListener("click", (e) => {
    const b = e.target.closest(".cmp-del");
    if (!b) return;
    cmp.rows.splice(+b.dataset.i, 1);
    if (!cmp.rows.length) cmp.rows.push({ c: "", w: 100 });
    drawRows(); draw();
  });
  body.querySelector("#cmpAdd").addEventListener("click", () => {
    if (cmp.rows.length >= 10) return;
    cmp.rows.push({ c: "", w: 0 });
    drawRows();
  });
  body.querySelector("#cmpRebal").addEventListener("change", (e) => { cmp.rebal = e.target.value; draw(); });
  body.querySelector("#cmpPeriod").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    cmp.period = b.dataset.p;
    body.querySelectorAll("#cmpPeriod button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    draw();
  });
  drawRows();
  draw();
}

// ------------------------------------------------------------------ model
// Yıllık bileşik getiriden birikimli getiri (%)
const cum = (c, yrs) => (c == null || !isFinite(c) ? null : (Math.pow(1 + c / 100, yrs) - 1) * 100);
const wsum = (basket, f) => {
  const xs = basket.map((b) => [b.w, f(b)]).filter(([, v]) => v != null);
  const tw = xs.reduce((s, [w]) => s + w, 0);
  return tw ? xs.reduce((s, [w, v]) => s + w * v, 0) / tw : null;
};

function basketHtml(p, idp) {
  const bt = p.backtest;
  const months = p.history.map((h) => h.date);
  const bar = p.basket.map((b, i) => `<span style="width:${b.w}%;background:${SLICE[i % SLICE.length]}">${esc(b.c)} %${b.w}</span>`).join("");
  const tags = (b) => (b.fx ? `<span class="fx-tag">YABANCI</span>` : "") + (b.tk ? `<span class="fx-tag">TEKNOLOJİ</span>` : "")
    + (b.fill ? `<span class="ax-tag" title="3 yıllık getirisi TÜFE'yi geçen fon 3'ten az olduğu için TÜFE'ye en yakın fonla tamamlandı">TÜFE ALTI</span>` : "")
    + (b.bf ? `<span class="ax-tag" title="BEFAS'tan alınamaz (${esc(b.bf)})">ŞİRKET İÇİ</span>` : "");
  return `
    <div class="kpi-row">
      <div><span>Dönem başından</span><b class="${(p.sinceEntry ?? 0) >= 0 ? "up" : "down"}">${pct(p.sinceEntry, 2)}</b></div>
      <div><span>1 yıl</span><b>${pct(wsum(p.basket, (b) => b.r["1y"]), 1)}</b></div>
      <div><span>2 yıl</span><b>${pct(wsum(p.basket, (b) => cum(b.r2, 2)), 1)}</b></div>
      <div><span>3 yıl</span><b>${pct(wsum(p.basket, (b) => cum(b.r["3y"], 3)), 1)}</b></div>
      <div><span>Kuruluş</span><b>${dateTR(p.formed)}</b></div>
    </div>
    <div class="weight-bar">${bar}</div>
    <div class="table-wrap"><table class="model-table">
      <thead><tr><th class="left">Fon</th><th class="left">Şirket</th><th class="left">Varlık sınıfı</th><th>Ağırlık</th><th>Puan</th><th>Not</th>
        <th title="Son 1 yılın getirisi">1 yıl</th><th title="Son 2 yılın birikimli getirisi">2 yıl</th><th title="Son 3 yılın birikimli getirisi">3 yıl</th>
        <th title="12 aylık dönemlerin kaçında TÜFE'yi geçti">TÜFE'yi geçen 12A</th><th title="Son 1 yılda zirveden en büyük düşüş">Maks. düşüş (1 yıl)</th><th>Oynaklık</th><th class="left">Bugünkü durum</th></tr></thead>
      <tbody>${p.basket.map((b, i) => `<tr>
        <td class="left"><span class="mdl-swatch" style="background:${SLICE[i % SLICE.length]}"></span>${chip(b.c)}${tags(b)}
          <span class="fund-name">${esc(b.n)}</span></td>
        <td class="left dim">${esc(b.co || "—")}</td><td class="left dim">${esc(b.bk || b.k || "—")}</td><td><b class="weight">%${b.w}</b></td><td>${num(b.score, 0)}</td>
        <td>${esc(b.gNow || b.g || "—")}</td>
        <td>${pct(b.r["1y"], 1)}</td><td>${pct(cum(b.r2, 2), 1)}</td><td>${pct(cum(b.r["3y"], 3), 1)}</td>
        <td>%${num(b.realWin, 0)}</td><td class="down">${pct(b.mdd1 ?? b.mdd, 1)}</td><td>%${num(b.vol, 1)}</td>
        <td class="left">${b.warn ? `<span class="warn-tag">${esc(b.warn)}</span>` : `<span class="dim">—</span>`}</td></tr>`).join("")}</tbody>
    </table></div>
    ${bt.available ? `<div class="card-head sub-head"><h3>Geçmişte</h3>
        <div class="seg" id="${idp}Period">${PERIODS.map(([k, l]) => `<button data-p="${k}" aria-pressed="${k === state.period}">${l}</button>`).join("")}</div></div>
      <div class="chart" id="${idp}Chart"></div>
      <p class="chart-note dim" id="${idp}Range"></p>
      <div class="table-wrap"><table id="${idp}Stats"></table></div>` : ""}
    ${months.length ? `<div class="card-head sub-head"><h3>Geçmiş dönem dağılımları</h3>
        <select id="${idp}Month">${months.slice().reverse().map((d) => `<option value="${d}">${dateTR(d)}</option>`).join("")}</select></div>
      <div id="${idp}Hold"></div>` : ""}`;
}

function bindBasket(body, p, idp, label) {
  const bt = p.backtest;
  if (bt.available) {
    const keys = Object.keys(bt.series);
    const name = (k) => (k === "model" ? label : k === "universe" ? "BEFAS evreni (uygun tüm fonlar, eşit)" : LABELS[k] || k);
    const pm = () => PERIODS.find(([k]) => k === state.period)[2];
    const draw = () => {
      const i0 = startIndex(bt.dates, pm());
      const d = bt.dates.slice(i0);
      lineChart(body.querySelector(`#${idp}Chart`), keys.map((k) => ({ name: name(k), d, v: windowed(bt.series[k], i0),
        color: COLORS[k] || "var(--text-dim)", dashed: k === "ppf" || k === "universe" })), { base: 100, height: 300, format: (v) => num(v, 0) });
      body.querySelector(`#${idp}Range`).textContent = `${dateTR(d[0])} – ${dateTR(d[d.length - 1])} · dönem başı = 100 · 2 ayda bir yeniden kurulum (o gün bilinen veriyle, T+1 alış)`;
      body.querySelector(`#${idp}Stats`).innerHTML = `<thead><tr><th class="left">Sepet / varlık</th><th>Toplam</th><th>Yıllık</th><th>Maks. düşüş</th><th>Oynaklık</th>
        <th>En kötü / en iyi dönem</th><th>Pozitif dönem</th><th>—</th></tr></thead>
        <tbody>${keys.map((k, i) => statRow(name(k), windowStats(d, windowed(bt.series[k], i0), null), i === 0 ? "is-self" : "")).join("")}</tbody>`;
    };
    body.querySelector(`#${idp}Period`).addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      state.period = b.dataset.p;
      body.querySelectorAll(`#${idp}Period button`).forEach((x) => x.setAttribute("aria-pressed", x === b));
      draw();
    });
    draw();
  }
  const sel = body.querySelector(`#${idp}Month`);
  if (sel) {
    const hold = () => {
      const h = p.history.find((x) => x.date === sel.value);
      body.querySelector(`#${idp}Hold`).innerHTML = h.items.length
        ? `<div class="chip-cloud">${h.items.map(([c, w]) => `<span class="hold-chip">${chip(c)}<b>%${w}</b></span>`).join("")}</div>`
        : `<p class="dim">Bu dönem kurallara uyan fon yoktu; geçmiş testte uygun fonlar eşit ağırlıkla tutuldu.</p>`;
    };
    sel.addEventListener("change", hold);
    hold();
  }
}

async function renderModel(body) {
  body.innerHTML = `<div class="loading"><div class="spinner"></div><p>Model yükleniyor…</p></div>`;
  if (!cacheModel) cacheModel = await get("data/bes_model.json").catch(() => null);
  const m = cacheModel;
  if (!m || !m.befas) {
    body.innerHTML = `<div class="card empty"><h3>BES modeli için yeterli geçmiş yok</h3><p>Model 2 yıllık fiyat geçmişi istiyor; emeklilik fonlarının geçmişi doldukça açılacak.</p></div>`;
    return;
  }
  const R = m.rules;
  const P = m.profiles || { dengeli: m.befas };
  const pkeys = Object.keys(P).filter((k) => P[k]);
  if (!pkeys.includes(state.bprof)) state.bprof = pkeys.includes("dengeli") ? "dengeli" : pkeys[0];
  const B = P[state.bprof];
  const ust = B?.backtest.available ? B.backtest.stats : null;
  const ppfBeat = ust ? ust.model.total - ust.ppf.total : null;

  body.innerHTML = `
  <section class="card">
    <div class="card-head"><h2>Uzun vadeli BES modelleri (BEFAS)</h2><span class="sub">2 ayda bir · son kurulum ${B ? dateTR(B.formed) : "—"} · sonraki ${dateTR(m.nextRebalance)}</span></div>
    <div class="seg bes-prof" id="besProf">${pkeys.map((k) => `<button data-k="${k}" aria-pressed="${k === state.bprof}">${esc(P[k].label || k)}</button>`).join("")}</div>
    ${B?.desc ? `<p class="bes-prof-desc"><b>${esc(B.label)}:</b> ${esc(B.desc)}</p>` : ""}
    <p><b>BEFAS</b> (Takasbank'ın emeklilik fonu platformu, Temmuz 2021'den beri) sayesinde hangi emeklilik şirketinde olursan ol, kendi şirketinin
      uygulamasından <b>başka şirketlerin fonlarını</b> da alabilirsin. İstisnalar (EGM): grup fonları, unvanında "yabancı" ibaresi olan fonlar,
      para piyasası, katkı ve başlangıç fonları; bunlar yalnızca kendi şirketinin sözleşmesinde. Bu yüzden ana sepet, tüm şirketlerin
      <b>BEFAS'a açık</b> fonları arasından kurulur; herkes kendi sözleşmesinden uygulayabilir.</p>
    <p>5–10 yıllık birikim için: PPF benzeri faiz fonları alınmaz; 3 yılda enflasyonu (TÜFE) geçmiş, tek bir sıçramaya dayanmayan, notu ve risk bayrakları
      temiz fonlar seçilir. Sepet varlık sınıfı başına (altın, yerli hisse, teknoloji-yabancı, çok varlıklı) en fazla ${R.perCat} ve şirket başına en fazla
      ${R.perCompany} fon içerir; ağırlıklar <b>eşit</b> dağıtılır (tahmine dayalı ağırlıklar uzun vadede eşit ağırlığı genelde geçemez; DeMiguel, Garlappi ve Uppal, 2009).</p>
    ${B ? basketHtml(B, "bf") : `<p class="dim">BEFAS sepeti için yeterli fon yok.</p>`}
    ${ust ? `<div class="notice ${ppfBeat >= 0 ? "good" : ""}">${dateTR(B.backtest.dates[0])}'den bu yana ${esc(B.label)} modeli ${pct(ust.model.total, 1)} getirdi;
      PPF ortalaması (yatırım fonu) ${pct(ust.ppf?.total, 1)}, BEFAS'a açık tüm uygun fonların eşit sepeti ${pct(ust.universe?.total, 1)}, gram altın ${pct(ust.gold?.total, 1)},
      TÜFE ${pct(ust.tufe?.total, 1)}. PPF'ye göre ${ppfBeat >= 0 ? "önde" : "geride"}: ${num(Math.abs(ppfBeat), 1)} puan.
      Not: PPF burada vergisiz gösteriliyor; normal hesapta para piyasası fonu kazancından bugün %17,5 stopaj kesilir, BES'te birikim boyunca kesilmez ve devlet katkısı eklenir.
      2024–2026'daki çok yüksek faiz döneminde (PPF yılda %50–60) uzun vadeli fonların çoğu PPF'nin gerisinde kaldı; 2022–2023'te ise hisse ve altın PPF'yi çok geride bıraktı.</div>` : ""}
  </section>

  ${comparatorHtml(loadCmp(), cacheFunds.funds.filter((f) => !f.ax))}

  <section class="card">
    <div class="card-head"><h2>BES model kuralları ve vergi</h2></div>
    <ol class="rule-list">
      <li><b>Aday:</b> devlet katkısı, OKS ve grup fonları hariç; en az 3 yıl geçmiş, ≥${num(R.minAum / 1e6, 0)}m TL, ≥${num(R.minInvestors, 0)} katılımcı;
        kurulum günündeki notu ${R.okGrades.join(" / ")} ve getiri anomalisi, kuyruk riski, sıcak para ya da kurucu riski bayrağı yok.</li>
      <li><b>PPF benzeri fon yok:</b> ${R.excludedCategories.map(esc).join(", ")} kategorileri ve 1 yıllık oynaklığı %${num(R.minVol * 100, 0)}'ın altındaki fonlar alınmaz.</li>
      <li><b>Reel getiri şartı:</b> 3 yıllık yıllık getiri TÜFE'yi geçmiş olmalı. Şartı geçen fon 3'ten azsa sepet TÜFE'ye en yakın fonlarla tamamlanır (<b>TÜFE ALTI</b> etiketi).</li>
      <li><b>Sıçrama filtresi:</b> tek aya dayalı getiri, aşırı son 3 ay, tek günde aşırı hareket ya da 1 yılda %${num(R.max1y * 100, 0)}'ün üstü yükseliş alınmaz.</li>
      <li><b>Puan (sıralama için):</b> getiri ${R.weights.ret} (1Y %${R.retWindows["1y"] * 100}, 3Y %${R.retWindows["3y"] * 100}, 5Y %${R.retWindows["5y"] * 100}),
        reel istikrar ${R.weights.real} (12 aylık dönemlerde TÜFE'yi geçme oranı), Sharpe ${R.weights.sharpe}, 3 yıllık azami düşüş ${R.weights.mdd},
        TEFAS Quant skoru ${R.weights.quant}, katılımcı sayısı ${R.weights.inv}; önceki dönem sepette olan fona +${num(R.stayBonus, 0)}.</li>
      <li><b>Çeşitlendirme:</b> en fazla ${R.maxFunds} fon (alt sınır yok); varlık sınıfı başına en fazla ${R.perCat}, şirket başına en fazla ${R.perCompany} fon;
        haftalık getiri korelasyonu &gt; ${num(R.maxCorr, 2)} olan ikinci fon alınmaz.</li>
      <li><b>Vergi yerleşimi:</b> normal yatırım fonunda %17,5 stopajlı olan sınıflar (${(R.taxBuckets || []).map(esc).join(", ")}) BES'te birikim boyunca stopajsız
        büyüdüğü için +${num(R.taxTilt || 0, 0)} puan önceliklidir; yerli hisse yoğun fonlar normal fonda zaten %0 stopajlı olduğundan BES'te ek avantaj taşımaz.
        3 yıllık testte bu öncelik getiriyi artırdı, düşüşü değiştirmedi.</li>
      <li><b>Ağırlık:</b> eşit (1/N), her fon %${num(R.minW * 100, 0)}–%${num(R.maxW * 100, 0)}, 5'in katları. BES'te fon dağılımı yılda 12 kez değiştirilebilir; 2 aylık yenileme yılda 6 hak kullanır.</li>
      <li><b>Vergi:</b> birikim döneminde fon getirisinden stopaj kesilmez (yatırım fonunda altın, yabancı, değişken fonlarda %17,5). Çıkışta yalnızca getiriden:
        10 yıldan önce %15, 10 yılı dolduran ama 56 yaşını doldurmayan %10, emeklilik hakkıyla %5. Anapara ve devlet katkısı anaparası vergilenmez.</li>
      <li><b>Devlet katkısı (2026):</b> katkı payının %20'si, yıllık üst sınır brüt asgari ücretin %20'si (79.272 TL); hak ediş 3 yıl %15, 6 yıl %35, 10 yıl %60, emeklilikte %100.
        Devlet katkısı şirketin devlet katkısı fonlarında değerlenir; BEFAS'tan alınamaz.</li>
      <li><b>Vergi açısından yerleşim:</b> yatırım fonunda %0 stopajlı hisse yoğun fonlarla BES arasında birikim vergisi farkı yoktur; BES'in vergi avantajı en çok
        normal fonda %17,5 stopajlı altın, yabancı ve değişken fonlarda ortaya çıkar.</li>
    </ol>
  </section>`;

  if (B) bindBasket(body, B, "bf", `${B.label || "BEFAS"} BES modeli`);
  body.querySelector("#besProf")?.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || b.dataset.k === state.bprof) return;
    state.bprof = b.dataset.k;
    renderModel(body);
  });
  bindComparator(body, m, cacheFunds.funds);
}
