import urllib.request, json

token = open('.env').read().split('META_ACCESS_TOKEN=')[1].split('\n')[0]
fields = 'id,name,leadgen_form{id,name}'
url = f"https://graph.facebook.com/v18.0/act_577546498668650/ads?fields={urllib.parse.quote(fields)}&limit=50&access_token={token}"

try:
    resp = urllib.request.urlopen(url, timeout=30)
    data = json.loads(resp.read())
    for ad in data.get('data', []):
        if ad.get('leadgen_form'):
            print(json.dumps(ad))
            print('---')
except Exception as e:
    print('ERROR:', e)
