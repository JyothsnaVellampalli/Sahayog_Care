import { test, expect } from '@playwright/test';

const medicine = { brand_id: 'BR001', brand: 'Brand A', generic_name: 'Generic A', composition: 'A', variant: '5 mg tablets', forms: ['Tablet'], specialty: 'cardiology', available_quantity: 20 };
const summary = { subjective: ['Recorded symptoms'], objective: [], assessment: [], plan: ['Reviewed plan'] };

async function fixtures(context) {
  await context.addInitScript(() => localStorage.setItem('sahayog.doctor.session', JSON.stringify({ profile: { id: 'doctor', full_name: 'Dr. Test', has_signature: true } })));
  const state = { stage: 'TRANSCRIPTION', items: [], reviewed: false, workspaceAt: null, queueCalls: 0 };
  await context.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let data;
    if (path.endsWith('/settings')) data = { show_speech_transcripts: true };
    else if (path.endsWith('/processing')) data = { jobs: state.stage === 'MISSING' ? [] : [
      ...(state.stage === 'TRANSCRIPTION' ? [] : [{ id: 'soap-job', kind: 'SOAP', state: state.stage === 'DONE' ? 'SUCCEEDED' : 'RUNNING' }]),
      { id: 'audio-job', kind: 'TRANSCRIPTION', state: state.stage === 'TRANSCRIPTION' ? 'RUNNING' : 'SUCCEEDED' },
    ] };
    else if (path.endsWith('/transcript')) data = { segments: state.stage === 'TRANSCRIPTION' ? [] : [{ text: 'Recorded symptoms' }] };
    else if (path.endsWith('/soap')) {
      if (method === 'POST') { state.queueCalls++; state.stage = 'SOAP'; data = { job: { id: 'soap-job', kind: 'SOAP', state: 'QUEUED' } }; }
      else data = { soap: state.stage === 'DONE' ? summary : null };
    } else if (path.endsWith('/medicines')) data = { items: [medicine], default_specialty: 'cardiology', specialties: ['cardiology'] };
    else if (path.endsWith('/workspace')) {
      state.items = route.request().postDataJSON().items; state.workspaceAt = new Date().toISOString(); state.reviewed = false;
      data = { updated_at: state.workspaceAt };
    } else if (path.endsWith('/prescription')) {
      if (method === 'PUT') { state.items = route.request().postDataJSON().items; state.reviewed = true; }
      data = { items: state.items, suggestions: [], reviewed: state.reviewed, soap_revision: state.stage === 'DONE' ? 'a'.repeat(64) : null, workspace_updated_at: state.workspaceAt };
    } else data = { id: 'visit', doctor_id: 'doctor', status: 'IN_PROGRESS', consent_recorded: true, patient_name: 'Test Patient', symptoms: [], starts_at: '2026-10-29T05:00:00Z' };
    return route.fulfill({ json: data });
  });
  return state;
}

for (const width of [1440, 390]) {
  test(`processing and medicine drafts survive closing the screen at ${width}px`, async ({ context, page }) => {
    const state = await fixtures(context);
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/doctor/consultations/visit');
    await expect(page.getByText(/Processing audio… Your recording is saved/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Generate SOAP', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: '+ Add medicine', exact: true }).click();
    await page.getByRole('dialog').getByRole('checkbox', { name: /Brand A/ }).check();
    await page.getByRole('button', { name: 'Add to prescription' }).click();
    await page.getByLabel('Dose for Brand A', { exact: true }).fill('1 tablet');
    await expect(page.getByText('Draft autosaved. Review it after SOAP is ready.')).toBeVisible();
    state.stage = 'SOAP';
    await expect(page.getByText(/Generating SOAP… You can select medicines/)).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('button', { name: 'Save prescription' })).toBeDisabled();
    await page.close();
    state.stage = 'DONE';
    const reopened = await context.newPage();
    await reopened.setViewportSize({ width, height: 900 });
    await reopened.goto('/doctor/consultations/visit');
    await expect(reopened.getByText('Reviewed plan', { exact: true })).toBeVisible();
    await expect(reopened.getByLabel('Dose for Brand A', { exact: true })).toHaveValue('1 tablet');
    await expect(reopened.getByRole('button', { name: 'Sign and close' })).toBeDisabled();
    expect(state.queueCalls).toBe(0); // completion is server-owned, not a mount-time model call
  });
}

test('missing SOAP offers a nonblocking recovery button and preserves in-flight medicine edits', async ({ context, page }) => {
  const state = await fixtures(context); state.stage = 'MISSING';
  await page.goto('/doctor/consultations/visit');
  await page.getByRole('button', { name: 'Generate SOAP', exact: true }).click();
  await expect(page.getByText(/Generating SOAP…/)).toBeVisible();
  expect(state.queueCalls).toBe(1);
  await page.getByRole('button', { name: '+ Add medicine', exact: true }).click();
  await page.getByRole('dialog').getByRole('checkbox', { name: /Brand A/ }).check();
  await page.getByRole('button', { name: 'Add to prescription' }).click();
  await page.getByLabel('Dose for Brand A', { exact: true }).fill('Doctor draft');
  state.stage = 'DONE';
  await expect(page.getByText('Reviewed plan', { exact: true })).toBeVisible({ timeout: 10000 });
  await expect(page.getByLabel('Dose for Brand A', { exact: true })).toHaveValue('Doctor draft');
});

test('a delayed initial summary read cannot erase a completed SOAP job', async ({ context, page }) => {
  const state = await fixtures(context); state.stage = 'DONE';
  let first = true;
  let release;
  let released;
  const delay = new Promise(resolve => { release = resolve; });
  const done = new Promise(resolve => { released = resolve; });
  await page.route('**/api/doctors/consultations/visit/soap', async route => {
    if (!first) return route.fallback();
    first = false;
    await delay;
    await route.fulfill({ json: { soap: null } });
    released();
  });
  await page.goto('/doctor/consultations/visit');
  await expect(page.getByText('Reviewed plan', { exact: true })).toBeVisible();
  release();
  await done;
  await expect(page.getByText('Reviewed plan', { exact: true })).toBeVisible();
  expect(state.queueCalls).toBe(0);
});
