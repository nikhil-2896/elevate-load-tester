import requests
from analysis.type_detector import extract_paths_from_sitemap

analyze = requests.post("http://localhost:5000/api/analyze", json={"url": "https://scentitude.in"}).json()
raw = analyze["sitemap"]["raw"]

paths = extract_paths_from_sitemap(raw)
print("Extracted paths:", paths)
print("Total paths found:", len(paths))