// Biçimlendirme ve küçük DOM yardımcıları

const nf = (d) => new Intl.NumberFormat("tr-TR", { minimumFractionDigits: d, maximumFractionDigits: d });
const NF0 = nf(0), NF1 = nf(1), NF2 = nf(2);

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const num = (v, d = 2) => (v == null || !isFinite(v) ? "—" : (d === 0 ? NF0 : d === 1 ? NF1 : NF2).format(v));

export const pct = (v, d = 2) => (v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : ""}${num(v, d)}%`);

export const tone = (v) => (v == null || !isFinite(v) || v === 0 ? "" : v > 0 ? "up" : "down");

export const pctCell = (v, d = 2) => `<span class="${tone(v)}">${pct(v, d)}</span>`;

export function money(v) {
  if (v == null || !isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `${num(v / 1e9, 1)} mr ₺`;
  if (a >= 1e6) return `${num(v / 1e6, 1)} mn ₺`;
  if (a >= 1e3) return `${num(v / 1e3, 0)} bin ₺`;
  return `${num(v, 0)} ₺`;
}

export function dateTR(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

const MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];
export const monthLabel = (iso) => `${MONTHS[+iso.slice(5, 7) - 1]} ${iso.slice(2, 4)}`;

export const SIGNALS = [
  { key: "GÜÇLÜ AL", grade: "A+", cls: "sig-aplus" },
  { key: "AL", grade: "A", cls: "sig-a" },
  { key: "İZLE", grade: "B", cls: "sig-b" },
  { key: "ZAYIF", grade: "C", cls: "sig-c" },
  { key: "UZAK DUR", grade: "D", cls: "sig-d" },
];

const SIG_CLASS = Object.fromEntries(SIGNALS.map((s) => [s.key, s.cls]));

export const gradeBadge = (f) =>
  `<span class="grade ${SIG_CLASS[f.sig] || ""}" title="${esc(f.sig)}">${esc(f.g)}</span>`;

export const signalPill = (sig) => `<span class="signal ${SIG_CLASS[sig] || ""}">${esc(sig)}</span>`;

export const codeChip = (code) => `<a class="code-chip" href="#/fon/${encodeURIComponent(code)}">${esc(code)}</a>`;

export function scoreBar(v) {
  const w = Math.max(0, Math.min(100, v ?? 0));
  return `<span class="scorebar"><i style="width:${w}%"></i></span><span class="num">${num(v, 1)}</span>`;
}

export const COMPONENT_LABELS = {
  performance: "Performans",
  risk: "Risk",
  investor: "Yatırımcı & Akış",
  cost: "Maliyet",
  portfolio: "Portföy Kalitesi",
};

export const RETURN_LABELS = { "1g": "1 Gün", "1a": "1 Ay", "2a": "2 Ay", "3a": "3 Ay", "6a": "6 Ay", "1y": "1 Yıl", "3y": "3 Yıl" };

export function debounce(fn, ms = 200) {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}

export const trUpper = (s) => String(s ?? "").toLocaleUpperCase("tr-TR");

/**
 * Fon arama: kod yazılanla başlıyorsa en üstte, sonra kodda geçenler, sonra
 * ünvanda kelime başı eşleşenler, en son ünvanın herhangi bir yerinde geçenler.
 * Aynı gruptakiler skora göre sıralanır.
 */
export function searchFunds(funds, query, { limit = 10, exclude = [] } = {}) {
  const q = trUpper(query.trim());
  if (!q) return [];
  const skip = new Set(exclude);
  const rank = (f) => {
    if (f.c.startsWith(q)) return 0;
    if (f.c.includes(q)) return 1;
    const name = trUpper(f.n);
    if (name.split(/\s+/).some((w) => w.startsWith(q))) return 2;
    if (name.includes(q)) return 3;
    return -1;
  };
  return funds
    .filter((f) => !skip.has(f.c))
    .map((f) => [rank(f), f])
    .filter(([r]) => r >= 0)
    .sort((a, b) => a[0] - b[0] || (b[1].s ?? 0) - (a[1].s ?? 0))
    .slice(0, limit)
    .map(([, f]) => f);
}
