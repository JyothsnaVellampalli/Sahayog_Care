import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const soap = { subjective: ['Knee pain'], objective: ['Reviewed X-ray'], assessment: ['Improving'], plan: ['Review in two weeks'] };
const completed = { id: 'prior', type: 'appointment', status: 'COMPLETED', starts_at: '2026-10-07T04:30:00Z', doctor_name: 'Dr. Demo', reason: 'Knee pain' };

async function patient(page) {
  await page.addInitScript(() => localStorage.setItem('sahayog.patient.session', JSON.stringify({ profile: { id: 'patient', full_name: 'Demo Patient', city: 'Pune' }, access_token: 'token' })));
}

test('follow-up choice persists into intake and booking; new appointment clears it', async ({ page }) => {
  await patient(page);
  const requests = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data;
    if (path.endsWith('/symptoms')) data = { symptoms: [] };
    else if (path.endsWith('/appointments')) data = { appointments: [completed, { ...completed, id: 'future', status: 'BOOKED' }] };
    else if (path.endsWith('/intake')) { requests.push(route.request().postDataJSON()); data = { outcome: 'booking', classification: { category: 'Normal' }, doctors: [{ id: 'doctor', full_name: 'Dr. Demo', slots: [{ id: 'slot', starts_at: '2099-01-01T10:00:00Z' }] }] }; }
    else if (path.endsWith('/book')) { requests.push(route.request().postDataJSON()); data = { ok: true }; }
    else data = {};
    await route.fulfill({ json: data });
  });
  await page.goto('/patient/book-appointment?followup=prior');
  await expect(page.getByLabel('This is a follow-up appointment')).toBeChecked();
  await expect(page.getByLabel('Previous appointment')).toHaveValue('prior');
  await expect(page.getByRole('option', { name: /future/ })).toHaveCount(0);
  await page.getByLabel('Anything else the doctor should know? (optional)').fill('Knee pain review');
  await page.getByRole('button', { name: 'Show available slots' }).click();
  await page.getByRole('button', { name: /Book .*Dr. Demo/ }).click();
  await expect(page.getByText('Your appointment is booked.')).toBeVisible();
  expect(requests.map(r => r.linked_appointment_id)).toEqual(['prior', 'prior']);
  await page.goto('/patient/book-appointment');
  await expect(page.getByLabel('This is a follow-up appointment')).not.toBeChecked();
});

test('patient views report carousel without upload and follows previous appointment', async ({ page }) => {
  await patient(page);
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    await route.fulfill({ json: path.endsWith('/reports') ? { reports: [
      { id: 'one', title: 'Blood panel', reported_at: '2026-10-07', findings: { findings: 'Normal panel' } },
      { id: 'two', title: 'Knee X-ray', reported_at: '2026-10-07', findings: { findings: 'No fracture' } },
    ] } : { ...completed, id: 'followup', linked_appointment_id: 'prior', soap, signed_at: '2026-10-07', prescription: [] } });
  });
  await page.goto('/patient/my-appointments/followup');
  await expect(page.getByRole('link', { name: /Previous related appointment/ })).toHaveAttribute('target', '_blank');
  await page.getByRole('button', { name: 'Reports', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await expect(page.getByText('Normal panel')).toBeVisible();
  await page.getByRole('button', { name: 'Next report' }).click();
  await expect(page.getByText('No fracture')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add report', exact: true })).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Reports', exact: true })).toBeFocused();
});

