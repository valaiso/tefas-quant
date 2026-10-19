import { esc, num, pct, pctCell, money, dateTR, gradeBadge, scoreBar, SIGNALS, trUpper, debounce } from "../util.js";
import { lineChart } from "../chart.js";
import { startIndex, windowed, windowStats, statRow } from "./simulation.js";

const PAGE = 50;
const TEFAS = (c) => `https://www.tefas.gov.tr/FonAnaliz.aspx?FonKod=${encodeURIComponent(c)}`;
const chip = (c) => `<a class="code-chip" href="${TEFAS(c)}" target="_blank" rel="noopener" title="TEFAS'ta aç">${esc(c)}</a>`;
const ACCESS = {
  DK: "Devlet katkısı fonu: katkı payı otomatik yatırılır, serbestçe seçilemez",
  OKS: "Otomatik katılım (OKS) fonu: yalnızca işveren üzerinden otomatik katılım sözleşmesinde",
  GRUP: "Grup emeklilik fonu: yalnızca işverenin grup sözleşmesiyle",
};
const COLORS = { model: "var(--brand-3)", universe: "var(--text-dim)", gold: "var(--c7, #ca8a04)", usd: "var(--c4)", tufe: "var(--c2)", ppf: "var(--c6)" };
const LABELS = { gold: "Gram altın", usd: "Dolar/TL", tufe: "TÜFE", ppf: "PPF ortalaması (yatırım fonu)" };
const SLICE = ["#0f766e", "#2563eb", "#ca8a04", "#7c3aed", "#db2777", "#0891b2"];
const PERIODS = [["6a", "6A", 6], ["1y", "1Y", 12], ["2y", "2Y", 24], ["all", "Tümü", null]];
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

