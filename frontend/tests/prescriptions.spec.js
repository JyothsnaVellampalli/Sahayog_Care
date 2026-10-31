import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

for (const width of [1440, 390]) {
  test(`prescription review, catalogue drawer and signed snapshot at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.addInitScript(() => localStorage.setItem('sahayog.doctor.session', JSON.stringify({ profile: { id: 'doctor', full_name: 'Dr. Test', has_signature: true } })));
    let summary = { subjective: ['Recorded symptoms'], objective: ['Recorded findings'], assessment: ['Reviewed assessment'], plan: ['Review Brand A'] };
    let prescription = { items: [], reviewed: false, soap_revision: 'a'.repeat(64) };
    let closed = false;
    const medicine = { brand_id: 'BR001', brand: 'Brand A', generic_name: 'Generic A', composition: 'Composition A', variant: '5 or 10 mg tablets', forms: ['Tablet'], specialty: 'cardiology', stock_quantity: 24, available_quantity: 24 };
    const second = { ...medicine, brand_id: 'BR002', brand: 'Brand B', specialty: 'dermatology' };
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      const method = route.request().method();
      let data;
      if (path.endsWith('/settings')) data = { show_speech_transcripts: false };
      else if (path.endsWith('/transcript')) data = { segments: [{ text: 'Review Brand A' }] };
      else if (path.endsWith('/medicines')) data = { items: [medicine, second], default_specialty: 'cardiology', specialties: ['cardiology', 'dermatology'] };
      else if (path.endsWith('/prescription')) {
        if (method === 'PUT') prescription = { ...route.request().postDataJSON(), reviewed: true, items: route.request().postDataJSON().items.map(item => ({ ...medicine, ...item })) };
        data = { ...prescription, suggestions: [{ ...medicine, reason: 'Mentioned in plan' }] };
      } else if (path.endsWith('/soap')) {
        if (method === 'PUT') { summary = route.request().postDataJSON(); prescription.reviewed = false; }
        data = method === 'PUT' ? summary : { soap: summary, ...(closed ? { signature: 'data:image/png;base64,iVBORw0KGgo=', prescription: prescription.items, signed_at: '2026-10-29T06:00:00Z' } : {}) };
      } else {
        if (path.endsWith('/sign')) { expect(prescription.reviewed).toBe(true); closed = true; }
        data = { id: 'visit', status: closed ? 'COMPLETED' : 'IN_PROGRESS', doctor_id: 'doctor', consent_recorded: true,
          patient_name: 'Test Patient', symptoms: [], starts_at: '2026-10-29T05:00:00Z' };
      }
      await route.fulfill({ json: data });
    });
    await page.goto('/doctor/consultations/visit');
    await expect(page.getByRole('heading', { name: 'SOAP summary' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign and close' })).toBeDisabled();
    await page.getByRole('button', { name: 'Add Brand A', exact: true }).click();
    await page.getByRole('button', { name: '+ Add medicine', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('combobox', { name: 'Specialty' })).toHaveValue('cardiology');
    await dialog.getByRole('combobox', { name: 'Specialty' }).selectOption('dermatology');
    await dialog.getByRole('checkbox', { name: /Brand B/ }).check();
    await page.screenshot({ path: `test-results/prescription-picker-${width}.png`, fullPage: true });
    await dialog.getByRole('button', { name: 'Add to prescription' }).click();
    await page.getByRole('button', { name: 'Remove Brand B', exact: true }).click();
    await page.getByLabel('Strength / form for Brand A').fill('5 mg tablet');
    await page.getByLabel('Dose for Brand A', { exact: true }).fill('1 tablet');
    await page.getByLabel('Frequency for Brand A').fill('Once daily');
    await page.getByLabel('Duration for Brand A').fill('5 days');
    await page.getByLabel('Stock quantity for Brand A').fill('5');
    await page.getByRole('button', { name: 'Save prescription' }).click();
    await expect(page.getByRole('button', { name: 'Sign and close' })).toBeEnabled();
    await page.reload();
    await expect(page.getByLabel('Dose for Brand A', { exact: true })).toHaveValue('1 tablet');
    await page.getByRole('button', { name: 'Edit summary' }).click();
    await page.getByRole('textbox', { name: 'Plan', exact: true }).fill('Updated plan');
    await page.getByRole('button', { name: 'Apply edits' }).click();
    await expect(page.getByRole('button', { name: 'Sign and close' })).toBeDisabled();
    await page.getByRole('button', { name: 'Save prescription' }).click();
    await expect(page.getByRole('button', { name: 'Sign and close' })).toBeEnabled();
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
    expect(results.violations).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/prescription-review-${width}.png`, fullPage: true });
    await page.getByRole('button', { name: 'Sign and close' }).click();
    await expect(page.getByRole('button', { name: 'Save prescription' })).toHaveCount(0);
    await expect(page.getByText('Brand A · 5 mg tablet')).toBeVisible();
  });
}
