import requests
import json
import re

url = "https://www.tefas.gov.tr/tr/tefas-fonlar"

t = requests.get(url).text

start = t.find('mappedData')

if start == -1:
    print("mappedData bulunamadı")
    exit()

# mappedData'dan sonraki kısmı al
part = t[start:]

# sadece name-code-founder objelerini yakala
pattern = r'\{\\"name\\":\\"(.*?)\\",\\"code\\":\\"(.*?)\\",\\"founder\\":\\"(.*?)\\"'

data = re.findall(pattern, part)

funds = []

for name, code, founder in data:
    funds.append({
        "name": name,
        "code": code,
        "founder": founder
    })

with open("funds.json","w",encoding="utf-8") as f:
    json.dump(funds,f,ensure_ascii=False,indent=2)

print("Kaydedilen fon:", len(funds))
print(funds[:3])