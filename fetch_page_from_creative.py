import urllib.request, json

token = open('.env').read().split('META_ACCESS_TOKEN=')[1].split('\n')[0]
fields = 'id,name,creative{effective_object_story_id,object_story_spec{link_data{call_to_action{value}},page_id},asset_customization_rules}'
url = f"https://graph.facebook.com/v18.0/act_577546498668650/ads?fields={urllib.parse.quote(fields)}&limit=10&access_token={token}"

resp = urllib.request.urlopen(url, timeout=30)
data = json.loads(resp.read())
print(json.dumps(data, indent=2)[:4000])
