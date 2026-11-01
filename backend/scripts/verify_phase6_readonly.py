"""Read-only API smoke test against the configured DB; does not start workers."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def check(response):
    if response.status_code != 200:
        raise SystemExit(f'API check failed: HTTP {response.status_code} at {response.request.url.path}')
    return response.json()


profile = check(client.post('/api/helpdesk/identify', json={'phone': '+919800000002'}))['profile']
base = f"/api/helpdesk/{profile['id']}"
filters = check(client.get(base + '/filters'))
now = datetime.now(timezone.utc)
listing = check(client.get(base + '/consultations', params={
    'date_from': (now-timedelta(days=365)).isoformat(), 'date_to': (now+timedelta(days=365)).isoformat(),
}))
for visit in listing['consultations'][:3]:
    # Report metadata reads exercise PostgREST relationships without loading clinical snapshots.
    check(client.get(f"/api/records/{visit['id']}/reports", headers={'X-Helpdesk-Id': profile['id']}))
print('Helpdesk identify, filter catalogue, paginated consultations and report metadata API checks passed.')
