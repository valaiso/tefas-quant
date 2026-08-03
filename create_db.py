import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

try:
    # PostgreSQL varsayılan 'postgres' veritabanına bağlanıyoruz
    connection = psycopg2.connect(
        user="postgres",
        password="1234",  # Kendi PostgreSQL şifreniz
        host="localhost",
        port="5432",
        database="postgres"
    )
    connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = connection.cursor()

    # tefas_db veritabanını oluşturuyoruz
    cursor.execute("CREATE DATABASE tefas_db;")
    print("✅ Başarılı: 'tefas_db' veritabanı oluşturuldu!")

    cursor.close()
    connection.close()
except Exception as e:
    print("ℹ️ Bilgi / Hata:", e)