// Analiz hesabının Supabase istemcisi (tek örnek). Tarayıcı anahtarı herkese açıktır; veriyi RLS korur.
// Aynı kökende (valaiso.github.io) Analiz'in oturumu paylaşılır; ana ekran uygulamasında ayrı oturum açılır.
export const SUPABASE_URL = "https://jqmfvinbzgqyitqquzdc.supabase.co";
export const SUPABASE_KEY = "sb_publishable_uw979hCwS6xyLRTexQX55A_ZqgWidDs";

let client = null;
export function supabaseClient() {
  return (client ||= import("https://esm.sh/@supabase/supabase-js@2.117.2").then(({ createClient }) =>
    createClient(SUPABASE_URL, SUPABASE_KEY, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false } })));
}
