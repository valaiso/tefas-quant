// Rapor: haftalık ve aylık akış / yatırımcı raporu (2 sayfa A4, yazdırılabilir / PDF)
import { esc, num, money, dateTR } from "../util.js";
import { qualifiedToggle, includeQualified, bindQualified } from "./common.js";

const PERIODS = [
  { key: "1w", title: "Haftalık Fon Akış Raporu", badge: "HAFTALIK", label: "hafta" },
  { key: "1m", title: "Aylık Fon Akış Raporu", badge: "AYLIK", label: "ay" },
];

const short = (name, n = 44) => {
  const s = String(name || "").replace(/\s*\(.*?\)\s*/g, " ").replace(/\s+/g, " ").trim();
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
};

const signed = (v) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${money(Math.abs(v))}`);
const signedNum = (v) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v), 0)}`);
const pctS = (v, d = 1) => (v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}%${num(Math.abs(v), d)}`);
// Akış / dönem başı büyüklük (dönem başı ≈ bugünkü büyüklük − net akış)
const flowShare = (f, key) => {
  const base = (f.aum || 0) - (f.fl[key] || 0);
  return base > 0 ? (f.fl[key] / base) * 100 : null;
};

function bar(value, max, tone) {
  const w = max ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
  return `<span class="rp-bar ${tone}"><i style="width:${w.toFixed(1)}%"></i></span>`;
}

function flowTable(title, rows, key, tone) {
  const max = Math.max(...rows.map((f) => Math.abs(f.fl[key] || 0)), 1);
  return `<section class="rp-block">
    <h3><span class="rp-dot ${tone}"></span>${title}</h3>
    <table class="rp-table">
      <thead><tr><th>#</th><th>Fon</th><th class="r">Net akış</th><th class="r" title="Net akış / dönem başı büyüklük">Büyüklüğe</th><th class="bar-col"></th></tr></thead>
      <tbody>${rows.map((f, i) => `<tr>
        <td class="rk">${i + 1}</td>
        <td><b class="mono">${esc(f.c)}</b> <span class="nm">${esc(short(f.n, 34))}</span><div class="ct">${esc(f.k)}</div></td>
        <td class="r num ${tone}">${signed(f.fl[key])}</td>
        <td class="r num">${pctS(flowShare(f, key))}</td>
        <td class="bar-col">${bar(f.fl[key], max, tone)}</td></tr>`).join("")}
      </tbody></table></section>`;
}

function investorTable(rows, key) {
  const max = Math.max(...rows.map((f) => Math.abs(f.ivd[key] || 0)), 1);
  return `<section class="rp-block">
    <h3><span class="rp-dot brand"></span>En çok yatırımcı kazanan 10 fon</h3>
    <table class="rp-table rp-inv">
      <thead><tr><th>#</th><th>Fon</th><th>Kategori</th><th class="r">Yeni yatırımcı</th><th class="r">Değişim</th><th class="r">Toplam</th><th class="r">Not</th><th class="bar-col"></th></tr></thead>
      <tbody>${rows.map((f, i) => `<tr>
        <td class="rk">${i + 1}</td>
        <td><b class="mono">${esc(f.c)}</b> <span class="nm">${esc(short(f.n, 40))}</span></td>
        <td class="ct-cell">${esc(f.k)}</td>
        <td class="r num up">${signedNum(f.ivd[key])}</td>
        <td class="r num">${pctS(f.ivp[key])}</td>
        <td class="r num">${num(f.inv, 0)}</td>
        <td class="r"><span class="rp-grade g-${f.g === "A+" ? "ap" : f.g.toLowerCase()}">${esc(f.g)}</span></td>
        <td class="bar-col">${bar(f.ivd[key], max, "brand")}</td></tr>`).join("")}
      </tbody></table></section>`;
}

function categoryChart(funds, key) {
  const by = new Map();
  for (const f of funds) by.set(f.k, (by.get(f.k) || 0) + (f.fl[key] || 0));
  const rows = [...by.entries()].sort((a, b) => b[1] - a[1]);
  const max = Math.max(...rows.map(([, v]) => Math.abs(v)), 1);
  return `<div class="rp-cats">${rows.map(([k, v]) => `
    <div class="rp-cat"><span class="rp-cat-name">${esc(k)}</span>
      <span class="rp-cat-track"><span class="rp-cat-mid"></span>
        <i class="${v >= 0 ? "up" : "down"}" style="width:${((Math.abs(v) / max) * 50).toFixed(1)}%"></i></span>
      <span class="rp-cat-val num ${v >= 0 ? "up" : "down"}">${signed(v)}</span></div>`).join("")}</div>`;
}

function page(p, funds, meta, pageNo) {
  const key = p.key;
  const per = meta.periods?.[key] || {};
  const withFlow = funds.filter((f) => f.fl[key] != null);
  const inflow = [...withFlow].sort((a, b) => b.fl[key] - a.fl[key]).slice(0, 10);
  const outflow = [...withFlow].sort((a, b) => a.fl[key] - b.fl[key]).slice(0, 10);
  const investors = funds.filter((f) => f.ivd[key] != null).sort((a, b) => b.ivd[key] - a.ivd[key]).slice(0, 10);
  const net = withFlow.reduce((s, f) => s + f.fl[key], 0);
  const nIn = withFlow.filter((f) => f.fl[key] > 0).length;
  const nOut = withFlow.filter((f) => f.fl[key] < 0).length;
  const invNet = funds.reduce((s, f) => s + (f.ivd[key] || 0), 0);
  const catBy = new Map();
  for (const f of withFlow) catBy.set(f.k, (catBy.get(f.k) || 0) + f.fl[key]);
  const topCat = [...catBy.entries()].sort((a, b) => b[1] - a[1])[0];

  return `<article class="rp-page">
    <header class="rp-cover">
      <div class="rp-brand"><img src="assets/img/logo.webp" alt=""><div><b>TEFAS Quant</b><span>FON DERECELENDİRME</span></div></div>
      <span class="rp-badge">${p.badge} RAPOR</span>
      <h1>${p.title}</h1>
      <p class="rp-period">${dateTR(per.from)} – ${dateTR(per.to)} · ${num(funds.length, 0)} fon · ${includeQualified() ? "nitelikli fonlar dahil" : "yalnızca halka açık fonlar"}</p>
    </header>

    <div class="rp-kpis">
      <div class="${net >= 0 ? "up" : "down"}"><span>Toplam net akış</span><b>${signed(net)}</b></div>
      <div><span>Giriş / çıkış yapan fon</span><b><span class="up">${num(nIn, 0)}</span> / <span class="down">${num(nOut, 0)}</span></b></div>
      <div class="${invNet >= 0 ? "up" : "down"}"><span>Yatırımcı değişimi</span><b>${signedNum(invNet)}</b></div>
      <div><span>En çok giriş alan kategori</span><b class="sm">${esc(topCat?.[0] || "—")}</b><em>${signed(topCat?.[1])}</em></div>
    </div>

    <section class="rp-block">
      <h3><span class="rp-dot brand"></span>Kategorilere göre net akış</h3>
      ${categoryChart(withFlow, key)}
    </section>

    <div class="rp-two">
      ${flowTable("En çok para girişi alan 10 fon", inflow, key, "up")}
      ${flowTable("En çok para çıkışı yaşayan 10 fon", outflow, key, "down")}
    </div>

    ${investorTable(investors, key)}

    <footer class="rp-footer">
      <span>Kaynak: TEFAS (pay adedi değişimi × fiyat; yatırımcı sayısı). Net akış, dönemdeki günlük pay değişimlerinin o günkü fiyatla toplamıdır.
        Yatırım tavsiyesi değildir.</span>
      <span>Oluşturma ${dateTR(meta.lastDataDate)} · Sayfa ${pageNo} / 2</span>
    </footer>
  </article>`;
}

export function render(app, _route, store) {
  const funds = store.funds.filter((f) => includeQualified() || !f.q);
  app.innerHTML = `
  <div class="rp-toolbar no-print">
    <div><h2>Haftalık ve aylık akış raporu</h2>
      <p class="dim">En çok para girişi, para çıkışı ve yatırımcı artışı yaşayan fonlar · ${dateTR(store.meta.lastDataDate)} itibarıyla</p></div>
    <div class="rp-actions">${qualifiedToggle()}
      <button class="btn btn-primary" id="rpPrint" type="button">⤓ PDF olarak indir</button></div>
  </div>
  <div class="rp-doc">${PERIODS.map((p, i) => page(p, funds, store.meta, i + 1)).join("")}</div>`;

  bindQualified(app, () => render(app, _route, store));
  app.querySelector("#rpPrint").addEventListener("click", () => {
    const prev = document.title;
    document.title = `TEFAS-Quant-Akis-Raporu-${store.meta.lastDataDate}`;  // PDF dosya adı
    window.print();
    setTimeout(() => (document.title = prev), 500);
  });
}
