// Model Rapor: fon modelleri ve BES Öneri modelinin aylık getirileri, kıyaslarla (A4, yazdırılabilir / PDF)
import { esc, num, dateTR, monthLabel } from "../util.js";

const BENCH = [
  ["ppf", "PPF ortalaması", "#64748b"],
  ["tufe", "TÜFE", "#d6404a"],
  ["gold", "Gram altın", "#c58b12"],
  ["usd", "Dolar/TL", "#0f8a50"],
  ["sp500", "S&P 500 (TL)", "#7c3aed"],
];
const MODEL_COLOR = "#1f5fbf";
const MONTHS_LONG = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
const monthLong = (iso) => `${MONTHS_LONG[+iso.slice(5, 7) - 1]} ${iso.slice(0, 4)}`;
const pctS = (v, d = 1) => (v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}%${num(Math.abs(v), d)}`);
const ptsS = (v) => (v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v), 1)} puan`);
const tone = (v) => (v == null || !isFinite(v) || v === 0 ? "" : v > 0 ? "up" : "down");

let cache = null;
const load = () => (cache ||= fetch(`data/model_report.json?v=${Date.now().toString(36).slice(0, -3)}`)
  .then((r) => (r.ok ? r.json() : null)).catch(() => null));

/** Seviye serisinden aylık satırlar: her nokta bir ayın ilk işlem günü; son nokta ay içindeyse kısmi ay. */
function months(m) {
  const d = m.dates, rows = [];
  for (let i = 1; i < d.length; i++) {
    const r = {};
    for (const k of Object.keys(m.series)) {
      const a = m.series[k][i - 1], b = m.series[k][i];
      r[k] = a != null && b != null ? (b / a - 1) * 100 : null;
    }
    rows.push({ start: d[i - 1], end: d[i], partial: i === d.length - 1 && !isMonthStart(d, i), r });
  }
  return rows;
}
// Son nokta bir sonraki ayın ilk işlem günü değilse (veri ay ortasında bitiyorsa) son ay kısmidir
// Ay başında (rapor e-postasının gittiği gün) son nokta önceki ayın son işlem günüdür: o ay bitmiştir.
function isMonthStart(d, i) {
  const prev = d[i - 1].slice(0, 7), cur = d[i].slice(0, 7);
  if (cur !== prev && +d[i].slice(8, 10) <= 4) return true;
  return i === d.length - 1 && cur < new Date().toISOString().slice(0, 7);
}

const ret = (s, i0, i1) => (s?.[i0] != null && s?.[i1] != null ? (s[i1] / s[i0] - 1) * 100 : null);
// Son tamamlanmış ayın bitiş noktası (kısmi son ay hariç)
const lastFull = (m) => (isMonthStart(m.dates, m.dates.length - 1) ? m.dates.length - 1 : m.dates.length - 2);

function heatColor(v) {
  if (v == null || !isFinite(v)) return "transparent";
  const a = Math.min(1, Math.abs(v) / 10) * 0.75 + 0.08;
  return v >= 0 ? `rgba(15,138,80,${a.toFixed(2)})` : `rgba(214,64,74,${a.toFixed(2)})`;
}
const heatCell = (v) => `<td class="mr-heat ${Math.abs(v ?? 0) >= 6 ? "strong" : ""}" style="background:${heatColor(v)}">${v == null ? "—" : num(v, 1)}</td>`;

const modelLines = (m) => [
  { name: "Model", v: m.series.model, color: MODEL_COLOR, w: 2.4 },
  ...BENCH.filter(([k]) => m.series[k]).map(([k, l, c]) => ({ name: l.replace(" ortalaması", ""), v: m.series[k], color: c, dash: k === "ppf" })),
];

