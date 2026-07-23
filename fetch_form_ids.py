import urllib.request, json

token = None
with open('.env') as f:
    for line in f:
        if line.startswith('META_ACCESS_TOKEN='):
            token = line.strip().split('=',1)[1]
            break

url = f"https://graph.facebook.com/v18.0/act_577546498668650/ads?fields=id,name,lead_gen_form_id&limit=50&access_token={token}"
resp = urllib.request.urlopen(url, timeout=30)
data = json.loads(resp.read())

seen = set()
for ad in data.get('data', []):
    form_id = ad.get('lead_gen_form_id')
    if form_id and form_id not in seen:
        seen.add(form_id)
        print(f"Ad: {ad['name']}")
        print(f"Form ID: {form_id}")
        print("---")
