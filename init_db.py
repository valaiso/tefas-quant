from database.database import engine, Base
from database.models import Fund, FundDailyPrice, FundScore

def init_database():
    print("SQLite veritabanı tabloları oluşturuluyor...")
    # SQLAlchemy modellerini tarayarak eksik tabloları SQLite veritabanına yazar
    Base.metadata.create_all(bind=engine)
    print("İşlem tamam! Tablolar başarıyla oluşturuldu.")

if __name__ == "__main__":
    init_database()