/** Statik SVG birikimli getiri grafiği (yazdırmada da aynı görünür). */
function chart(dates, lines, H = 168, W = 764, xLabel = null) {
  const pad = { l: 34, r: 92, t: 8, b: 18 };
  const vals = lines.flatMap((l) => l.v).filter((v) => v != null);
  const lo = Math.min(100, ...vals), hi = Math.max(...vals);
  const n = dates.length;
  const x = (i) => pad.l + (i / (n - 1)) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - (v - lo) / (hi - lo || 1)) * (H - pad.t - pad.b);
  const ticks = [];
  const step = Math.pow(10, Math.floor(Math.log10((hi - lo) / 3 || 1)));
  const st = [1, 2, 5, 10].map((f) => f * step).find((s) => (hi - lo) / s <= 5) || step * 10;
  for (let v = Math.ceil(lo / st) * st; v <= hi; v += st) ticks.push(v);
  const xStep = Math.max(1, Math.round((n - 1) / 6));
  const xt = dates.map((d, i) => [d, i]).filter(([d], i) => i === 0 || i === n - 1
    || (xLabel ? i % xStep === 0 : (d.slice(5, 7) === "01" || d.slice(5, 7) === "07")) && x(i) - x(0) > 36 && x(n - 1) - x(i) > 36);
  // Seri sonu etiketleri çakışmasın: değere göre sırala, en az 10 px aralık
  const ends = lines.map((l) => ({ l, v: l.v[n - 1] })).filter((e) => e.v != null).sort((a, b) => b.v - a.v);
  let lastY = -Infinity;
  for (const e of ends) { e.y = Math.max(y(e.v), lastY + 10); lastY = e.y; }
  return `<svg class="mr-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Birikimli getiri grafiği">
    ${ticks.map((v) => `<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" class="${v === 100 ? "base" : "grid"}"/>
      <text x="${pad.l - 5}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end">${num(v, 0)}</text>`).join("")}
    ${xt.map(([d, i]) => `<text x="${x(i).toFixed(1)}" y="${H - 4}" text-anchor="${i === 0 ? "start" : i === n - 1 ? "end" : "middle"}">${xLabel ? xLabel(d) : monthLabel(d)}</text>`).join("")}
    ${lines.slice().reverse().map((l) => {
      const pts = l.v.map((v, i) => (v == null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean).join(" ");
      return `<polyline points="${pts}" fill="none" stroke="${l.color}" stroke-width="${l.w || 1.3}" ${l.dash ? 'stroke-dasharray="4 3"' : ""} stroke-linejoin="round"/>`;
    }).join("")}
    ${ends.map((e) => `<text x="${W - pad.r + 6}" y="${(e.y + 3).toFixed(1)}" class="end" fill="${e.l.color}">${esc(e.l.name)} ${num(e.v, 0)}</text>`).join("")}
  </svg>`;
}

function cover(badge, title, sub, caption = "MODEL PORTFÖY RAPORU") {
  return `<header class="rp-cover">
      <div class="rp-brand"><img src="assets/img/logo.webp" alt=""><div><b>TEFAS Quant</b><span>${caption}</span></div></div>
      <span class="rp-badge">${badge}</span>
      <h1>${title}</h1>
      <p class="rp-period">${sub}</p>
    </header>`;
}

function footer(text, asOf, pageNo, total) {
  return `<footer class="rp-footer"><span>${text} Geriye dönük testtir; geçmiş getiri geleceği göstermez. Yatırım tavsiyesi değildir.</span>
      <span>Oluşturma ${dateTR(asOf)} · Sayfa ${pageNo} / ${total}</span></footer>`;
}

const TABLE_FROM = "2024-11";  // aylık getiri tablosu bu aydan başlar; grafik ve özetler son 12 ay

/** Son 12 tamamlanmış ay (süren ay hariç): seriler pencere başında 100'e çekilir. */
function lastYear(m) {
  const e = lastFull(m), s0 = Math.max(0, e - 12);
  const series = {};
  for (const [k, v] of Object.entries(m.series)) {
    const w = v.slice(s0, e + 1), b = w.find((x) => x != null);
    series[k] = w.map((x) => (x == null || !b ? null : (x / b) * 100));
  }
  return { ...m, dates: m.dates.slice(s0, e + 1), series };
}

