import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

for (const width of [1440, 390]) {
  test(`pharmacy login, combined filters, stock update and signed summary at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let quantity = 24;
    let demo = true;
    const queries = [];
    await page.route('**/api/pharmacy/**', async route => {
      const url = new URL(route.request().url());
      let data;
      if (url.pathname.endsWith('/identify')) data = { profile: { id: 'pharmacist', full_name: 'Demo Pharmacist' } };
      else if (url.pathname.endsWith('/filters')) data = { brands: ['Brand A'], specialties: ['cardiology'], compositions: ['Composition A'] };
      else if (route.request().method() === 'PATCH') {
        quantity = route.request().postDataJSON().quantity; demo = false; data = { stock_quantity: quantity };
      } else if (url.pathname.endsWith('/stock')) {
        queries.push(url.searchParams);
        const empty = url.searchParams.get('stock') === 'out_of_stock' && quantity !== 0;
        data = { total: empty ? 0 : 1, items: empty ? [] : [{ brand_id: 'BR001', brand: 'Brand A', manufacturer: null,
          variant: 'Source variant', source_status: 'unverified', stock_quantity: quantity, stock_is_demo: demo,
          pharmacy_medicines: { composition: 'Composition A', specialty: 'cardiology' } }] };
      } else if (url.pathname.endsWith('/consultations/visit')) data = { patient_name: 'Test Patient', doctor_name: 'Dr. Test',
        signed_at: '2026-10-29T06:00:00Z', soap: { plan: ['Reviewed care plan'] } };
      else if (url.pathname.endsWith('/consultations')) data = { total: 1, items: [{ id: 'visit', patients: { full_name: 'Test Patient' },
        slots: { doctors: { full_name: 'Dr. Test' } }, completed_at: '2026-10-29T06:00:00Z' }] };
      else return route.fulfill({ status: 404, json: { detail: 'Not found' } });
      await route.fulfill({ json: data });
    });
    await page.goto('/');
    await page.getByRole('button', { name: /Pharmacist/ }).click();
    await page.getByLabel('Phone number').fill('+919800000001');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Update stock for Brand A' })).toBeVisible();
    await page.getByRole('combobox', { name: 'Brand', exact: true }).selectOption('Brand A');
    await page.getByRole('combobox', { name: 'Specialty', exact: true }).selectOption('cardiology');
    await page.getByRole('combobox', { name: 'Composition', exact: true }).selectOption('Composition A');
    await page.getByRole('combobox', { name: 'Stock', exact: true }).selectOption('out_of_stock');
    await expect(page.getByText('No medicines match these filters.')).toBeVisible();
    expect(queries.some(q => q.get('brand') === 'Brand A' && q.get('specialty') === 'cardiology' && q.get('composition') === 'Composition A' && q.get('stock') === 'out_of_stock')).toBe(true);
    await page.getByRole('button', { name: 'Clear filters' }).click();
    await page.getByRole('button', { name: 'Update stock for Brand A' }).click();
    await page.getByLabel('Count for Brand A').fill('0');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByText('Stock updated for Brand A.', { exact: true })).toBeVisible();
    expect(quantity).toBe(0);
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Medicine stock' })).toBeVisible();
    const accessibility = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
    expect(accessibility.violations).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole('link', { name: 'Signed consultations', exact: true }).click();
    await page.getByRole('link', { name: /Test Patient/ }).click();
    await expect(page.getByText('Reviewed care plan')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Pharmacist sign in' })).toBeVisible();
  });
}

test('pharmacy errors can be retried and signed queue can be empty', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('sahayog.pharmacist.profile', JSON.stringify({ id: 'pharmacist', full_name: 'Demo' })));
  let failing = true;
  await page.route('**/api/pharmacy/**', route => failing
    ? route.fulfill({ status: 503, json: { detail: 'Database unavailable' } })
    : route.fulfill({ json: { total: 0, items: [] } }));
  await page.goto('/pharmacist/consultations');
  await expect(page.getByRole('alert')).toContainText('Database unavailable');
  failing = false;
  await page.getByRole('button', { name: 'Refresh' }).click();
  await expect(page.getByText('No signed consultations yet.')).toBeVisible();
});
