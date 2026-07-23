import urllib.request, json

token = open('.env').read().split('META_ACCESS_TOKEN=')[1].split('\n')[0]
fields = 'id,name,ads{id,name,creative{object_story_spec{link_data{call_to_action{value}}}}'
url = f"https://graph.facebook.com/v18.0/act_577546498668650/campaigns?fields={urllib.parse.quote(fields)}&access_token={token}"

resp = urllib.request.urlopen(url, timeout=30)
data = json.loads(resp.read())
print(json.dumps(data, indent=2)[:4000])