function summaryPage(models, asOf, total) {
  const fon = models.filter((m) => m.kind === "fon");
  const ref = fon[0] || models[0];
  const e = lastFull(ref);
  const lastMonth = ref.dates[e - 1];
  const yr = lastMonth.slice(0, 4);
  const per = (m, s, name, extra) => {
    const eM = lastFull(m);
    const y0 = m.dates.findIndex((d) => d.slice(0, 4) === yr);  // yılbaşından: yılın ilk ay noktasından
    return { name, ...extra, m1: ret(s, eM - 1, eM), m3: ret(s, eM - 3, eM), m6: ret(s, eM - 6, eM), m12: ret(s, eM - 12, eM),
      ytd: y0 >= 0 && y0 < eM ? ret(s, y0, eM) : null };
  };
  const rows = models.map((m) => per(m, m.series.model, m.label, { kind: m.kind }));
  const bRows = BENCH.filter(([k]) => ref.series[k]).map(([k, label]) => per(ref, ref.series[k], label, { bench: true }));

  // Isı haritası: son 12 tamamlanmış ay
  const monthKeys = ref.dates.slice(Math.max(0, e - 12), e).map((d) => d.slice(0, 7));
  const byMonth = (m, k) => {
    const map = new Map(months(m).filter((r) => !r.partial).map((r) => [r.start.slice(0, 7), r.r[k]]));
    return monthKeys.map((mk) => map.get(mk) ?? null);
  };
  const heatRows = [
    ...models.map((m) => ({ name: m.label, v: byMonth(m, "model"), self: true })),
    ...BENCH.filter(([k]) => ref.series[k]).map(([k, label]) => ({ name: label, v: byMonth(ref, k) })),
  ];

  // Birikimli grafik: son 12 ay; BES Öneri aynı ay noktalarına hizalanır (son, süren ay noktası ayrı tutulur)
  const refY = lastYear(ref);
  const pointKey = (d, i) => d[i].slice(0, 7) + (i === d.length - 1 && !isMonthStart(d, i) ? "+" : "");
  const align = (m) => {
    const y = lastYear(m);
    const map = new Map(y.dates.map((_, i) => [pointKey(y.dates, i), y.series.model[i]]));
    const v = refY.dates.map((_, i) => map.get(pointKey(refY.dates, i)) ?? null);
    const b = v.find((x) => x != null);
    return v.map((x) => (x == null || !b ? null : (x / b) * 100));
  };
  const colors = { guvenli: "#0b7a45", dengeli: "#1f5fbf", atak: "#db2777", bes: "#0891b2" };

  const tr = (r) => `<tr class="${r.bench ? "mr-bench" : "mr-self"}">
      <td><b>${esc(r.name)}</b>${r.kind === "bes" ? ' <span class="mr-tag">BES</span>' : ""}</td>
      ${[r.m1, r.m3, r.m6, r.m12].map((v) => `<td class="r num ${tone(v)}">${pctS(v)}</td>`).join("")}
      <td class="r num ${tone(r.ytd)}"><b>${pctS(r.ytd)}</b></td></tr>`;

  return `<article class="rp-page">
    ${cover("AYLIK RAPOR", "Model Performans Raporu",
      `Güvenli · Dengeli · Atak fon modelleri ve BES Öneri · ${monthLong(lastMonth)} sonu itibarıyla son 12 ay · PPF, TÜFE, altın, dolar ve S&P 500 ile`)}
    <div class="rp-kpis">${rows.map((r) => `<div class="${tone(r.m1)}"><span>${esc(r.name)} · ${MONTHS_LONG[+lastMonth.slice(5, 7) - 1]}</span>
      <b>${pctS(r.m1)}</b><em>Son 12 ayda ${pctS(r.m12)}</em></div>`).join("")}</div>

    <section class="rp-block">
      <h3><span class="rp-dot brand"></span>Dönemsel getiriler (tamamlanmış aylar)</h3>
      <table class="rp-table mr-sum">
        <thead><tr><th>Model / kıyas</th><th class="r">${MONTHS_LONG[+lastMonth.slice(5, 7) - 1]}</th><th class="r">3 ay</th><th class="r">6 ay</th><th class="r">12 ay</th>
          <th class="r">${yr} yılbaşından</th></tr></thead>
        <tbody>${rows.map(tr).join("")}${bRows.map(tr).join("")}</tbody>
      </table>
    </section>

    <section class="rp-block">
      <h3><span class="rp-dot brand"></span>Son 12 ay · aylık getiri ısı haritası (%)</h3>
      <table class="rp-table mr-heatmap">
        <thead><tr><th>Model / kıyas</th>${monthKeys.map((mk) => `<th class="r">${monthLabel(mk + "-01")}</th>`).join("")}</tr></thead>
        <tbody>${heatRows.map((h) => `<tr class="${h.self ? "mr-self" : "mr-bench"}"><td><b>${esc(h.name)}</b></td>${h.v.map(heatCell).join("")}</tr>`).join("")}</tbody>
      </table>
    </section>

    <section class="rp-block">
      <h3><span class="rp-dot brand"></span>Birikimli getiri · son 12 ay (${monthLabel(refY.dates[0])} = 100)</h3>
      ${chart(refY.dates, [
        ...models.map((m) => ({ name: m.label, v: m === ref ? refY.series.model : align(m), color: colors[m.key] || MODEL_COLOR, w: 2.2 })),
        ...BENCH.filter(([k]) => refY.series[k]).map(([k, l, c]) => ({ name: l.replace(" ortalaması", ""), v: refY.series[k], color: c, dash: k === "ppf" })),
      ], 200)}
    </section>

    <section class="rp-block">
      <h3><span class="rp-dot brand"></span>Hangi model hangi kıyası geçti? (son 12 ay, toplam getiri farkı)</h3>
      <table class="rp-table mr-beat">
        <thead><tr><th>Model</th>${BENCH.filter(([k]) => ref.series[k]).map(([, l]) => `<th class="r">${esc(l)}</th>`).join("")}</tr></thead>
        <tbody>${models.map((m) => {
          const y = lastYear(m), n2 = y.dates.length - 1, t = ret(y.series.model, 0, n2);
          return `<tr><td><b>${esc(m.label)}</b></td>${BENCH.filter(([k]) => ref.series[k]).map(([k]) => {
            const b = ret(y.series[k], 0, n2), d = t == null || b == null ? null : t - b;
            return `<td class="r num ${tone(d)}">${d == null ? "—" : `${d >= 0 ? "✓ " : "✗ "}${ptsS(d)}`}</td>`;
          }).join("")}</tr>`;
        }).join("")}</tbody>
      </table>
    </section>

    ${footer("Model getirileri fon fiyatlarından (yönetim ücreti düşülmüş), vergi öncesi hesaplanır; fon modelleri aylık, BES Öneri 2 ayda bir yenilenir. S&P 500 temettüsüz fiyat endeksidir, dolar/TL ile TL'ye çevrilir.", asOf, 1, total)}
  </article>`;
}

