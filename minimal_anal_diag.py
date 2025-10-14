from datetime import datetime, timedelta, timezone
from cloudflare_api import cf_api

def test_endpoints():
    print("1. Testing zone details endpoint...")
    z = cf_api.get_zone_details()
    print(f"   Status: {'OK' if z else 'FAIL'}")
    if z:
        name = z.get('result', {}).get('name') or z.get('result', {}).get('id')
        print(f"   ✅ Zone: {name}")

    print("\n2. Testing GraphQL zone analytics (last 1h)...")
    g = cf_api.get_http_requests_fixed(hours=1)  # fixed: method actually exists
    print(f"   Status: {'OK' if g else 'FAIL'}")
    if g:
        groups = g['data']['viewer']['zones'][0]['httpRequestsAdaptiveGroups']
        print(f"   ✅ Buckets: {len(groups)}")

    print("\n3. Testing GraphQL colo breakdown (last 24h)...")
    c = cf_api.get_analytics_by_colo(hours=24)
    print(f"   Status: {'OK' if c else 'FAIL'}")
    if c:
        groups = c['data']['viewer']['zones'][0]['httpRequestsAdaptiveGroups']
        print(f"   ✅ Colos: {len(groups)}")

    print("\n4. Testing DNS analytics report (last 1h, ISO timestamps)...")
    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=1)
    d = cf_api.get_dns_analytics_report(since=since, until=until)
    if d:
        print("   ✅ Success!")
        print("   Data keys:", list(d.get('result', {}).keys()))
    else:
        print("   ❌ DNS analytics request failed")

if __name__ == "__main__":
    test_endpoints()
