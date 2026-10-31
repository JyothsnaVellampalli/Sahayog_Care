"""Import existing S3 prescriptions to Supabase without deleting source objects."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.consultation import prescription_store


def main():
    offset = 0
    imported = 0
    while True:
        visits = (prescription_store.client().table('appointments').select('id')
                  .order('id').range(offset, offset + 99).execute().data or [])
        for visit in visits:
            if prescription_store.load(visit['id']):
                imported += 1
        if len(visits) < 100:
            break
        offset += 100
    print(f'Prescriptions available in Supabase: {imported}. Original S3 objects retained.')


if __name__ == '__main__':
    main()
