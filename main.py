import os

dosya_adi = "generate_history_scores.py"
print(f"-> {dosya_adi} içeriği inceleniyor...\n")

if os.path.exists(dosya_adi):
    with open(dosya_adi, "r", encoding="utf-8") as f:
        print(f.read())
else:
    print(f"⚠️ {dosya_adi} bulunamadı. Lütfen klasördeki dosyaları kontrol edin.")