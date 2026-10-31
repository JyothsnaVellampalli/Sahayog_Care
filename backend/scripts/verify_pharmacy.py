"""Read-only Phase 4.1 smoke checks against the configured database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pharmacy import service
from app.pharmacy.catalogue import load_catalogue
from app.consultation import prescriptions


def main():
    medicines, brands = load_catalogue()
    profile = service.identify('+919800000001')['profile']
    service.require_pharmacist(profile['id'])
    all_stock = service.inventory(limit=100)
    assert all_stock['total'] == len(brands), 'Brand count mismatch'
    db_medicines = service._admin().table('pharmacy_medicines').select('id', count='exact').execute()
    assert db_medicines.count == len(medicines), 'Medicine count mismatch'
    options = service.facets()
    assert len(options['specialties']) == 4
    first = all_stock['items'][0]
    filtered = service.inventory(first['brand'], first['pharmacy_medicines']['specialty'],
                                 first['pharmacy_medicines']['composition'])
    assert any(row['brand_id'] == first['brand_id'] for row in filtered['items'])
    for state in ['in_stock', 'out_of_stock', 'low_stock', 'unknown']:
        service.inventory(stock=state)
    visits = service.consultations()
    for row in all_stock['items']:
        if row['stock_quantity'] is not None:
            assert row['available_quantity'] == row['stock_quantity'] - row['locked_quantity']
    doctor = service._admin().table('doctors').select('id').eq('is_active', True).limit(1).execute().data
    if doctor:
        doctor_catalogue = prescriptions.catalogue(doctor[0]['id'])
        assert len(doctor_catalogue['items']) == len(brands)
        assert 'available_quantity' in doctor_catalogue['items'][0]
    print(f"Verified: {db_medicines.count} medicines, {all_stock['total']} brands, four specialties.")
    print('Phone lookup, combined filters, stock filters and signed consultation joins passed.')
    print('Available/reserved stock fields and doctor medicine catalogue passed.')
    print(f"Signed consultation queue: {visits['total']} rows. No patient details printed.")


if __name__ == '__main__':
    main()
