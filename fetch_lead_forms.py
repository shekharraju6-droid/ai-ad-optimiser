import urllib.request, json

token = open('.env').read().split('META_ACCESS_TOKEN=')[1].split('\n')[0]
page_id = '112549478397749'
url = f"https://graph.facebook.com/v18.0/{page_id}/leadgen_forms?fields=id,name,status,leads_count,created_time,questions{{key,label,type}}&access_token={token}"

try:
    resp = urllib.request.urlopen(url, timeout=30)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2)[:6000])
except Exception as e:
    print('ERROR:', e)
