import os

def create_database():
    print("SQLite veritabanı yapısı kontrol ediliyor...")
    # database klasörünün var olduğundan emin olalım
    os.makedirs("database", exist_ok=True)
    print("✅ Başarılı: SQLite veritabanı dizini hazır!")

if __name__ == "__main__":
    create_database()