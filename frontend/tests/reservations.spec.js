import { test, expect } from '@playwright/test';

for (const action of ['release', 'dispense']) {
  test(`pharmacist ${action} resolves a reservation and preserves signed medicines`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 900 });
    await page.addInitScript(() => sessionStorage.setItem('sahayog.pharmacist.profile', JSON.stringify({ id: 'pharmacist', full_name: 'Demo' })));
    let overdue = false;
    let status = 'LOCKED';
    let actions = 0;
    await page.route('**/api/pharmacy/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/reservation')) {
        expect(route.request().postDataJSON().action).toBe(action);
        actions++;
        status = action === 'release' ? 'RELEASED' : 'DISPENSED';
        return route.fulfill({ json: { status } });
      }
      const details = { id: 'visit', patient_name: 'Test Patient', doctor_name: 'Dr. Test',
        signed_at: '2026-10-28T01:00:00Z', reservation_status: status,
        can_unlock: overdue && status === 'LOCKED', release_available_at: '2026-10-29T01:00:00Z',
        soap: { plan: ['Reviewed plan'] }, prescription: [{ brand_id: 'BR001', brand: 'Brand A', strength_form: '5 mg tablet',
          dose: '1 tablet', frequency: 'Once daily', duration: '5 days', quantity: 5 }] };
      return route.fulfill({ json: path.endsWith('/consultations') ? {
        total: 1, items: [{ ...details, patients: { full_name: 'Test Patient' }, slots: { doctors: { full_name: 'Dr. Test' } }, completed_at: details.signed_at }],
      } : details });
    });
    await page.goto('/pharmacist/consultations/visit');
    await expect(page.getByRole('button', { name: 'Unlock stock' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Mark collected' })).toBeEnabled();
    if (action === 'release') {
      overdue = true;
      await page.getByRole('button', { name: 'Refresh consultation' }).click();
      await expect(page.getByText('Overdue · stock still locked')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Unlock stock' })).toBeEnabled();
    }
    page.once('dialog', dialog => dialog.dismiss());
    await page.getByRole('button', { name: action === 'release' ? 'Unlock stock' : 'Mark collected' }).click();
    expect(actions).toBe(0);
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', { name: action === 'release' ? 'Unlock stock' : 'Mark collected' }).click();
    await expect(page.getByText(action === 'release' ? 'Stock unlocked' : 'Medicines collected', { exact: true })).toBeVisible();
    expect(actions).toBe(1);
    await expect(page.getByRole('button', { name: 'Unlock stock' })).toHaveCount(0);
    await expect(page.getByText('Brand A · 5 mg tablet')).toBeVisible();
    await page.reload();
    await expect(page.getByText(action === 'release' ? 'Stock unlocked' : 'Medicines collected', { exact: true })).toBeVisible();
  });
}

test('overdue reservations are flagged in the signed queue', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('sahayog.pharmacist.profile', JSON.stringify({ id: 'pharmacist' })));
  await page.route('**/api/pharmacy/**', route => route.fulfill({ json: { total: 1, items: [{ id: 'visit', patients: { full_name: 'Test Patient' }, reservation_status: 'LOCKED', can_unlock: true }] } }));
  await page.goto('/pharmacist/consultations');
  await expect(page.getByText('Overdue · stock still locked')).toBeVisible();
});
