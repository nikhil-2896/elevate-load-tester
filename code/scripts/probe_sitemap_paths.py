import requests

BASE = "http://localhost:5000"

# scentitude.in was confirmed earlier to have a real sitemap
analyze = requests.post(f"{BASE}/api/analyze", json={"url": "https://scentitude.in"}).json()
print("Sitemap found:", analyze.get("sitemap", {}).get("found"))

sitemap_raw = analyze.get("sitemap", {}).get("raw")
if not sitemap_raw:
    print("No raw sitemap content — can't test path extraction")
else:
    print("Raw sitemap length:", len(sitemap_raw))
    print("First 300 chars:\n", sitemap_raw[:300])