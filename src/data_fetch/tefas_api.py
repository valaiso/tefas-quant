import requests


url = "https://www.tefas.gov.tr/api/DB/BindHistoryInfo"


headers = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.tefas.gov.tr/"
}


data = {
    "fontip": "YAT",
    "bastarih": "01.08.2026",
    "bittarih": "02.08.2026",
    "fonkod": "",
    "sfontur": "",
    "fonunvan": ""
}


r = requests.post(
    url,
    headers=headers,
    data=data
)


print(r.status_code)
print(r.text[:1000])