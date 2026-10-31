"""Run rollback-only recovery and publication checks against the configured DB."""
import os
from pathlib import Path
import psycopg2
from apply_migration import _load_env, _project_ref

def main():
    _load_env()
    ref = _project_ref(os.environ['SUPABASE_URL'])
    connection = psycopg2.connect(host=f'db.{ref}.supabase.co', port=5432, user='postgres',
        password=os.environ['DB_PASSWORD'], dbname='postgres', sslmode='require', connect_timeout=8)
    try:
        with connection.cursor() as cursor:
            cursor.execute((Path(__file__).resolve().parents[1] / 'tests' / 'consultation_processing_transaction.sql').read_text(encoding='utf-8'))
        print('Passed: upload deduplication, worker claim/recovery, stale lease fencing, automatic SOAP, signing guard, result publication, edits and retries. All fixtures rolled back.')
    except psycopg2.Error as error:
        print(f'Processing check failed: {error.diag.message_primary}\n{error.diag.context}')
        return 1
    finally:
        connection.rollback(); connection.close()
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
