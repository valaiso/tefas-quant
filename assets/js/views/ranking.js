import { esc, num, pctCell, money, gradeBadge, codeChip, scoreBar, SIGNALS, trUpper, debounce } from "../util.js";
import { qualifiedToggle, includeQualified, bindQualified, bindRows } from "./common.js";

const PAGE = 50;
const COLUMNS = [
  { key: "rk", label: "Sıra", get: (f) => f.rk, title: "Kategori içi sıra" },
  { key: "c", label: "Fon", get: (f) => f.c, left: true },
  { key: "k", label: "Kategori", get: (f) => f.k, left: true },
  { key: "g", label: "Not", get: (f) => f.s },
  { key: "s", label: "Skor", get: (f) => f.s },
  { key: "r1a", label: "1 Ay", get: (f) => f.r["1a"] },
  { key: "r3a", label: "3 Ay", get: (f) => f.r["3a"] },
  { key: "r1y", label: "1 Yıl", get: (f) => f.r["1y"] },
  { key: "r3y", label: "3 Yıl", get: (f) => f.r["3y"] },
  { key: "vol", label: "Volatilite", get: (f) => f.m.vol },
  { key: "sh", label: "Sharpe", get: (f) => f.m.sharpe },
  { key: "inv", label: "Yatırımcı", get: (f) => f.inv },
  { key: "aum", label: "Büyüklük", get: (f) => f.aum },
  { key: "pen", label: "Ceza", get: (f) => penalty(f), title: "Toplam ceza puanı" },
];

const penalty = (f) => (f.p.investor || 0) + (f.p.outflow || 0) + (f.p.anomaly || 0);

const state = { q: "", cat: "", sig: "", sort: "s", dir: -1, page: 0, picked: new Set() };

