import os
import json
from openai import OpenAI

# Not: API anahtarını ortam değişkeninden (environment variable) veya doğrudan buraya ekleyebilirsin.
# Örn: os.environ["OPENAI_API_KEY"] = "senin_api_anahtarin"
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def generate_fund_analysis(metrics_json: dict) -> dict:
    """
    Python tarafında hesaplanan deterministik metrikleri alır,
    Yapay Zeka (Explainable AI) katmanından yapılandırılmış JSON yorum üretir.
    """
    
    system_prompt = """
    Sen kıdemli bir Quant Finans Analistisin. Asla matematiksel hesaplama yapmazsın.
    Görevin, sana verilen tamamen doğrulanmış sayısal verileri okumak ve yatırımcı için 
    tarafsız, profesyonel, açıklanabilir bir analiz raporuna dönüştürmektir.
    
    ASLA halüsinasyon görme, dışarıdan veri uydurma. Sadece verilen metrikleri yorumla.
    Çıktıyı KESİNLİKLE şu JSON formatında ver, başka hiçbir metin ekleme:
    {
      "summary": "Genel piyasa durumu ve fonun konumu hakkında 2 cümlelik özet.",
      "strengths": ["Güçlü yön 1", "Güçlü yön 2"],
      "risks": ["Risk 1", "Risk 2"],
      "score_explanation": "Fonun bu skoru almasının matematiksel gerekçesi.",
      "portfolio_fit": "Portföy çeşitlendirmesi ve risk profili uyumu hakkında yorum.",
      "educational_note": "Metrikler içinden seçilen bir kavramın (örn: Sharpe veya Alpha) kısa eğitimi.",
      "conclusion": "Yatırımcı profili için sonuç cümlesi."
    }
    """

    user_message = f"İşte fonun kesinleşmiş analitik verileri:\n{json.dumps(metrics_json, ensure_ascii=False, indent=2)}"

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", # Hızlı, ekonomik ve yapılandırılmış çıktıda çok başarılı
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            response_format={"type": "json_object"},
            temperature=0.2 # Yaratıcılığı kıs, tamamen mantıksal ve tutarlı ol
        )
        
        result_content = response.choices[0].message.content
        return json.loads(result_content)
        
    except Exception as e:
        # API anahtarı girilmediyse veya hata alırsak sistemi kilitlememek için güvenli fallback dön
        return {
            "summary": "Yapay zeka analiz katmanı geçici olarak erişilemez durumda, ancak skorlar matematiksel olarak geçerlidir.",
            "strengths": ["Yüksek Matematiksel Skor", "Deterministik Altyapı"],
            "risks": ["API bağlantısı kontrol edilmeli"],
            "score_explanation": f"Skor {metrics_json.get('score', 0)} olarak hesaplanmıştır.",
            "portfolio_fit": "Veri tabanı ile uyumlu.",
            "educational_note": "Matematik karar verir.",
            "conclusion": "Analiz tamamlandı."
        }