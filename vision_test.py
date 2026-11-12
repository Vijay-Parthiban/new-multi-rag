import requests
URL = "https://receiver-retrieve-simulation-outlined.trycloudflare.com"
H = {"x-api-key": "vj-pa"}

print(requests.get(f"{URL}/health", headers=H).json())

files = [("files", (p, open(p, "rb"), "image/png")) for p in ["sources_page_v2.png","sources_page_resized.png","sources_page_2026.png", "sources_page_test.png","sources_page.png"]]
r = requests.post(f"{URL}/score", headers=H, data={"query": "which are the those with black empty screens ?"}, files=files)
print(r.status_code, r.json())