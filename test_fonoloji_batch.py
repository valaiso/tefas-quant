import requests
import sqlite3
import time


API_KEY = "fon_X1OyzL474C5DeMWSQ7_VOO0k-twPlfDK"

DB = "tefas.db"


headers = {
    "X-API-Key": API_KEY
}


conn = sqlite3.connect(DB)
cursor = conn.cursor()


cursor.execute("""
SELECT code 
FROM funds
WHERE status='ACTIVE'
LIMIT 20
""")


funds = cursor.fetchall()


print("TEST FON SAYISI:", len(funds))

success = 0
failed = 0


for row in funds:

    code = row[0]

    url = f"https://fonoloji.com/v1/funds/{code}"


    try:

        r = requests.get(
            url,
            headers=headers,
            timeout=20
        )


        if r.status_code == 200:

            data = r.json()

            fund = data.get("fund", {})

            print(
                "OK",
                code,
                "|",
                fund.get("name","")[:40]
            )

            success += 1


        else:

            print(
                "ERROR",
                code,
                r.status_code,
                r.text[:100]
            )

            failed += 1


    except Exception as e:

        print(
            "EXCEPTION",
            code,
            e
        )

        failed += 1


    time.sleep(1)


print("\nSONUC")
print("BAŞARILI:", success)
print("HATALI:", failed)


conn.close()