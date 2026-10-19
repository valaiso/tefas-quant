/* Aylık kişisel portföy raporu hesabı: Analiz'in rapor hesaplamasının (assets/js/report.js) TEFAS Quant kopyası.
   Kaynaklar Analiz hesabındaki durumdur: günlük toplamlar (valueHistory), para giriş/çıkışları (cashflows),
   temettüler (dividends) ve ay sonu pozisyon fotoğrafları (monthlySnapshots). Kıyaslar Analiz'in yayımladığı
   serilerden (BIST 100, S&P 500 TL, gram altın, dolar, PPF, TÜFE) gelir. Kurallar Analiz ile aynı tutulur. */

const MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
export const monthLabel = (month) => `${MONTHS[Number(month.slice(5, 7)) - 1]} ${month.slice(0, 4)}`;
const FROZEN_FUND_CODES = new Set(["THF", "TP2"]);

export const BENCHMARK_ORDER = [
  ["BIST100", "BIST 100"],
  ["SP500TL", "S&P 500 (TL)"],
  ["GRAMALTIN", "Gram Altın"],
  ["USDTRY", "Dolar/TL"],
  ["PARAPIYASASI", "PPF Ortalaması"],
  ["TUFE", "Enflasyon (TÜFE)"],
];

const previousMonth = (month) => {
  const date = new Date(`${month}-01T12:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() - 1);
  return date.toISOString().slice(0, 7);
};
export const istanbulMonth = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Istanbul", year: "numeric", month: "2-digit" })
  .format(new Date()).slice(0, 7);

/** Raporu hazırlanabilecek aylar (yeniden eskiye). */
export function reportMonths(history, snapshots) {
  const months = new Set([...Object.keys(history || {}).map((d) => d.slice(0, 7)), ...Object.keys(snapshots || {})]);
  return [...months].sort().reverse();
}
/** Varsayılan rapor ayı: biten son ay (ayın başında e-postayla giden rapor), yoksa süren ay. */
export function defaultMonth(history, snapshots) {
  const now = istanbulMonth();
  const months = reportMonths(history, snapshots);
  return months.find((m) => m < now) || months[0] || now;
}

function idxOn(cal, iso) {
  let lo = 0, hi = cal.length - 1, ans = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (cal[m] <= iso) { ans = m; lo = m + 1; } else hi = m - 1; }
  return ans;
}

export function realReturn(history, flows) {
  const dates = Object.keys(history || {}).filter((date) => Number(history[date]) > 0).sort();
  if (!dates.length) return null;
  const flowsBetween = (after, upTo) => (flows || []).filter((f) => f.date > after && f.date <= upTo)
    .reduce((sum, f) => sum + (Number(f.amount) || 0), 0);
  let growth = 1;
  for (let i = 1; i < dates.length; i += 1) {
    const flow = flowsBetween(dates[i - 1], dates[i]);
    const previous = history[dates[i - 1]];
    if (previous > 0) growth *= (history[dates[i]] - flow) / previous;
  }
  return { dates, twr: dates.length > 1 ? (growth - 1) * 100 : null };
}

function fundStopajRate(meta) {
  const name = String(meta?.name || "").toLocaleUpperCase("tr");
  const bist = Number(meta?.alloc?.["Hisse Senedi"]) || 0;
  if (name.includes("HİSSE SENEDİ YOĞUN") || bist >= 80) return 0;
  return 0.175;
}

const realOf = (nominal, inflation) => (Number.isFinite(nominal) && Number.isFinite(inflation)
  ? ((1 + nominal / 100) / (1 + inflation / 100) - 1) * 100 : null);

function periodReturn(history, flows, dividends, fromDate, toDate) {
  const dates = Object.keys(history).filter((d) => d >= fromDate && d <= toDate).sort();
  if (dates.length < 2) return null;
  const real = realReturn(Object.fromEntries(dates.map((d) => [d, history[d]])), flows);
  const startDate = dates[0], endDate = dates.at(-1);
  const inPeriod = (item) => item.date > startDate && item.date <= endDate;
  const deposits = flows.filter((f) => inPeriod(f) && f.amount > 0).reduce((s, f) => s + f.amount, 0);
  const withdrawals = flows.filter((f) => inPeriod(f) && f.amount < 0).reduce((s, f) => s - f.amount, 0);
  const dividendTotal = dividends.filter(inPeriod).reduce((s, d) => s + d.amount, 0);
  const startValue = history[startDate], endValue = history[endDate];
  return { startDate, endDate, startValue, endValue, twr: real?.twr ?? null, deposits, withdrawals, dividends: dividendTotal,
    market: endValue - startValue - deposits + withdrawals - dividendTotal, dates };
}

function portfolioIndex(history, flows, dates) {
  let level = 100, peak = 100, maxDrawdown = 0;
  const index = dates.map((date, i) => {
    if (i > 0) {
      const flow = flows.filter((f) => f.date > dates[i - 1] && f.date <= date).reduce((s, f) => s + f.amount, 0);
      const previous = history[dates[i - 1]];
      if (previous > 0) level *= (history[date] - flow) / previous;
    }
    peak = Math.max(peak, level);
    maxDrawdown = Math.min(maxDrawdown, (level / peak - 1) * 100);
    return level;
  });
  return { index, maxDrawdown };
}

/** input: { month, history, flows, dividends, snapshots, az: {cal, bench, meta} } */
export function buildMonthlyReport({ month, history = {}, flows = [], dividends = [], snapshots = {}, az }) {
  const benchAt = (key, date) => {
    const values = az.bench?.[key]?.values || [];
    for (let i = idxOn(az.cal, date); i >= 0; i -= 1) if (values[i] > 0) return values[i];
    return null;
  };
  const benchmarkReturn = (key, from, to) => { const s = benchAt(key, from), e = benchAt(key, to); return s > 0 && e > 0 ? (e / s - 1) * 100 : null; };
  const benchmarkIndex = (key, dates) => {
    const raw = dates.map((d) => benchAt(key, d));
    const base = raw.find((v) => v > 0);
    return raw.map((v) => (base && v > 0 ? (v / base) * 100 : null));
  };

  const monthDates = Object.keys(history).filter((d) => d.startsWith(month)).sort();
  const priorDates = Object.keys(history).filter((d) => d < `${month}-01`).sort();
  const fromDate = priorDates.at(-1) || monthDates[0];
  const toDate = monthDates.at(-1);
  const firstDate = Object.keys(history).sort()[0];
  const yearStart = Object.keys(history).filter((d) => d < `${month.slice(0, 4)}-01-01`).sort().at(-1) || firstDate;
  const complete = month < istanbulMonth();

  const periods = {
    month: fromDate && toDate ? periodReturn(history, flows, dividends, fromDate, toDate) : null,
    ytd: yearStart && toDate ? periodReturn(history, flows, dividends, yearStart, toDate) : null,
    inception: firstDate && toDate ? periodReturn(history, flows, dividends, firstDate, toDate) : null,
  };
  const comparison = BENCHMARK_ORDER.map(([key, label]) => {
    const row = { key, label };
    for (const [name, period] of Object.entries(periods)) row[name] = period ? benchmarkReturn(key, period.startDate, period.endDate) : null;
    return row;
  }).filter((row) => az.bench?.[row.key]);
  const inflation = comparison.find((row) => row.key === "TUFE") || {};
  const portfolioRow = { key: "PORTFOY", label: "Portföyüm", month: periods.month?.twr ?? null, ytd: periods.ytd?.twr ?? null, inception: periods.inception?.twr ?? null };
  const comparisonRows = [portfolioRow, ...comparison].map((row) => ({
    ...row,
    realMonth: row.key === "TUFE" ? null : realOf(row.month, inflation.month),
    realInception: row.key === "TUFE" ? null : realOf(row.inception, inflation.inception),
  }));

  const chartDates = periods.month?.dates || [];
  const portfolio = portfolioIndex(history, flows, chartDates);
  const chartSeries = [
    { key: "PORTFOY", label: "Portföyüm", values: portfolio.index },
    ...comparison.filter((r) => r.key !== "TUFE").map((r) => ({ key: r.key, label: r.label, values: benchmarkIndex(r.key, chartDates) })),
  ];

  const end = snapshots[month] || null;
  const start = snapshots[previousMonth(month)] || null;
  const startByCode = new Map((start?.rows || []).map((row) => [row.code, row]));
  const endTotal = end?.total || periods.month?.endValue || 0;
  const positions = (end?.rows || []).map((row) => {
    const before = startByCode.get(row.code);
    const monthPct = !row.frozen && before?.unitTRY > 0 && row.unitTRY > 0 ? (row.unitTRY / before.unitTRY - 1) * 100 : null;
    const heldUnits = before ? Math.min(before.units || 0, row.units || 0) : 0;
    const contribution = row.frozen ? 0 : before?.unitTRY > 0 && row.unitTRY > 0 ? heldUnits * (row.unitTRY - before.unitTRY) : null;
    return { ...row, name: az.meta.get(row.code)?.name || "", weight: endTotal > 0 ? (row.value / endTotal) * 100 : null,
      startWeight: start?.total > 0 && before ? (before.value / start.total) * 100 : null, monthPct, contribution };
  }).sort((a, b) => b.value - a.value);
  const cash = end?.cash || 0;

  const groupKey = (row) => (row.group === "Fon" ? `Fon · ${String(row.label || "Diğer").split(" · ")[0]}` : row.group);
  const groups = new Map();
  for (const row of positions) groups.set(groupKey(row), (groups.get(groupKey(row)) || 0) + row.value);
  if (cash > 0.5) groups.set("Nakit", cash);
  const startGroups = new Map();
  for (const row of start?.rows || []) startGroups.set(groupKey(row), (startGroups.get(groupKey(row)) || 0) + row.value);
  if (start?.cash > 0.5) startGroups.set("Nakit", start.cash);
  const allocation = [...groups.entries()].sort((a, b) => b[1] - a[1]).map(([label, value]) => ({
    label, value, weight: endTotal > 0 ? (value / endTotal) * 100 : null,
    startWeight: start?.total > 0 && startGroups.has(label) ? (startGroups.get(label) / start.total) * 100 : null,
  }));

  const ranked = positions.filter((row) => Number.isFinite(row.contribution) && !row.frozen);
  const winners = [...ranked].sort((a, b) => b.contribution - a.contribution).filter((r) => r.contribution > 0).slice(0, 3);
  const losers = [...ranked].sort((a, b) => a.contribution - b.contribution).filter((r) => r.contribution < 0).slice(0, 3);

  const weights = positions.map((row) => row.weight || 0).sort((a, b) => b - a);
  const largest = positions[0] || null;
  const risk = {
    maxDrawdown: chartDates.length > 1 ? portfolio.maxDrawdown : null,
    largestCode: largest?.code || null, largestWeight: largest?.weight ?? null,
    top3Weight: weights.slice(0, 3).reduce((s, v) => s + v, 0), positionCount: positions.length,
  };
  const stopajTotal = positions.filter((row) => row.group === "Fon" && !FROZEN_FUND_CODES.has(row.code) && row.totalPLTRY > 0)
    .reduce((s, row) => s + row.totalPLTRY * fundStopajRate(az.meta.get(row.code)), 0);

  return {
    month, label: monthLabel(month), complete, fromDate, toDate, firstDate,
    periods, comparisonRows, inflation, chart: { dates: chartDates, series: chartSeries },
    positions, cash, endTotal, allocation, winners, losers, risk, stopajTotal,
    frozenCodes: positions.filter((row) => row.frozen).map((row) => row.code),
    hasSnapshot: Boolean(end), hasStartSnapshot: Boolean(start),
  };
}
