from apify_client import ApifyClient
import os

client = ApifyClient(os.getenv("APIFY_TOKEN"))

actor = client.actor("akemal/tefas-api-scraper")

readme = actor.get()["readmeSummary"]

print(readme)