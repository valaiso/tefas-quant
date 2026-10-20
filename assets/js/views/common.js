// Görünümler arası paylaşılan küçük parçalar

const QKEY = "tq-include-qualified";

export function includeQualified() {
  try {
    return localStorage.getItem(QKEY) === "1";  // varsayılan kapalı: nitelikli fonlar önerilmez
  } catch {
    return false;
  }
}

/** Nitelikli (serbest vb.) fonları dahil etme anahtarının HTML'i. */
export function qualifiedToggle() {
  return `<label class="switch"><input type="checkbox" data-qualified ${includeQualified() ? "checked" : ""}>
    <span class="switch-ui" aria-hidden="true"></span><span>Nitelikli yatırımcı fonlarını dahil et</span></label>`;
}

/** Anahtarı bağlar: tercihi saklar, sonra onChange'i çağırır. */
export function bindQualified(root, onChange) {
  root.querySelector("input[data-qualified]")?.addEventListener("change", (e) => {
    try {
      localStorage.setItem(QKEY, e.target.checked ? "1" : "0");
    } catch { /* özel pencere */ }
    onChange();
  });
}

/** Tablo satırına tıklayınca fon detayına git (içteki bağlantılar hariç). */
export function bindRows(root) {
  root.querySelectorAll("tr.row-link").forEach((tr) =>
    tr.addEventListener("click", (e) => {
      if (!e.target.closest("a, button, input")) location.hash = tr.dataset.href;
    }));
}
