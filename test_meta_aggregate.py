import urllib.request, urllib.parse, json

with open('.env') as f:
    lines = f.readlines()
token = None
for line in lines:
    if line.startswith('META_ACCESS_TOKEN='):
        token = line.strip().split('=', 1)[1]
        break

fields = 'campaign_name,actions,spend'
params = {
    'fields': fields,
    'date_preset': 'today',
    'level': 'campaign',
    'access_token': token
}
url = f"https://graph.facebook.com/v18.0/act_577546498668650/insights?{urllib.parse.urlencode(params)}"

try:
    resp = urllib.request.urlopen(url, timeout=30)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2)[:4000])
except Exception as e:
    print('ERROR:', e)
    try:
        err_body = e.read().decode()
        print(err_body)
    except:
        pass