export async function render(app, route) {
  app.innerHTML = `<div class="loading"><div class="spinner"></div><p>BES fonları yükleniyor…</p></div>`;
  if (route.params.has("tab")) state.tab = route.params.get("tab");
  if (!cacheFunds) cacheFunds = await get("data/bes.json").catch(() => null);
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

// ------------------------------------------------------------------ vergi hesaplayıcı
// 2026 kuralları: devlet katkısı %20, yıllık üst sınır brüt asgari ücretin %20'si (79.272 TL);
// hak ediş 3 yıl %15, 6 yıl %35, 10 yıl %60, emeklilik %100; çıkışta getiriden %15 / %10 / %5.
const DK_RATE = 0.20, DK_CAP_2026 = 79272;
function vesting(years, ageEnd) {
  if (years >= 10 && ageEnd >= 56) return { vest: 1, tax: 0.05, label: "Emeklilik hakkıyla (10 yıl + 56 yaş)" };
  if (years >= 10) return { vest: 0.60, tax: 0.10, label: "10 yıl dolmuş, 56 yaş dolmamış" };
  if (years >= 6) return { vest: 0.35, tax: 0.15, label: "6-10 yıl arası ayrılış" };
  if (years >= 3) return { vest: 0.15, tax: 0.15, label: "3-6 yıl arası ayrılış" };
  return { vest: 0, tax: 0.15, label: "3 yıldan önce ayrılış" };
}
function simulate({ monthly, years, age, ret, dkRet, infl, fundTax }) {
  const rm = (1 + ret) ** (1 / 12) - 1, rd = (1 + dkRet) ** (1 / 12) - 1;
  let vb = 0, vd = 0, vy = 0, paid = 0, paidReal = 0, dkPaid = 0, c = monthly, t = 0;
  for (let y = 0; y < years; y++) {
    const cap = DK_CAP_2026 * (1 + infl) ** y;
    let dkYear = 0;
    for (let mth = 0; mth < 12; mth++) {
      const dk = Math.max(0, Math.min(c * DK_RATE, cap - dkYear));
      dkYear += dk; dkPaid += dk; paid += c; paidReal += c / (1 + infl) ** (t / 12); t++;
      vb = (vb + c) * (1 + rm); vy = (vy + c) * (1 + rm); vd = (vd + dk) * (1 + rd);
    }
    c *= 1 + infl;
  }
  const v = vesting(years, age + years);
  const gain = Math.max(0, vb - paid) + v.vest * Math.max(0, vd - dkPaid);
  const bes = vb + v.vest * vd - v.tax * gain;
  const fund = vy - fundTax * Math.max(0, vy - paid);
  const deflate = (1 + infl) ** years;
  return { v, paid, dkPaid, bes, fund, real: { bes: bes / deflate, fund: fund / deflate, paid: paidReal } };
}
const tl = (x) => `${num(x, 0)} ₺`;

function calculator(defaultRet) {
  return `<section class="card">
    <div class="card-head"><h2>BES mi, normal fon mu? Vergi ve devlet katkısı hesaplayıcı</h2><span class="sub">2026 kurallarıyla, aynı fon getirisini varsayarak</span></div>
    <div class="filter-grid calc-grid">
      <label class="field"><span>Aylık katkı (TL)</span><input id="cM" type="number" min="0" step="500" value="5000"></label>
      <label class="field"><span>Süre (yıl)</span><input id="cY" type="number" min="1" max="40" value="10"></label>
      <label class="field"><span>Başlangıç yaşı</span><input id="cA" type="number" min="18" max="75" value="35"></label>
      <label class="field"><span>Beklenen yıllık getiri (%)</span><input id="cR" type="number" step="1" value="${Math.round(defaultRet)}"></label>
      <label class="field"><span>Devlet katkısı fonu getirisi (%)</span><input id="cD" type="number" step="1" value="35"></label>
      <label class="field"><span>Yıllık enflasyon / katkı artışı (%)</span><input id="cI" type="number" step="1" value="25"></label>
      <label class="field"><span>Normal fonda stopaj</span><select id="cT"><option value="0.175">%17,5 (altın, yabancı, değişken…)</option>
        <option value="0">%0 (hisse senedi yoğun fon)</option></select></label>
    </div>
    <div id="calcOut"></div>
    <p class="dim small">Varsayımlar: katkı her yıl enflasyon kadar artar; devlet katkısı katkının %20'si, yıllık üst sınır 2026'da 79.272 TL ve enflasyonla büyür;
      devlet katkısı ayrı (devlet katkısı) fonda değerlenir; çıkışta yalnızca getiriden stopaj kesilir, anapara ve devlet katkısı anaparası vergilenmez;
      hak edilmeyen devlet katkısı geri alınır. Normal fonda stopaj satışta kazanç üzerinden alınır. Giriş aidatı ve yönetim gider kesintisi 0 kabul edildi.
      Mevzuat değişebilir; sonuç yaklaşık bir karşılaştırmadır.</p>
  </section>`;
}

function bindCalculator(body) {
  const val = (id) => parseFloat(body.querySelector(id).value) || 0;
  const draw = () => {
    const r = simulate({ monthly: val("#cM"), years: Math.max(1, Math.round(val("#cY"))), age: val("#cA"),
      ret: val("#cR") / 100, dkRet: val("#cD") / 100, infl: val("#cI") / 100, fundTax: parseFloat(body.querySelector("#cT").value) });
    const diff = r.bes - r.fund;
    body.querySelector("#calcOut").innerHTML = `
      <div class="kpi-row">
        <div><span>Ödenen toplam katkı</span><b>${tl(r.paid)}</b></div>
        <div><span>Devlet katkısı (yatan · hak edilen)</span><b>${tl(r.dkPaid)} · %${num(r.v.vest * 100, 0)}</b></div>
        <div><span>BES net (vergi sonrası)</span><b class="up">${tl(r.bes)}</b></div>
        <div><span>Normal fon net</span><b>${tl(r.fund)}</b></div>
        <div><span>BES farkı</span><b class="${diff >= 0 ? "up" : "down"}">${diff >= 0 ? "+" : ""}${tl(diff)}</b></div>
      </div>
      <p>${esc(r.v.label)}: çıkışta getiriden <b>%${num(r.v.tax * 100, 0)}</b> stopaj, devlet katkısının <b>%${num(r.v.vest * 100, 0)}</b>'i hak edilir.
        Bugünün parasıyla (enflasyondan arındırılmış): BES <b>${tl(r.real.bes)}</b>, normal fon <b>${tl(r.real.fund)}</b>, ödenen katkı ${tl(r.real.paid)}.
        ${diff >= 0 ? "BES'in avantajı devlet katkısı ve düşük çıkış vergisinden geliyor." : "Bu senaryoda erken çıkış ve hak edilmeyen devlet katkısı BES'i dezavantajlı yapıyor."}</p>`;
  };
  body.querySelectorAll(".calc-grid input, .calc-grid select").forEach((el) => el.addEventListener("input", draw));
  draw();
}

// ------------------------------------------------------------------ model
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
      <div><span>1Y</span><b>${pct(p.portfolio["1y"], 1)}</b></div>
      <div><span>3Y yıllık</span><b>${pct(p.portfolio["3y"], 1)}</b></div>
      <div><span>5Y yıllık</span><b>${pct(p.portfolio["5y"], 1)}</b></div>
      <div><span>Kuruluş</span><b>${dateTR(p.formed)}</b></div>
    </div>
    <div class="weight-bar">${bar}</div>
    <div class="table-wrap"><table class="model-table">
      <thead><tr><th class="left">Fon</th><th class="left">Şirket</th><th class="left">Varlık sınıfı</th><th>Ağırlık</th><th>Puan</th><th>Not</th>
        <th>1Y</th><th>3Y yıllık</th><th>5Y yıllık</th><th title="3 yıllık reel (TÜFE üstü) yıllık getiri">3Y reel</th>
        <th title="12 aylık dönemlerin kaçında TÜFE'yi geçti">TÜFE'yi geçen 12A</th><th>Maks. düşüş (3Y)</th><th>Oynaklık</th><th class="left">Bugünkü durum</th></tr></thead>
      <tbody>${p.basket.map((b, i) => `<tr>
        <td class="left"><span class="mdl-swatch" style="background:${SLICE[i % SLICE.length]}"></span>${chip(b.c)}${tags(b)}
          <span class="fund-name">${esc(b.n)}</span></td>
        <td class="left dim">${esc(b.co || "—")}</td><td class="left dim">${esc(b.bk || b.k || "—")}</td><td><b class="weight">%${b.w}</b></td><td>${num(b.score, 0)}</td>
        <td>${esc(b.gNow || b.g || "—")}</td>
        <td>${pct(b.r["1y"], 1)}</td><td>${pct(b.r["3y"], 1)}</td><td>${pct(b.r["5y"], 1)}</td><td>${pct(b.real3, 1)}</td>
        <td>%${num(b.realWin, 0)}</td><td class="down">${pct(b.mdd, 1)}</td><td>%${num(b.vol, 1)}</td>
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
  const names = m ? Object.keys(m.companies).sort((a, b) => a.localeCompare(b, "tr")) : [];
  if (!m || (!m.befas && !names.length)) {
    body.innerHTML = `<div class="card empty"><h3>BES modeli için yeterli geçmiş yok</h3><p>Model 3 yıllık fiyat geçmişi istiyor; emeklilik fonlarının geçmişi doldukça açılacak.</p></div>`;
    return;
  }
  const R = m.rules;
  if (!state.company || !m.companies[state.company]) {
    const best = names.map((n) => [n, m.companies[n].backtest.available ? m.companies[n].backtest.stats.model.total : -1e9]).sort((a, b) => b[1] - a[1]);
    state.company = best[0]?.[0];
  }
  const summary = names.map((n) => {
    const p = m.companies[n];
    const st = p.backtest.available ? p.backtest.stats.model : null;
    return `<tr data-co="${esc(n)}" class="${n === state.company ? "is-self" : ""} row-link">
      <td class="left"><b>${esc(n)}</b>${p.channel ? ` <span class="dim">· ${esc(p.channel)}</span>` : ""}</td>
      <td>${p.basket.length}</td><td>${st ? pct(st.total, 1) : "—"}</td><td>${st ? pct(st.cagr, 1) : "—"}</td>
      <td class="down">${st ? pct(st.mdd, 1) : "—"}</td><td>${pct(p.portfolio["3y"], 1)}</td><td>${pct(p.sinceEntry, 2)}</td></tr>`;
  }).join("");
  const B = m.befas;
  const ust = B?.backtest.available ? B.backtest.stats : null;

  body.innerHTML = `
  <section class="card">
    <div class="card-head"><h2>Uzun vadeli BES modeli (BEFAS)</h2><span class="sub">2 ayda bir · son kurulum ${B ? dateTR(B.formed) : "—"} · sonraki ${dateTR(m.nextRebalance)}</span></div>
    <p><b>BEFAS</b> (Takasbank'ın emeklilik fonu platformu, Temmuz 2021'den beri) sayesinde hangi emeklilik şirketinde olursan ol, kendi şirketinin
      uygulamasından <b>başka şirketlerin fonlarını</b> da alabilirsin. İstisnalar (EGM): grup fonları, unvanında "yabancı" ibaresi olan fonlar,
      para piyasası, katkı ve başlangıç fonları; bunlar yalnızca kendi şirketinin sözleşmesinde. Bu yüzden ana sepet, tüm şirketlerin
      <b>BEFAS'a açık</b> fonları arasından kurulur; herkes kendi sözleşmesinden uygulayabilir.</p>
    <p>5–10 yıllık birikim için: PPF benzeri faiz fonları alınmaz; 3 yılda enflasyonu (TÜFE) geçmiş, tek bir sıçramaya dayanmayan, notu ve risk bayrakları
      temiz fonlar seçilir. Sepet varlık sınıfı başına (altın, yerli hisse, teknoloji-yabancı, çok varlıklı) en fazla ${R.perCat} ve şirket başına en fazla
      ${R.perCompany} fon içerir; ağırlıklar <b>eşit</b> dağıtılır (tahmine dayalı ağırlıklar uzun vadede eşit ağırlığı genelde geçemez; DeMiguel, Garlappi ve Uppal, 2009).</p>
    ${B ? basketHtml(B, "bf") : `<p class="dim">BEFAS sepeti için yeterli fon yok.</p>`}
    ${ust ? `<div class="notice">Geçmiş testte BEFAS sepeti ${pct(ust.model.total, 1)} getirirken BEFAS'a açık tüm uygun fonların eşit ağırlıklı sepeti
      ${pct(ust.universe?.total, 1)}, gram altın ${pct(ust.gold?.total, 1)}, TÜFE ${pct(ust.tufe?.total, 1)} getirdi. Altın bu dönemde çok güçlüydü;
      model altını tek bir varlık sınıfı olarak sınırlı tutar (çeşitlendirme).</div>` : ""}
  </section>

  ${calculator(B?.portfolio["3y"] ?? 35)}

  <section class="card">
    <div class="card-head"><h2>Kendi şirketinle (BEFAS'sız alternatif)</h2><span class="sub">Yalnızca şirketin kendi fonlarıyla; "yabancı" ibareli fonlar da dahil</span></div>
    <div class="table-wrap"><table class="compact" id="coTable">
      <thead><tr><th class="left">Şirket</th><th>Fon</th><th>Geçmiş toplam</th><th>Yıllık</th><th>Maks. düşüş</th><th>Sepet 3Y yıllık</th><th>Dönem başından</th></tr></thead>
      <tbody>${summary}</tbody>
    </table></div>
    <div id="coBody"></div>
  </section>

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
      <li><b>Çeşitlendirme:</b> varlık sınıfı / kategori başına en fazla ${R.perCat}, BEFAS sepetinde şirket başına en fazla ${R.perCompany} fon; haftalık getiri korelasyonu &gt; ${num(R.maxCorr, 2)} olan ikinci fon alınmaz.</li>
      <li><b>Ağırlık:</b> eşit (1/N), her fon %${num(R.minW * 100, 0)}–%${num(R.maxW * 100, 0)}, 5'in katları. BES'te fon dağılımı yılda 12 kez değiştirilebilir; 2 aylık yenileme yılda 6 hak kullanır.</li>
      <li><b>Vergi:</b> birikim döneminde fon getirisinden stopaj kesilmez (yatırım fonunda altın, yabancı, değişken fonlarda %17,5). Çıkışta yalnızca getiriden:
        10 yıldan önce %15, 10 yılı dolduran ama 56 yaşını doldurmayan %10, emeklilik hakkıyla %5. Anapara ve devlet katkısı anaparası vergilenmez.</li>
      <li><b>Devlet katkısı (2026):</b> katkı payının %20'si, yıllık üst sınır brüt asgari ücretin %20'si (79.272 TL); hak ediş 3 yıl %15, 6 yıl %35, 10 yıl %60, emeklilikte %100.
        Devlet katkısı şirketin devlet katkısı fonlarında değerlenir; BEFAS'tan alınamaz.</li>
      <li><b>Vergi açısından yerleşim:</b> yatırım fonunda %0 stopajlı hisse yoğun fonlarla BES arasında birikim vergisi farkı yoktur; BES'in vergi avantajı en çok
        normal fonda %17,5 stopajlı altın, yabancı ve değişken fonlarda ortaya çıkar.</li>
    </ol>
  </section>`;

  if (B) bindBasket(body, B, "bf", "BEFAS BES modeli");
  bindCalculator(body);
  const drawCompany = () => {
    const p = m.companies[state.company];
    if (!p) return;
    body.querySelector("#coBody").innerHTML = `<div class="card-head sub-head"><h3>${esc(p.company)} sepeti</h3>
      <span class="sub">${p.channel ? `satış kanalı: ${esc(p.channel)}` : ""}</span></div>${basketHtml(p, "co")}`;
    bindBasket(body, p, "co", `${p.company} modeli`);
  };
  body.querySelector("#coTable").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-co]");
    if (!tr) return;
    state.company = tr.dataset.co;
    body.querySelectorAll("#coTable tr[data-co]").forEach((x) => x.classList.toggle("is-self", x === tr));
    drawCompany();
  });
  drawCompany();
}
