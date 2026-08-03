from sqlalchemy import create_engine

DATABASE_URL = "sqlite:///database/fonlar.db"

engine = create_engine(DATABASE_URL)

print("Database bağlantısı hazır")