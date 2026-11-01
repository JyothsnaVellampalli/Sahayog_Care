"""After seed.sql: provision demo Auth accounts and upload their JSON objects."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Create accounts and upload objects; otherwise validate offline.')
    args = parser.parse_args()
    from app.consultation.soap import SoapDraft
    manifest = json.loads((ROOT / 'database/demo_patient_history/storage_manifest.json').read_text())
    for key, obj in manifest['objects'].items():
        if 'soap' in obj:
            SoapDraft.model_validate(obj['soap'])
        assert key.startswith('demo_patient_history/v1/') and '..' not in key
    if not args.apply:
        print('Validated 5 patient fixtures and 50 JSON objects offline. No external writes.')
        return
    from app import storage
    from app.patient.service import _require_admin
    password = os.environ.get('DEMO_PATIENT_PASSWORD', '')
    if len(password) < 12:
        raise SystemExit('Set DEMO_PATIENT_PASSWORD to a demo password of at least 12 characters.')
    db = _require_admin()
    # Check all seed rows before creating any external resources.
    for p in manifest['patients']:
        rows = db.table('patients').select('*').eq('id', p['id']).execute().data
        if not rows or any(rows[0].get(k) != p[k] for k in ('phone', 'email', 'full_name')):
            raise SystemExit('Apply seed.sql first; demo profile missing or changed.')
    for p in manifest['patients']:
        row = db.table('patients').select('auth_user_id').eq('id', p['id']).single().execute().data
        if row['auth_user_id']:
            user = db.auth.admin.get_user_by_id(row['auth_user_id']).user
        else:
            # Recover a prior interrupted create without resetting any password.
            user = None
            page = 1
            while True:
                users = db.auth.admin.list_users(page=page, per_page=100)
                user = next((u for u in users if u.email == p['email']), None)
                if user or len(users) < 100:
                    break
                page += 1
            if user is None:
                user = db.auth.admin.create_user({'email': p['email'], 'password': password,
                    'email_confirm': True, 'phone': p['phone'],
                    'user_metadata': {'full_name': p['full_name'], 'role': 'patient',
                                      'demo_seed': manifest['version']}}).user
        if user.email != p['email'] or user.user_metadata.get('demo_seed') != manifest['version']:
            raise SystemExit('Account collision: refusing to link a non-seed Auth account.')
        db.table('patients').update({'auth_user_id': str(user.id)}).eq('id', p['id']).execute()
        print(f"Account ready: {p['full_name']} / {p['phone']}")
    for key, original in manifest['objects'].items():
        obj = dict(original)
        if key.endswith('/signed.json'):
            doctor = db.table('doctors').select('id,full_name').eq('doctor_code', obj.pop('doctor_code')).single().execute().data
            obj.update(signed_by=doctor['id'], doctor_name=doctor['full_name'])
        existing = storage.get_json(key, strict=True)
        if existing is not None and existing != obj:
            raise SystemExit(f'Refusing to overwrite changed object: {key}')
        if existing is None:
            storage.put_json(key, obj)
        if storage.get_json(key, strict=True) != obj:
            raise SystemExit(f'Storage verification failed: {key}')
    print(f'50 objects verified in {storage.backend_name()}. Existing account passwords were preserved.')


if __name__ == '__main__':
    main()
