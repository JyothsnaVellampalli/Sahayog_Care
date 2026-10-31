import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('profile popup loads, saves and restores focus', async ({ page }) => {
  await fixtures(page);
  let profile = { id: 'patient', full_name: 'Test Patient', city: 'Pune', phone: '9999999999', email: 'test@example.com', age: 35, gender: 'female', role: 'patient' };
  await page.route('**/api/patients/patient/profile', async route => {
    expect(route.request().headers().authorization).toBe('Bearer test-token');
    if (route.request().method() === 'PATCH') profile = { ...profile, ...route.request().postDataJSON() };
    await route.fulfill({ json: profile });
  });
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto('/patient/book-appointment');
  const trigger = page.getByRole('button', { name: /View and edit your profile/ });
  await trigger.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('test@example.com')).toBeVisible();
  await dialog.getByLabel('Full name').fill('Updated Patient');
  await dialog.getByLabel('Location').selectOption('Hyderabad');
  await accessible(page);
  await page.screenshot({ path: 'test-results/profile-mobile.png', fullPage: true });
  await dialog.getByRole('button', { name: 'Save changes' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toContainText('Updated Patient');
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('sahayog.patient.session')));
  expect(saved.profile.city).toBe('Hyderabad');
  await trigger.click();
  await expect(page.getByLabel('Full name')).toHaveValue('Updated Patient');
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});

