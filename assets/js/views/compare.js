import { esc, num, pctCell, money, gradeBadge, trUpper, COMPONENT_LABELS, RETURN_LABELS } from "../util.js";
import { lineChart, rebase } from "../chart.js";

const MAX = 5;

export async function render(app, route, store) {
  const codes = (route.params.get("f") || "").split(",").map((s) => s.trim().toUpperCase())
    .filter((c) => store.byCode.has(c)).slice(0, MAX);
  const funds = codes.map((c) => store.byCode.get(c));
  const setCodes = (list) => { location.hash = `#/karsilastir?f=${list.join(",")}`; };

  // Satır: fn(f) sayı döndürürse fmt ile yazılır ve en iyi değer vurgulanır; metin döndürürse olduğu gibi.
  const R = (label, fn, best, fmt = (v) => v) => {
    const vals = funds.map(fn);
    const nums = vals.filter((v) => typeof v === "number" && isFinite(v));
    const target = best === "max" ? Math.max(...nums) : best === "min" ? Math.min(...nums) : null;
    return `<tr><td>${label}</td>${vals.map((v) => {
      const isBest = best && typeof v === "number" && v === target && nums.length > 1;
      return `<td class="${isBest ? "best" : ""}">${typeof v === "number" || v == null ? fmt(v) : v}</td>`;
    }).join("")}</tr>`;
  };
  const section = (title, rows) => `<tr class="group"><td colspan="${funds.length + 1}">${title}</td></tr>${rows.join("")}`;

  app.innerHTML = `
  <section class="card">
    <div class="card-head"><h2>Fon seç</h2><span class="sub">En fazla ${MAX} fon</span></div>
    <div class="picker">
      ${funds.map((f) => `<span class="chip">${esc(f.c)}<button data-remove="${esc(f.c)}" aria-label="${esc(f.c)} çıkar">×</button></span>`).join("")}
      ${funds.length < MAX ? `<span class="autocomplete"><input id="addFund" type="search" placeholder="Fon ekle…" autocomplete="off"><div class="ac-list" id="addList" hidden></div></span>` : ""}
    </div>
  </section>
  ${funds.length < 2 ? `<div class="card empty"><h3>Karşılaştırmak için en az iki fon seçin</h3>
     <p>Sıralama sayfasında satırlardaki kutucukları işaretleyebilir ya da yukarıdan fon ekleyebilirsiniz.</p></div>` : `
  <section class="card">
    <div class="card-head"><h2>Fiyat performansı</h2><span class="sub">Haftalık kapanış, ortak başlangıç = 100</span></div>
    <div class="chart" id="cmpChart"><div class="loading"><div class="spinner"></div></div></div>
  </section>
  <section class="card">
    <div class="table-wrap"><table class="compare">
      <thead><tr><th></th>${funds.map((f) => `<th><a href="#/fon/${encodeURIComponent(f.c)}" class="mono">${esc(f.c)}</a><div class="th-name">${esc(f.n)}</div></th>`).join("")}</tr></thead>
      <tbody>
        ${section("Derecelendirme", [
          R("Not", (f) => gradeBadge(f) + ` <span class="dim">${esc(f.sig)}</span>`),
          R("Final skor", (f) => f.s, "max", (v) => num(v, 1)),
          R("Kategori", (f) => esc(f.k)),
          R("Kategori sırası", (f) => `${f.rk} / ${f.ct}`),
          R("Toplam ceza", (f) => f.p.investor + f.p.outflow + f.p.anomaly, "min", (v) => (v ? "−" + num(v, 1) : "0")),
        ])}
        ${section("Bileşenler", Object.keys(COMPONENT_LABELS).map((k) => R(COMPONENT_LABELS[k], (f) => f.b[k], "max", (v) => num(v, 1))))}
        ${section("Getiri", Object.entries(RETURN_LABELS).map(([k, l]) => R(l, (f) => f.r[k], "max", (v) => pctCell(v))))}
        ${section("Risk", [
          R("Volatilite", (f) => f.m.vol, "min", (v) => `%${num(v, 1)}`),
          R("Maks. düşüş", (f) => f.m.mdd, "min", (v) => `−%${num(v, 1)}`),
          R("Sharpe", (f) => f.m.sharpe, "max", (v) => num(v)),
          R("Sortino", (f) => f.m.sortino, "max", (v) => num(v)),
          R("Alfa", (f) => f.m.alpha, "max", (v) => pctCell(v)),
        ])}
        ${section("Fon", [
          R("Büyüklük", (f) => f.aum, "max", money),
          R("Yatırımcı", (f) => f.inv, "max", (v) => num(v, 0)),
          R("1A yatırımcı değişimi", (f) => f.ig, "max", (v) => pctCell(v, 1)),
          R("Yönetim ücreti", (f) => f.fee, "min", (v) => `%${num(v)}`),
        ])}
      </tbody></table></div>
  </section>`}`;

  app.querySelectorAll("[data-remove]").forEach((b) =>
    b.addEventListener("click", () => setCodes(codes.filter((c) => c !== b.dataset.remove))));

  const input = app.querySelector("#addFund"), list = app.querySelector("#addList");
  input?.addEventListener("input", () => {
    const q = trUpper(input.value.trim());
    if (q.length < 2) { list.hidden = true; return; }
    const hits = store.funds.filter((f) => !codes.includes(f.c) && (f.c.includes(q) || trUpper(f.n).includes(q))).slice(0, 8);
    list.innerHTML = hits.map((f) => `<div class="ac-item" data-add="${esc(f.c)}"><b class="mono">${esc(f.c)}</b><span class="ac-name">${esc(f.n)}</span></div>`).join("")
      || `<div class="ac-item dim">Sonuç yok</div>`;
    list.hidden = false;
  });
  list?.addEventListener("click", (e) => {
    const it = e.target.closest("[data-add]");
    if (it) setCodes([...codes, it.dataset.add]);
  });

  if (funds.length >= 2) {
    const hists = await Promise.all(funds.map((f) => store.history(f.c)));
    const from = new Date(Date.parse(store.meta.lastDataDate) - 365 * 86400000).toISOString().slice(0, 10);
    const start = hists.filter(Boolean).map((h) => h.d.find((d) => d >= from) || h.d[0]).sort().pop();
    lineChart(app.querySelector("#cmpChart"),
      funds.map((f, i) => (hists[i] ? { name: f.c, ...rebase(hists[i].d, hists[i].p, start) } : null)).filter(Boolean),
      { base: 100, format: (v) => num(v, 0) });
  }
}
