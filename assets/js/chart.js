// Bağımlılıksız SVG çizgi grafiği (çoklu seri, ızgara, ipucu)
import { esc, monthLabel, dateTR, num } from "./util.js";

const PALETTE = ["var(--c1)", "var(--c2)", "var(--c4)", "var(--c5)", "var(--c6)", "var(--c3)"];

/**
 * Açıklamadaki bir seriye tıklayınca seri gizlenir / gösterilir. Gizlenenler
 * aynı grafik kutusunda (dönem değişse de) hatırlanır; ölçek görünenlere göre ayarlanır.
 * @param {HTMLElement} el
 * @param {{name:string, d:string[], v:number[], dashed?:boolean, color?:string}[]} series
 * @param {{height?:number, format?:(v:number)=>string, base?:number}} opts
 */
export function lineChart(el, series, opts = {}) {
  const full = series.map((s, i) => ({ ...s, color: s.color || PALETTE[i % PALETTE.length] }));
  el._hidden = el._hidden || new Set();
  const visible = full.filter((s) => !el._hidden.has(s.name));
  draw(el, visible, opts, full);
  el.querySelectorAll(".chart-legend .item").forEach((item) =>
    item.addEventListener("click", () => {
      const name = item.dataset.name;
      el._hidden.has(name) ? el._hidden.delete(name) : el._hidden.add(name);
      lineChart(el, series, opts);
    }));
}

function legendHtml(full, hidden) {
  return `<div class="chart-legend">${full.map((s) => `<button type="button" class="item ${hidden.has(s.name) ? "off" : ""}"
      data-name="${esc(s.name)}" aria-pressed="${!hidden.has(s.name)}" title="Göster / gizle">
      <span class="swatch" style="background:${s.color}"></span>${esc(s.name)}</button>`).join("")}</div>`;
}

function draw(el, series, opts, full) {
  const H = opts.height || 280, W = Math.max(320, el.clientWidth || 720);
  const pad = { l: 46, r: 14, t: 12, b: 26 };
  const fmt = opts.format || ((v) => num(v, 1));
  const all = series.flatMap((s) => s.d.map((d, i) => ({ d, v: s.v[i] }))).filter((p) => p.v != null);
  if (!all.length) {
    el.innerHTML = `<div class="empty">${full.length ? "Tüm seriler gizli — açıklamadan birini seçin" : "Grafik verisi yok"}</div>${legendHtml(full, el._hidden)}`;
    return;
  }
  const dates = [...new Set(all.map((p) => p.d))].sort();
  const t0 = Date.parse(dates[0]), t1 = Date.parse(dates[dates.length - 1]) || t0 + 1;
  let lo = Math.min(...all.map((p) => p.v)), hi = Math.max(...all.map((p) => p.v));
  if (lo === hi) { lo -= 1; hi += 1; }
  const span = hi - lo; lo -= span * 0.06; hi += span * 0.06;
  const x = (d) => pad.l + ((Date.parse(d) - t0) / (t1 - t0 || 1)) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);

  const ticks = 5, grid = [];
  for (let i = 0; i <= ticks; i++) {
    const v = lo + ((hi - lo) * i) / ticks;
    grid.push(`<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(v)}" y2="${y(v)}" class="grid-line"/>` +
      `<text x="${pad.l - 6}" y="${y(v) + 4}" text-anchor="end" class="axis">${esc(fmt(v))}</text>`);
  }
  const months = [];
  let last = "";
  const stepMonths = Math.max(1, Math.round((t1 - t0) / (86400000 * 30) / 8));
  dates.forEach((d) => {
    const key = d.slice(0, 7);
    if (key !== last && (+d.slice(5, 7) - 1) % stepMonths === 0) {
      months.push(`<text x="${x(d)}" y="${H - 6}" text-anchor="middle" class="axis">${monthLabel(d)}</text>`);
    }
    last = key;
  });
  if (opts.base != null && opts.base >= lo && opts.base <= hi) {
    grid.push(`<line x1="${pad.l}" x2="${W - pad.r}" y1="${y(opts.base)}" y2="${y(opts.base)}" class="base-line"/>`);
  }

  const paths = series.map((s, i) => {
    const pts = s.d.map((d, j) => (s.v[j] == null ? null : `${x(d).toFixed(1)},${y(s.v[j]).toFixed(1)}`)).filter(Boolean);
    const color = s.color || PALETTE[i % PALETTE.length];
    return `<polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="${i === 0 ? 2.2 : 1.6}"
      ${s.dashed ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round" stroke-linecap="round"/>`;
  });

  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Fiyat grafiği">
      ${grid.join("")}${months.join("")}${paths.join("")}
      <line class="hover-line" y1="${pad.t}" y2="${H - pad.b}" x1="-10" x2="-10"/>
      <rect x="${pad.l}" y="${pad.t}" width="${W - pad.l - pad.r}" height="${H - pad.t - pad.b}" fill="transparent" class="hit"/>
    </svg>
    <div class="tooltip" hidden></div>
    ${legendHtml(full, el._hidden)}`;

  const svg = el.querySelector("svg"), tip = el.querySelector(".tooltip"), line = el.querySelector(".hover-line");
  const hit = el.querySelector(".hit");
  hit.addEventListener("mousemove", (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    const t = t0 + ((px - pad.l) / (W - pad.l - pad.r)) * (t1 - t0);
    let best = dates[0];
    for (const d of dates) if (Math.abs(Date.parse(d) - t) < Math.abs(Date.parse(best) - t)) best = d;
    line.setAttribute("x1", x(best)); line.setAttribute("x2", x(best));
    const rows = series.map((s, i) => {
      const j = s.d.indexOf(best);
      return j < 0 || s.v[j] == null ? "" :
        `<div class="t-row"><span><span class="sw" style="background:${s.color || PALETTE[i % PALETTE.length]}"></span>${esc(s.name)}</span><b>${esc(fmt(s.v[j]))}</b></div>`;
    }).join("");
    tip.innerHTML = `<div class="t-date">${dateTR(best)}</div>${rows}`;
    tip.hidden = false;
    tip.style.left = `${(x(best) / W) * 100}%`;
    tip.style.top = `${(pad.t / H) * 100 + 4}%`;
  });
  hit.addEventListener("mouseleave", () => { tip.hidden = true; line.setAttribute("x1", -10); line.setAttribute("x2", -10); });
}

/** Seriyi ilk değeri 100 olacak şekilde normalize eder. */
export function rebase(d, p, from) {
  const start = from ? d.findIndex((x) => x >= from) : 0;
  if (start < 0) return { d: [], v: [] };
  const base = p[start];
  return { d: d.slice(start), v: p.slice(start).map((x) => (x / base) * 100) };
}
