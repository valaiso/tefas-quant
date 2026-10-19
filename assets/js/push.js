// Aylık rapor bildirimleri (Web Push). Açılıp kapatılmaz: ayın 1'i ve son günü 09:00 ve 18:00'de gelir.
// iPhone bildirime yalnızca ana ekrana eklenmiş uygulamada ve bir düğmeye basınca izin verdirir; bu yüzden
// ana ekran uygulamasında, kurulum bitene kadar bir kerelik kart görünür. Abonelik Analiz hesabına
// (Supabase push_subscriptions, app: "tefas-quant") yazılır; gönderimi Analiz deposundaki GitHub işi yapar.
import { supabaseClient } from "./supabase.js";

const VAPID_PUBLIC_KEY = "BCqEzXeK-J1lFgWvYoOmd1SnveNzmq1L-Ch_IalHNbSeRc79o0fJ7bUAIbMn42ZAcqc0wqfOHMzW4gmN2AZ6yQQ";
const BASE = new URL("./", location.href).pathname;  // /tefas-quant/
const APP = "tefas-quant";

const supported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const standalone = () => matchMedia?.("(display-mode: standalone)").matches || navigator.standalone === true;

function keyToBytes(b64) {
  const s = `${b64}${"=".repeat((4 - (b64.length % 4)) % 4)}`.replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}
const register = () => navigator.serviceWorker.register(`${BASE}sw.js`, { scope: BASE, updateViaCache: "none" });

async function save(sb, sub) {
  const { data: { user } } = await sb.auth.getUser();
  if (!user) throw new Error("Önce Analiz hesabınla giriş yap.");
  const { error } = await sb.from("push_subscriptions").upsert({
    user_id: user.id, endpoint: sub.endpoint, subscription: { ...sub.toJSON(), app: APP }, updated_at: new Date().toISOString(),
  }, { onConflict: "endpoint" });
  if (error) throw new Error(`Abonelik kaydedilemedi: ${error.message}`);
}

async function enable(sb) {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Bildirim izni verilmedi.");
  const reg = await register();
  await navigator.serviceWorker.ready;
  const sub = (await reg.pushManager.getSubscription())
    || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyToBytes(VAPID_PUBLIC_KEY) }));
  await save(sb, sub);
}

/** Uygulama açılışında: izin verilmişse aboneliği hesaba yeniden yazar, değilse kurulum kartını gösterir. */
export async function initPush() {
  const box = document.getElementById("pushSetup");
  if (!box || !supported()) return;
  register().then((r) => r.update()).catch(() => {});
  if (!standalone()) return;  // bildirim yalnızca ana ekran uygulamasında
  let sb;
  try { sb = await supabaseClient(); } catch { return; }
  const { data: { session } } = await sb.auth.getSession();

  if (Notification.permission === "granted" && session) {
    const reg = await navigator.serviceWorker.getRegistration(BASE);
    const sub = await reg?.pushManager.getSubscription();
    if (sub) {
      // iPhone aboneliği yenileyebilir; her açılışta hesaba yeniden yazılır
      save(sb, sub).catch((e) => console.warn(e));
      box.hidden = true;
      return;
    }
  }
  const show = (inner) => {
    box.innerHTML = `<section class="card push-card"><h2>Aylık rapor bildirimleri</h2>
      <p>Ayın 1'inde (raporlar bugün gelecek / gönderildi) ve ayın son gününde (raporlar yarın gelecek) saat 09:00 ve 18:00'de
      telefonuna bildirim gelir. Kurulum bir kez yapılır; bitince bu kart kaybolur.</p>${inner}</section>`;
    box.hidden = false;
  };

  if (Notification.permission === "denied") {
    show(`<p class="dim">Bildirim izni kapalı. iPhone Ayarlar → Bildirimler → TEFAS Quant bölümünden izin ver, sonra uygulamayı yeniden aç.</p>`);
    return;
  }
  if (!session) {
    show(`<form class="push-login" id="pushLogin">
        <label>E-posta<input id="pushEmail" type="email" autocomplete="username" required></label>
        <label>Parola<input id="pushPass" type="password" autocomplete="current-password" required></label>
        <button class="btn btn-primary" type="submit">Analiz hesabınla giriş yap</button>
        <p class="push-err" id="pushErr" hidden></p></form>`);
    box.querySelector("#pushLogin").addEventListener("submit", async (e) => {
      e.preventDefault();
      const err = box.querySelector("#pushErr");
      const { error } = await sb.auth.signInWithPassword({ email: box.querySelector("#pushEmail").value.trim(), password: box.querySelector("#pushPass").value });
      if (error) {
        err.textContent = /invalid login/i.test(error.message) ? "E-posta veya parola doğru değil." : error.message;
        err.hidden = false;
        return;
      }
      initPush();
    });
    return;
  }
  show(`<button class="btn btn-primary" id="pushOn" type="button">Bildirimlere izin ver</button><p class="push-err" id="pushErr" hidden></p>`);
  box.querySelector("#pushOn").addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      await enable(sb);
      box.innerHTML = `<section class="card push-card"><p><b>Bildirimler kuruldu.</b> Ayın 1'i ve son günü 09:00 ve 18:00'de gelecek.</p></section>`;
      setTimeout(() => (box.hidden = true), 4000);
    } catch (x) {
      const err = box.querySelector("#pushErr");
      err.textContent = x.message;
      err.hidden = false;
      e.target.disabled = false;
    }
  });
}
