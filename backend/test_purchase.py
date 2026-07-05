import requests, json, uuid, os, django

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
django.setup()

from api.providers.cms_only import CMSOnlyAdapter

# Test 1: Direct adapter call
adapter = CMSOnlyAdapter()
try:
    result = adapter.create_line(pack_id=40017, months=1)
    print("TEST 1 - Valid pack (40017):")
    print(f"  Username: {result['username']}")
    print(f"  Password: {result['password']}")
    print(f"  DNS: {result['dns_domain'][:60]}...")
    print("  PASS\n")
except Exception as e:
    print(f"TEST 1 - FAIL: {e}\n")

# Test 2: Invalid pack
try:
    result = adapter.create_line(pack_id=132, months=1)
    print("TEST 2 - Invalid pack: UNEXPECTED SUCCESS\n")
except Exception as e:
    print(f"TEST 2 - Invalid pack (132):")
    print(f"  Error: {e}")
    print("  PASS\n")

# Test 3: End-to-end purchase via API
BASE = 'http://backend:8000/api'
r = requests.post(f'{BASE}/auth/login/', json={'username': 'ahmed', 'password': 'reseller123'})
token = r.json()['access']
print(f"TEST 3 - Logged in as ahmed")

idem_key = str(uuid.uuid4())
r = requests.post(f'{BASE}/purchase/',
    json={'product_id': 2, 'quantity': 1},
    headers={'Authorization': f'Bearer {token}', 'Idempotency-Key': idem_key})
data = r.json()
print(f"Purchase response: {r.status_code}")

if r.status_code == 201:
    order_id = data['order_id']
    r = requests.get(f'{BASE}/orders/{order_id}/credentials/',
        headers={'Authorization': f'Bearer {token}'})
    creds = r.json()
    print(f"Credentials: {len(creds)}")
    for c in creds:
        uname = c['external_username']
        pwd = c['password']
        dns = c['dns_domain'][:60]
        print(f"  Username: {uname}")
        print(f"  Password: {pwd}")
        print(f"  DNS: {dns}...")
    if creds and creds[0]['password'] != creds[0]['external_username']:
        print("  PASS - Password differs from username (extracted from URL)")
    else:
        print("  FAIL - Password equals username")
else:
    print(f"  FAIL: {data}")