const symptoms = [{ id: 'S006', label: 'Palpitations', severity: 'mild', specialty: 'cardiology' }, { id: 'S001', label: 'Chest pain', severity: 'emergency', specialty: 'cardiology' }];
const future = '2099-10-28T10:00:00Z';
const booked = { id: 'visit', type: 'appointment', status: 'BOOKED', starts_at: future, doctor_name: 'Dr. Test', reason: 'Cardiology', symptoms: [{ id: 'S006', label: 'Palpitations', severity: 'mild', duration_days: 2 }], symptom_text: 'Palpitations for two days' };
const past = { ...booked, id: 'past', status: 'COMPLETED', starts_at: '2020-10-01T10:00:00Z', soap: { subjective: ['Palpitations'], objective: ['Reviewed'], assessment: ['Signed assessment'], plan: ['Follow the care plan'] }, signed_at: '2020-10-01T11:00:00Z', signed_by: 'Dr. Test' };
async function fixtures(page) {
  await page.addInitScript(() => {
    localStorage.setItem('sahayog.patient.session', JSON.stringify({ profile: { id: 'patient', full_name: 'Test Patient', city: 'Pune' }, access_token: 'test-token' }));
  });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    let data;
    if (url.pathname === '/api/symptoms') data = { symptoms };
    else if (url.pathname.endsWith('/intake')) data = { classification: { category: 'Normal', scores: { Normal: 1 } }, outcome: 'booking', symptoms: booked.symptoms, specialty: { name: 'Cardiology' }, doctors: [{ id: 'doc', full_name: 'Dr. Test', city: 'Pune', slots: [{ id: 'slot', starts_at: future }] }] };
    else if (url.pathname.endsWith('/book')) data = { ok: true };
    else if (url.pathname.endsWith('/appointments')) data = { appointments: [booked, past, { id: 'emergency', type: 'emergency', status: 'EMERGENCY_PENDING', reason: 'Emergency case' }] };
    else if (url.pathname.endsWith('/appointments/visit')) data = route.request().method() === 'PUT' ? { ok: true } : booked;
    else if (url.pathname.endsWith('/appointments/past')) data = past;
    else return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Appointment not found.' }) });
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) });
  });
}
async function accessible(page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  expect(results.violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}
for (const width of [1440, 390, 320]) {
  test(`patient booking, draft, filters, details and download at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await fixtures(page);
    await page.goto('/patient/book-appointment');
    const combo = page.getByRole('combobox', { name: 'Symptoms (optional)' });
    await combo.fill('Palpitations'); await combo.press('ArrowDown'); await combo.press('Enter'); await combo.press('Escape');
    await page.getByRole('spinbutton').fill('2');
    await page.getByRole('button', { name: 'Save draft' }).click();
    await expect(page.getByRole('status')).toContainText('Draft saved');
    await page.reload(); await expect(page.getByRole('spinbutton')).toHaveValue('2');
    await accessible(page);
    await page.screenshot({ path: `test-results/booking-${width}.png`, fullPage: true });
    await page.getByRole('button', { name: 'Show available slots' }).click();
    await expect(page.getByRole('tab', { name: '2. Slot booking' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tabpanel', { name: '1. Symptoms' })).toBeHidden();
    await expect(page.getByText('Normal', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Showing doctors in Pune.')).toBeVisible();
    await accessible(page);
    await page.getByRole('tab', { name: '1. Symptoms' }).click();
    await expect(page.getByRole('spinbutton')).toHaveValue('2');
    await page.getByRole('tab', { name: '1. Symptoms' }).press('ArrowRight');
    await expect(page.getByRole('tab', { name: '2. Slot booking' })).toBeFocused();
    await page.getByRole('button', { name: /Book .* with Dr. Test/ }).click();
    await page.getByRole('link', { name: 'View my appointments' }).click();
    await expect(page.getByText('Emergency case')).toBeVisible();
    await page.getByRole('button', { name: 'past', exact: true }).click();
    await expect(page.getByRole('link', { name: /View details for appointment/ })).toHaveCount(1);
    await accessible(page);
    await page.getByRole('link', { name: /View details for appointment/ }).click();
    await expect(page.getByText('Signed assessment')).toBeVisible();
    await accessible(page);
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download summary' }).click();
    expect((await download).suggestedFilename()).toBe('consultation-past.txt');
    await page.screenshot({ path: `test-results/detail-${width}.png`, fullPage: true });
    await page.getByRole('link', { name: 'Book follow-up' }).click();
    await expect(page).toHaveURL(/book-appointment/);
  });
}
test('scheduled detail editing, refresh, unavailable detail, and auth redirect', async ({ page }) => {
  await fixtures(page);
  await page.goto('/patient/my-appointments/visit');
  await page.getByRole('button', { name: 'Edit details' }).click();
  await page.getByRole('textbox', { name: 'Your note' }).fill('Updated note');
  await accessible(page);
  const save = page.waitForRequest(req => req.method() === 'PUT');
  await page.getByRole('button', { name: 'Save changes' }).click();
  expect((await save).postDataJSON().symptom_text).toBe('Updated note');
  await expect(page.getByText('Appointment details saved.')).toBeVisible();
  await page.reload(); await expect(page.getByRole('heading', { name: 'Appointment details' })).toBeVisible();
  await page.goto('/patient/my-appointments/missing');
  await expect(page.getByRole('alert')).toContainText('Appointment not found');
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/patient\/login/);
});

test('empty slots, emergency guidance, and failed assessment preserve the intake flow', async ({ page }) => {
  await fixtures(page);
  let outcome = 'empty';
  await page.route('**/api/appointments/intake', route => {
    if (outcome === 'error') return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Please try again' }) });
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(outcome === 'emergency' ? { classification: { category: 'Emergency' }, outcome: 'emergency', emergency_message: 'Emergency care is needed.' } : { classification: { category: 'Severe' }, outcome: 'booking', doctors: [], severe_guidance: 'Choose the earliest slot.' }) });
  });
  await page.goto('/patient/book-appointment');
  await page.getByRole('textbox', { name: /Anything else/ }).fill('Symptoms to assess');
  await page.getByRole('button', { name: 'Show available slots' }).click();
  await expect(page.getByText(/No doctors with open slots/)).toBeVisible();
  await accessible(page);
  await expect(page.getByText('Severe', { exact: true })).toHaveCount(0);
  await page.getByRole('tab', { name: '1. Symptoms' }).click();
  outcome = 'emergency';
  await page.getByRole('button', { name: 'Show available slots' }).click();
  await expect(page.getByRole('alert')).toContainText('Please seek urgent medical care.');
  await accessible(page);
  await expect(page.getByText('Emergency', { exact: true })).toHaveCount(0);
  await page.getByRole('tab', { name: '1. Symptoms' }).click();
  outcome = 'error';
  await page.getByRole('button', { name: 'Show available slots' }).click();
  await expect(page.getByRole('alert')).toContainText('Please try again');
});

test('text-only intake submits without a dropdown selection or an old draft', async ({ page }) => {
  await fixtures(page);
  await page.addInitScript(() => sessionStorage.setItem('sahayog.intake.draft.patient', JSON.stringify({
    selectedIds: ['S001'], details: {}, freeText: 'Old catalogue draft'
  })));
  await page.goto('/patient/book-appointment');
  await expect(page.getByRole('button', { name: 'Show available slots' })).toBeDisabled();
  await expect(page.getByRole('spinbutton')).toHaveCount(0);
  await page.getByRole('textbox', { name: /Anything else/ }).fill('Palpitations since yesterday');
  const intake = page.waitForRequest(req => req.url().endsWith('/intake'));
  await page.getByRole('button', { name: 'Show available slots' }).click();
  const payload = (await intake).postDataJSON();
  expect(payload.symptoms).toEqual([]);
  expect(payload.free_text).toBe('Palpitations since yesterday');
  await expect(page.getByRole('button', { name: /Book .* with Dr. Test/ })).toBeVisible();
});

test('doctor signature navigation, consultation screen, and mobile accessibility', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem('sahayog.doctor.session', JSON.stringify({ profile: { id: 'doctor', full_name: 'Dr. Test Doctor', has_signature: true } })));
  const visit = { id: 'doctor-visit', status: 'SCHEDULED', severity: 'Normal', patient_name: 'Test Patient', patient_age: 30, patient_gender: 'female', symptoms: ['Palpitations'], starts_at: future, symptom_text: 'Two days' };
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    const data = path.endsWith('/settings') ? { show_speech_transcripts: true } : path.endsWith('/consultations') ? { consultations: [visit] } : path.endsWith('/transcript') ? { segments: [] } : path.endsWith('/soap') ? {} : visit;
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto('/doctor/signature');
  await accessible(page);
  await expect(page.getByRole('link', { name: 'Consultations', exact: true })).toHaveAttribute('href', '/doctor/consultations');
  await page.getByRole('link', { name: 'Consultations', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Consultations' })).toBeVisible();
  await accessible(page);
  await page.getByRole('button', { name: /Test Patient/ }).click();
  await expect(page.getByRole('button', { name: 'Start consultation' })).toBeDisabled();
  await accessible(page);
  await page.screenshot({ path: 'test-results/doctor-mobile.png', fullPage: true });
  await page.getByRole('link', { name: 'Profile', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Add your digital signature' })).toBeVisible();
});

test('landing and patient registration remain accessible at narrow widths', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.route('**/api/patients/lookup', route => route.fulfill({ contentType: 'application/json', body: '{"exists":false}' }));
  await page.goto('/');
  await accessible(page);
  await page.getByRole('button', { name: /Patient/ }).click();
  await accessible(page);
  await page.getByLabel(/Phone/).fill('9999999999');
  await page.getByLabel(/Password/).fill('test-password');
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByLabel(/Full name/)).toBeVisible();
  await accessible(page);
  await page.goto('/doctor/login');
  await accessible(page);
});