function modelPage(m, asOf, pageNo, total) {
  const rows = months(m).filter((r) => r.start.slice(0, 7) >= TABLE_FROM);
  const y = lastYear(m);
  const yFull = months(y).filter((r) => !r.partial);
  const s = y.series.model, n = s.length - 1;
  const tot = ret(s, 0, n);
  const pos = yFull.filter((r) => r.r.model > 0).length;
  const best = yFull.reduce((a, r) => (r.r.model > (a?.r.model ?? -Infinity) ? r : a), null);
  const worst = yFull.reduce((a, r) => (r.r.model < (a?.r.model ?? Infinity) ? r : a), null);
  const bench = BENCH.filter(([k]) => m.series[k]);
  const isBes = m.kind === "bes";
  const desc = {
    guvenli: "Para piyasası ve kısa vadeli borçlanma ağırlıklı; hedef PPF'ye yakın, düşük oynaklık.",
    dengeli: "Karma ve değişken fonlarla PPF üstü getiri hedefi; orta oynaklık, trend kapısı açık.",
    atak: "Hisse ve tematik fon ağırlıklı; yüksek oynaklık, uzun vadede TÜFE ve PPF üstü hedef.",
    bes: "BEFAS'a açık tüm şirketlerden en çok 6 fon; uzun vade (3–10 yıl), vergi avantajı yüksek varlıklara öncelik.",
  }[m.key] || "";

  const cmp = bench.map(([k, label, color]) => {
    const bt = ret(y.series[k], 0, n), diff = tot == null || bt == null ? null : tot - bt;
    const beat = yFull.filter((r) => r.r.model != null && r.r[k] != null && r.r.model > r.r[k]).length;
    return { k, label, color, bt, diff, beat };
  });
  const maxDiff = Math.max(...cmp.map((c) => Math.abs(c.diff || 0)), 1);

  // Uzun dönem birikimli getiri: son tamamlanmış aydan geriye 24 / 36 ay. Süreye en fazla 3 ay kalmışsa
  // başlangıçtan bugüne gösterilir (ay sayısıyla); daha kısa geçmişte boş kalır.
  const eF = lastFull(m);
  const longRet = (months) => {
    const head = `<span>${months / 12} yıl birikimli</span>`;
    if (eF < months - 3) return `<div>${head}<b>—</b><em>Geçmiş ${eF} ay, ${months / 12} yıl dolmadı</em></div>`;
    const i0 = Math.max(0, eF - months);
    const r = ret(m.series.model, i0, eF), p = ret(m.series.ppf, i0, eF);
    const note = eF < months ? `Başlangıçtan ${eF} ay` : `${monthLong(m.dates[i0])} başından`;
    return `<div class="${tone(r)}">${head}<b>${pctS(r)}</b><em>${note} · PPF ${pctS(p)}</em></div>`;
  };

  return `<article class="rp-page">
    ${cover(isBes ? "BES MODELİ" : "FON MODELİ", `${esc(m.label)}${isBes ? "" : " Model"} · Aylık Performans`,
      `Son 12 ay: ${dateTR(y.dates[0])} – ${dateTR(y.dates[n])} · ${esc(desc)}`)}
    <div class="rp-kpis mr-kpis6">
      <div class="${tone(tot)}"><span>Son 12 ay getirisi</span><b>${pctS(tot)}</b><em>${monthLong(y.dates[0])} başından</em></div>
      <div><span>Pozitif ay (12 ay)</span><b>${pos} / ${yFull.length}</b><em>%${num((pos / Math.max(yFull.length, 1)) * 100, 0)} isabet</em></div>
      <div class="up"><span>En iyi ay</span><b>${pctS(best?.r.model)}</b><em>${best ? monthLong(best.start) : "—"}</em></div>
      <div class="down"><span>En kötü ay</span><b>${pctS(worst?.r.model)}</b><em>${worst ? monthLong(worst.start) : "—"}</em></div>
      ${longRet(24)}
      ${longRet(36)}
    </div>

    <div class="rp-two mr-two">
      <section class="rp-block">
        <h3><span class="rp-dot brand"></span>Birikimli getiri · son 12 ay (${monthLabel(y.dates[0])} = 100)</h3>
        ${chart(y.dates, modelLines(y), 210, 470)}
      </section>
      <section class="rp-block">
        <h3><span class="rp-dot brand"></span>Kıyaslara karşı fark · son 12 ay</h3>
        <div class="mr-cmp">${cmp.map((c) => `<div class="mr-cmp-row">
          <span class="mr-cmp-name"><i style="background:${c.color}"></i>${esc(c.label)}</span>
          <span class="rp-cat-track"><span class="rp-cat-mid"></span><i class="${(c.diff ?? 0) >= 0 ? "up" : "down"}" style="width:${((Math.abs(c.diff || 0) / maxDiff) * 50).toFixed(1)}%"></i></span>
          <span class="num ${tone(c.diff)}"><b>${ptsS(c.diff)}</b></span>
          <span class="mr-cmp-sub">kıyas ${pctS(c.bt)} · ${c.beat}/${yFull.length} ay önde</span></div>`).join("")}</div>
      </section>
    </div>

    <section class="rp-block">
      <h3><span class="rp-dot brand"></span>Aylık getiriler (%) · model ve kıyaslar · ${monthLong(TABLE_FROM + "-01")} başından bugüne</h3>
      <table class="rp-table mr-month ${rows.length > 28 ? "mr-dense" : ""}">
        <thead><tr><th>Ay</th><th class="r">${esc(m.label)}</th>${bench.map(([, l]) => `<th class="r">${esc(l)}</th>`).join("")}<th class="r">PPF'ye fark</th><th>Ayın en iyisi</th></tr></thead>
        <tbody>${rows.slice().reverse().map((r) => {
          const all = [["model", m.label], ...bench.map(([k, l]) => [k, l])].filter(([k]) => r.r[k] != null);
          const top = all.reduce((a, b) => (r.r[b[0]] > r.r[a[0]] ? b : a), all[0]);
          const dPpf = r.r.model != null && r.r.ppf != null ? r.r.model - r.r.ppf : null;
          return `<tr class="${r.partial ? "mr-partial" : ""}">
            <td>${monthLong(r.start)}${r.partial ? ` <span class="mr-tag" title="${dateTR(r.end)} tarihine kadar">KISMİ</span>` : ""}</td>
            <td class="r num mr-model ${tone(r.r.model)}"><b>${pctS(r.r.model)}</b></td>
            ${bench.map(([k]) => `<td class="r num ${tone(r.r[k])}">${pctS(r.r[k])}</td>`).join("")}
            <td class="r num ${tone(dPpf)}">${ptsS(dPpf)}</td>
            <td class="${top?.[0] === "model" ? "mr-win" : "dim"}">${top ? esc(top[0] === "model" ? "★ Model" : top[1]) : "—"}</td></tr>`;
        }).join("")}</tbody>
      </table>
    </section>

    ${footer(isBes
      ? "BES Öneri: 2 ayda bir yeniden kurulan BEFAS sepeti, ara aylarda aynı sepet tutulur; fon değişikliği vergisizdir, devlet katkısı dahil değildir."
      : `${esc(m.label)} model: her ay yeniden kurulan sepet (T+1 alış), vergi öncesi. Normal hesapta fon değişikliğinde kazançtan stopaj kesilir.`, asOf, pageNo, total)}
  </article>`;
}

