import os, requests

TG = os.environ["TG_TOKEN"]
DC = os.environ["DC_WEBHOOK"]
api = f"https://api.telegram.org/bot{TG}/getUpdates"

r = requests.get(api, params={"allowed_updates": '["channel_post"]'}).json()
last = None
for u in r.get("result", []):
    last = u["update_id"]
    p = u.get("channel_post", {})
    text = p.get("text") or p.get("caption")
    if text:
        requests.post(DC, json={"content": text[:2000]})

if last is not None:
    requests.get(api, params={"offset": last + 1})  # tandai sudah diproses