test('helpdesk filters consultations and opens read-only clinical view with report upload', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('sahayog.helpdesk.session', JSON.stringify({ id: 'staff', full_name: 'Demo Helpdesk' })));
  const queries = [];
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()); let data;
    if (url.pathname.endsWith('/filters')) data = { doctors: [{ id: 'doc', full_name: 'Dr. Demo' }], specialties: [{ id: 'orth', name: 'Orthopedics' }] };
    else if (url.pathname.endsWith('/consultations')) { queries.push(url.searchParams); data = { consultations: [{ ...completed, patients: { full_name: 'Demo Patient' }, slots: { starts_at: completed.starts_at, doctors: { full_name: 'Dr. Demo' } }, specialties: { name: 'Orthopedics' } }], count: 1 }; }
    else if (url.pathname.endsWith('/reports')) data = route.request().method() === 'POST' ? { id: 'added', title: 'Blood panel', reported_at: '2026-10-07', findings: { findings: 'Uploaded' } } : { reports: [] };
    else data = { ...completed, patient_name: 'Demo Patient', linked_appointment_id: 'older', symptoms: ['Knee pain'], soap, prescription: [], signed_at: '2026-10-07' };
    await route.fulfill({ json: data });
  });
  await page.goto('/helpdesk/consultations');
  await page.getByLabel('Doctor', { exact: true }).selectOption('doc');
  await page.getByLabel('Specialty', { exact: true }).selectOption('orth');
  await page.getByLabel('Day', { exact: true }).fill('2026-10-07');
  await page.getByLabel('From time').fill('09:00');
  await expect.poll(() => queries.at(-1)?.get('specialty_id')).toBe('orth');
  await expect.poll(() => queries.at(-1)?.get('doctor_id')).toBe('doc');
  await page.getByRole('link', { name: /Demo Patient/ }).click();
  await expect(page.getByRole('heading', { name: 'SOAP summary' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Start consultation|Start listening|Sign and close|Edit summary|Add medicine/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Reports', exact: true }).click();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByLabel('Report title').fill('Blood panel');
  await page.getByLabel('PDF or image (up to 10 MB)').setInputFiles({ name: 'blood.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\n%%EOF') });
  await page.getByRole('button', { name: 'Add report', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Blood panel' })).toBeVisible();
  await page.screenshot({ path: 'test-results/phase6-reports.png', fullPage: true });
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 390, height: 900 });
  await page.screenshot({ path: 'test-results/phase6-helpdesk-mobile.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('doctor can read a previous completed consultation from another doctor and its image report', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('sahayog.doctor.session', JSON.stringify({ profile: { id: 'doctor', full_name: 'Dr. Viewer', has_signature: true } })));
  const calls = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname; calls.push(path);
    if (path.endsWith('/file')) {
      expect(route.request().headers()['x-doctor-id']).toBe('doctor');
      return route.fulfill({ contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jA2kAAAAASUVORK5CYII=', 'base64') });
    }
    const data = path.endsWith('/settings') ? { show_speech_transcripts: false }
      : path.endsWith('/soap') ? { soap, signed_at: '2026-10-07', doctor_name: 'Dr. Previous', prescription: [{ brand: 'Saved medicine', strength_form: 'Tablet', dose: 'Recorded dose' }] }
      : path.endsWith('/reports') ? { reports: [{ id: 'image', title: 'Scan image', content_type: 'image/png', reported_at: '2026-10-07' }] }
      : path.endsWith('/transcript') ? { segments: [] }
      : { ...completed, doctor_id: 'another-doctor', patient_name: 'Demo Patient', linked_appointment_id: 'older' };
    return route.fulfill({ json: data });
  });
  await page.goto('/doctor/consultations/prior');
  await expect(page.getByText('Saved medicine · Tablet')).toBeVisible();
  await expect(page.getByRole('link', { name: /Previous related consultation/ })).toHaveAttribute('target', '_blank');
  await expect(page.getByRole('button', { name: /Sign and close|Start consultation|Edit summary/ })).toHaveCount(0);
  expect(calls.some(path => path.endsWith('/prescription'))).toBe(false);
  await page.getByRole('button', { name: 'Reports', exact: true }).click();
  await expect(page.getByRole('img', { name: 'Scan image' })).toBeVisible();
  await expect.poll(() => page.getByRole('img', { name: 'Scan image' }).evaluate(img => img.naturalWidth)).toBe(1);
  await expect(page.getByRole('button', { name: 'Add report', exact: true })).toHaveCount(0);
});

test('PDF report opens in the browser viewer and can be downloaded', async ({ page }) => {
  await patient(page);
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  const stream = 'BT /F1 18 Tf 30 240 Td (Demo blood test report) Tj ET';
  objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
  let pdf = '%PDF-1.4\n'; const offsets = [0];
  objects.forEach((obj,i) => { offsets.push(pdf.length); pdf += `${i+1} 0 obj\n${obj}\nendobj\n`; });
  const xref = pdf.length;
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(n => `${String(n).padStart(10,'0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/file')) return route.fulfill({ contentType: 'application/pdf', body: pdf });
    return route.fulfill({ json: path.endsWith('/reports') ? { reports: [{ id: 'pdf', title: 'Blood test PDF', reported_at: '2026-10-07', content_type: 'application/pdf' }] } : { ...completed, soap, prescription: [] } });
  });
  await page.goto('/patient/my-appointments/prior');
  await page.getByRole('button', { name: 'Reports', exact: true }).click();
  await expect(page.locator('iframe[title="Blood test PDF"]')).toHaveAttribute('src', /^blob:/);
  await expect(page.frameLocator('iframe[title="Blood test PDF"]').locator('embed')).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download report' }).click();
  expect((await download).suggestedFilename()).toBe('Blood test PDF.pdf');
  await page.screenshot({ path: 'test-results/phase6-pdf.png', fullPage: true });
});