export async function render(app, _route, store) {
  const data = await load();
  if (!data?.models?.length) {
    app.innerHTML = `<div class="card empty"><h3>Model raporu henüz hazır değil</h3><p>Bir sonraki veri güncellemesinde oluşturulur.</p></div>`;
    return;
  }
  const total = data.models.length + 1;
  app.innerHTML = `
  <div class="rp-toolbar no-print">
    <div><h2>Model performans raporu</h2>
      <p class="dim">Fon modelleri ve BES Öneri'nin aylık getirileri · PPF, TÜFE, altın, dolar ve S&P 500 ile · ${dateTR(data.asOf)} itibarıyla</p></div>
    <div class="rp-actions"><button class="btn btn-primary" id="mrPrint" type="button">⤓ PDF olarak indir</button></div>
  </div>
  <div class="rp-doc">${summaryPage(data.models, data.asOf, total)}${data.models.map((m, i) => modelPage(m, data.asOf, i + 2, total)).join("")}</div>`;
  app.querySelector("#mrPrint").addEventListener("click", () => {
    const prev = document.title;
    document.title = `TEFAS-Quant-Model-Raporu-${data.asOf}`;  // PDF dosya adı
    window.print();
    setTimeout(() => (document.title = prev), 500);
  });
}

// Kişisel portföy raporu ve karşılaştırma sayfası aynı yardımcıları kullanır
export { BENCH, MONTHS_LONG, monthLong, pctS, ptsS, tone, months, isMonthStart, ret, lastFull, heatCell, chart, cover, footer, lastYear, load as loadModelReport };