export function render(app, route, store) {
  if (route.params.has("sig")) state.sig = route.params.get("sig");
  if (route.params.has("k")) state.cat = route.params.get("k");
  const cats = [...new Set(store.funds.map((f) => f.k))].sort((a, b) => a.localeCompare(b, "tr"));

  app.innerHTML = `
  <section class="card filters">
    <div class="filter-grid">
      <label class="field"><span>Ara</span><input id="fq" type="search" placeholder="Kod veya ünvan" value="${esc(state.q)}"></label>
      <label class="field"><span>Kategori</span><select id="fcat"><option value="">Tüm kategoriler</option>
        ${cats.map((c) => `<option ${c === state.cat ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>
      <label class="field"><span>Sinyal</span><select id="fsig"><option value="">Tüm notlar</option>
        ${SIGNALS.map((s) => `<option value="${s.key}" ${s.key === state.sig ? "selected" : ""}>${s.grade} · ${s.key}</option>`).join("")}</select></label>
      <div class="field field-end">${qualifiedToggle()}</div>
    </div>
  </section>
  <section class="card">
    <div class="card-head">
      <h2 id="rcount">—</h2>
      <div class="btn-row">
        <button class="btn btn-sm" id="clearPick" hidden>Seçimi temizle</button>
        <a class="btn btn-sm btn-primary" id="goCompare" hidden>Karşılaştır</a>
      </div>
    </div>
    <div class="table-wrap"><table class="ranking">
      <thead><tr><th class="pick"></th>${COLUMNS.map((c) =>
        `<th class="sortable ${c.left ? "left" : ""}" data-key="${c.key}" ${c.title ? `title="${c.title}"` : ""}>${c.label}<span class="sort-ind"></span></th>`).join("")}</tr></thead>
      <tbody id="rbody"></tbody>
    </table></div>
    <div class="pagination" id="rpager"></div>
  </section>`;

  const body = app.querySelector("#rbody");
  const draw = () => {
    const q = trUpper(state.q.trim());
    let rows = store.funds.filter((f) =>
      (includeQualified() || !f.q) &&
      (!state.cat || f.k === state.cat) &&
      (!state.sig || f.sig === state.sig) &&
      (!q || f.c.includes(q) || trUpper(f.n).includes(q)));
    const col = COLUMNS.find((c) => c.key === state.sort);
    rows.sort((a, b) => {
      const x = col.get(a), y = col.get(b);
      if (x == null) return 1;
      if (y == null) return -1;
      return (typeof x === "string" ? x.localeCompare(y, "tr") : x - y) * state.dir;
    });
    const pages = Math.max(1, Math.ceil(rows.length / PAGE));
    state.page = Math.min(state.page, pages - 1);
    const slice = rows.slice(state.page * PAGE, state.page * PAGE + PAGE);

    app.querySelector("#rcount").textContent = `${num(rows.length, 0)} fon`;
    body.innerHTML = slice.map((f) => `
      <tr class="row-link" data-href="#/fon/${encodeURIComponent(f.c)}">
        <td class="pick"><input type="checkbox" data-code="${esc(f.c)}" ${state.picked.has(f.c) ? "checked" : ""} aria-label="${esc(f.c)} karşılaştır"></td>
        <td class="num"><b>${f.rk}</b><span class="dim">/${f.ct}</span></td>
        <td class="fund-cell left">${codeChip(f.c)}<span class="name">${esc(f.n)}</span></td>
        <td class="left dim cat-cell">${esc(f.k)}</td>
        <td>${gradeBadge(f)}</td>
        <td class="score-cell">${scoreBar(f.s)}</td>
        <td>${pctCell(f.r["1a"])}</td><td>${pctCell(f.r["3a"])}</td><td>${pctCell(f.r["1y"])}</td><td>${pctCell(f.r["3y"])}</td>
        <td>%${num(f.m.vol, 1)}</td><td>${num(f.m.sharpe)}</td>
        <td>${num(f.inv, 0)}</td><td>${money(f.aum)}</td>
        <td class="${penalty(f) > 0 ? "down" : "dim"}">${penalty(f) > 0 ? "−" + num(penalty(f), 1) : "—"}</td>
      </tr>`).join("") || `<tr><td colspan="${COLUMNS.length + 1}" class="empty">Filtreye uyan fon yok</td></tr>`;

    app.querySelectorAll("th.sortable").forEach((th) => {
      th.querySelector(".sort-ind").textContent = th.dataset.key === state.sort ? (state.dir < 0 ? " ↓" : " ↑") : "";
    });
    app.querySelector("#rpager").innerHTML = `<span class="dim">Sayfa ${state.page + 1} / ${pages}</span>
      <div class="pagination-controls">
        <button class="btn btn-sm" data-page="-1" ${state.page === 0 ? "disabled" : ""}>← Önceki</button>
        <button class="btn btn-sm" data-page="1" ${state.page >= pages - 1 ? "disabled" : ""}>Sonraki →</button>
      </div>`;
    syncPicked();
    bindRows(body);
  };

  const syncPicked = () => {
    const n = state.picked.size;
    const go = app.querySelector("#goCompare");
    go.hidden = n < 2;
    go.textContent = `Karşılaştır (${n})`;
    go.href = `#/karsilastir?f=${[...state.picked].join(",")}`;
    app.querySelector("#clearPick").hidden = n === 0;
  };

  app.querySelector("#fq").addEventListener("input", debounce((e) => { state.q = e.target.value; state.page = 0; draw(); }, 150));
  app.querySelector("#fcat").addEventListener("change", (e) => { state.cat = e.target.value; state.page = 0; draw(); });
  app.querySelector("#fsig").addEventListener("change", (e) => { state.sig = e.target.value; state.page = 0; draw(); });
  bindQualified(app, () => { state.page = 0; draw(); });
  app.querySelectorAll("th.sortable").forEach((th) => th.addEventListener("click", () => {
    const key = th.dataset.key;
    state.dir = state.sort === key ? -state.dir : (["rk", "c", "k", "vol", "pen"].includes(key) ? 1 : -1);
    state.sort = key;
    draw();
  }));
  app.querySelector("#rpager").addEventListener("click", (e) => {
    const b = e.target.closest("[data-page]");
    if (b) { state.page += +b.dataset.page; draw(); app.querySelector(".table-wrap").scrollIntoView({ block: "start" }); }
  });
  body.addEventListener("change", (e) => {
    const cb = e.target.closest("input[data-code]");
    if (!cb) return;
    if (cb.checked && state.picked.size >= 5) { cb.checked = false; return; }
    cb.checked ? state.picked.add(cb.dataset.code) : state.picked.delete(cb.dataset.code);
    syncPicked();
  });
  app.querySelector("#clearPick").addEventListener("click", () => { state.picked.clear(); draw(); });
  draw();
}
