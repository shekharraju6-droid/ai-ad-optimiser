import urllib.request, json

token = open('.env').read().split('META_ACCESS_TOKEN=')[1].split('\n')[0]
url = f"https://graph.facebook.com/v18.0/act_577546498668650/ads?fields=id,name,lead_gen_form_id&limit=50&access_token={token}"

resp = urllib.request.urlopen(url, timeout=30)
data = json.loads(resp.read())
print(json.dumps(data, indent=2)[:4000])
