// Portföy karşılaştırma yardımcıları (BES sekmesi ve Değer sekmesi ortak kullanır)
const histCache = new Map();
let benchCache = null;

/** Yatırım fonu (data/history) ya da BES fonu (data/bes_history) haftalık fiyatı. */
export async function fundHistory(code, kind = "fon") {
  const dir = kind === "bes" ? "bes_history" : "history";
  const key = `${dir}/${code}`;
  if (!histCache.has(key)) {
    histCache.set(key, fetch(`data/${dir}/${encodeURIComponent(code)}.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null));
  }
  return histCache.get(key);
}

export async function besHistory(code) {
  return fundHistory(code, "bes");
}

export async function benchData() {
  if (!benchCache) benchCache = fetch("data/benchmarks.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  return benchCache;
}

/** Haftalık fiyatlardan sabit hedef ağırlıklı sepet; rebalWeeks=0 ise al-tut. */
export function basketSeries(weights, hists, from, rebalWeeks) {
  const codes = Object.keys(weights).filter((c) => hists[c]);
  if (!codes.length) return null;
  const maps = Object.fromEntries(codes.map((c) => [c, new Map(hists[c].d.map((d, i) => [d, hists[c].p[i]]))]));
  const start = [from, ...codes.map((c) => hists[c].d[0])].sort().pop();
  const dates = [...new Set(codes.flatMap((c) => hists[c].d))].filter((d) => d >= start).sort();
  if (dates.length < 2) return null;
  const last = Object.fromEntries(codes.map((c) => [c, null]));
  const tw = codes.reduce((a, c) => a + weights[c], 0);
  let units = null, value = 100;
  const out = { d: [], v: [], start };
  dates.forEach((d, k) => {
    codes.forEach((c) => { const p = maps[c].get(d); if (p != null) last[c] = p; });
    if (codes.some((c) => last[c] == null)) return;
    if (units) value = codes.reduce((a, c) => a + units[c] * last[c], 0);
    if (!units || (rebalWeeks && k % rebalWeeks === 0)) {
      units = Object.fromEntries(codes.map((c) => [c, (value * weights[c] / tw) / last[c]]));
    }
    out.d.push(d);
    out.v.push(value);
  });
  return out.d.length >= 2 ? out : null;
}

export function rebaseFrom(d, v, from) {
  const i0 = d.findIndex((x) => x >= from);
  if (i0 < 0) return null;
  const base = v.slice(i0).find((x) => x != null);
  return base ? { d: d.slice(i0), v: v.slice(i0).map((x) => (x == null ? null : (x / base) * 100)) } : null;
}

export function weeklyStats(s) {
  const pts = s.d.map((d, i) => [d, s.v[i]]).filter(([, v]) => v != null);
  if (pts.length < 2) return null;
  const first = pts[0][1], last = pts[pts.length - 1][1];
  const years = (Date.parse(pts[pts.length - 1][0]) - Date.parse(pts[0][0])) / (365.25 * 86400000);
  let peak = -Infinity, mdd = 0;
  for (const [, v] of pts) { peak = Math.max(peak, v); mdd = Math.min(mdd, (v / peak - 1) * 100); }
  const rets = pts.slice(1).map(([, v], i) => v / pts[i][1] - 1);
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
  const sd = Math.sqrt(rets.reduce((a, r) => a + (r - mean) ** 2, 0) / Math.max(1, rets.length - 1));
  const perYear = rets.length / Math.max(years, 1e-6);  // seri sıklığı (haftalık ~52, 2 aylık ~6)
  const cagr = years > 0.95 ? ((last / first) ** (1 / years) - 1) * 100 : null;
  return { total: (last / first - 1) * 100, cagr, mdd, vol: sd * Math.sqrt(perYear) * 100, from: pts[0][0] };
}

