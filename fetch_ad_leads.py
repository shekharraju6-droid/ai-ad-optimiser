import urllib.request, json

token = open('.env').read().split('META_ACCESS_TOKEN=')[1].split('\n')[0]

# Try leads from a Goa campaign ad
ad_id = '120249207991670382'
fields = 'id,created_time,ad_id,form_id,field_data{values,name}'
url = f"https://graph.facebook.com/v18.0/{ad_id}/leads?fields={urllib.parse.quote(fields)}&limit=10&access_token={token}"

try:
    resp = urllib.request.urlopen(url, timeout=30)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2)[:6000])
except Exception as e:
    print('ERROR:', e)
