"""Seed 10 realistic demo patients with multi-visit, linked consultation
histories for testing later phases (RAG / support chatbot over patient data).

Scope, deliberately kept simple for a throwaway test dataset (NOT the
coordinated, strictly-guarded `demo_patient_history` v1/v2 fixture used by
Phase 6's setup docs):

- 10 patients, phones +9196500001..+9196500010 (does not collide with
  existing demo/staff/doctor phones).
- 12 visit "tracks" across the 4 supported specialties (Cardiology,
  Orthopedics, Dermatology, Gastroenterology). 2 of the 10 patients
  (Vikram Choudhary, Meena Iyer) see doctors from two different
  specialties, each with their own independent linked series.
- Each track is a chain of 3-5 COMPLETED, linked appointments
  (`linked_appointment_id`), told as a realistic progression (initial
  complaint -> investigation -> treatment adjustment -> follow-up/resolution).
- Each visit gets a SOAP note, 0-2 medicines (real catalogue brand/medicine
  IDs), and most get a dummy lab/imaging report (blood test, X-ray, ECG,
  endoscopy, etc.). Each report is rendered as a one-page PDF shaped like a
  real report (header, patient/visit details, findings text, and - for
  imaging/waveform studies - an explicitly-labelled synthetic placeholder
  graphic with a caption, followed by the impression). No real scan,
  waveform or photograph is fabricated, only a clearly marked placeholder.
- Per the request: transcripts are NOT uploaded; `transcript_key` points to
  an empty JSON array, matching what a real empty transcript looks like.
- No prescriptions are frozen, and NO stock reservation/dispensing is
  touched; prescriptions are inserted as inactive, already-reviewed rows
  (consistent with how the existing historical demo-history fixture records
  closed-visit medicines without affecting pharmacy stock).

Idempotent: every ID is derived deterministically (uuid5) from a stable
seed name, and every insert uses upsert-on-primary-key, so re-running is
safe and will not duplicate rows.

Usage (from `backend`):
    .venv/Scripts/python.exe scripts/seed_demo_patients.py            # dry run: prints the plan only
    .venv/Scripts/python.exe scripts/seed_demo_patients.py --apply     # writes DB rows + storage objects
    .venv/Scripts/python.exe scripts/seed_demo_patients.py --apply --with-auth
        # also provisions Supabase Auth logins so patients can sign in.
        # Requires DEMO_PATIENT_PASSWORD (>=12 chars) in the environment.

Requires Phase 6 (`phase_6_followups_reports.sql`) and the prescription
tables (`consultation_prescriptions.sql`) already applied.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEED = 'sahayog/demo-seed/v1/'


def uid(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, SEED + name))


# --- Patients -----------------------------------------------------------

PATIENTS = {
    1: dict(full_name='Rajesh Kulkarni', dob='1967-03-12', gender='male', city='Pune'),
    2: dict(full_name='Sunita Patil', dob='1971-07-22', gender='female', city='Pune'),
    3: dict(full_name='Farhan Ali', dob='1996-01-05', gender='male', city='Pune'),
    4: dict(full_name='Lakshmi Reddy', dob='1980-11-02', gender='female', city='Pune'),
    5: dict(full_name='Deepak Sharma', dob='1991-05-18', gender='male', city='Pune'),
    6: dict(full_name='Anjali Nair', dob='1984-09-09', gender='female', city='Pune'),
    7: dict(full_name='Rohit Verma', dob='2003-02-28', gender='male', city='Pune'),
    8: dict(full_name='Priya Menon', dob='1988-04-14', gender='female', city='Pune'),
    9: dict(full_name='Vikram Choudhary', gender='male', dob='1994-08-30', city='Hyderabad'),
    10: dict(full_name='Meena Iyer', gender='female', dob='1965-12-20', city='Hyderabad'),
}
for n, p in PATIENTS.items():
    p['id'] = uid(f'patient/{n}')
    p['phone'] = f'+9196500{n:03d}'
    p['email'] = f'sahayog.seed.patient{n}@example.com'

MED = dict(  # (brand_id, strength_form, dose, frequency)
    telmisartan=('BR007', '40 mg tablet', '1 tablet', 'Once daily (morning)'),
    aspirin=('BR021', '75 mg tablet', '1 tablet', 'Once daily (after breakfast)'),
    atorvastatin=('BR005', '10 mg tablet', '1 tablet', 'Once daily (night)'),
    metoprolol=('BR015', '25 mg ER tablet', '1 tablet', 'Once daily (morning)'),
    clopidogrel=('BR017', '75 mg tablet', '1 tablet', 'Once daily (after breakfast)'),
    diclofenac=('BR025', '75 mg SR tablet', '1 tablet', 'Twice daily'),
    paracetamol=('BR038', '650 mg tablet', '1 tablet', 'Thrice daily, as needed for pain'),
    calcium_d3=('BR042', '500 mg + 250 IU tablet', '1 tablet', 'Once daily'),
    thiocolchicoside=('BR041', '4 mg tablet', '1 tablet', 'Twice daily'),
    clotrimazole=('BR056', '1% cream', 'Thin layer', 'Twice daily'),
    clobetasol=('BR053', '0.05% cream', 'Thin layer', 'Once daily (night)'),
    cetirizine=('BR049', '10 mg tablet', '1 tablet', 'Once daily (night)'),
    terbinafine=('BR060', '250 mg tablet', '1 tablet', 'Once daily'),
    pantoprazole=('BR065', '20 mg tablet', '1 tablet', 'Once daily (before breakfast)'),
    omeprazole=('BR070', '40 mg tablet', '1 tablet', 'Once daily (before breakfast)'),
    domperidone=('BR073', '30 mg SR tablet', '1 tablet', 'Once daily (before breakfast)'),
)


def rx(key, duration, instructions, quantity):
    brand_id, strength_form, dose, frequency = MED[key]
    return dict(brand_id=brand_id, strength_form=strength_form, dose=dose,
                frequency=frequency, duration=duration, instructions=instructions, quantity=quantity)


def report(report_type, title, **findings):
    return dict(report_type=report_type, title=title, findings=findings)


def report_pdf(patient_name, doctor_name, visit_date, report_row):
    """Render a findings-only report as a one-page PDF shaped like a real lab/imaging
    report: header, patient/visit details, findings text, then (for non-lab reports)
    an explicitly-labelled placeholder graphic panel with a caption below it, then the
    impression. No real scan/photograph/waveform is fabricated - only a clearly marked
    synthetic placeholder - matching this project's existing demo-data convention
    (see scripts/build_patient_history_seed.py).
    """
    from io import BytesIO
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfgen.canvas import Canvas

    findings = {k: v for k, v in report_row['findings'].items() if k not in ('impression', 'title', 'report_type')}
    impression = report_row['findings'].get('impression') or findings.pop('result', None) or 'Not specified.'
    has_image = report_row['report_type'] != 'LAB'

    output = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('DemoTitle', parent=styles['Title'], fontSize=19, leading=24,
                               textColor=colors.HexColor('#125c58'), spaceAfter=12))
    styles.add(ParagraphStyle('DemoBody', parent=styles['BodyText'], fontSize=10.5, leading=15, spaceAfter=8))
    styles.add(ParagraphStyle('DemoLabel', parent=styles['Heading2'], fontSize=12,
                               textColor=colors.HexColor('#125c58'), spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle('DemoBanner', parent=styles['BodyText'], fontSize=9, leading=13,
                               alignment=TA_CENTER, textColor=colors.HexColor('#7c3829'),
                               backColor=colors.HexColor('#fff2e7'), borderPadding=8))
    styles.add(ParagraphStyle('PlaceholderCaption', parent=styles['BodyText'], fontSize=9, leading=12,
                               alignment=TA_CENTER, textColor=colors.HexColor('#7a7a7a')))

    def para(text, style='DemoBody'):
        return Paragraph(escape(str(text)), styles[style])

    story = [para('SAHAYOG CARE / DEMONSTRATION RECORD', 'DemoLabel'), para(report_row['title'], 'DemoTitle'),
             para('SYNTHETIC DATA - NOT A REAL PATIENT OR CLINICAL REPORT', 'DemoBanner'), Spacer(1, 16)]

    details = [('Patient', patient_name), ('Referring doctor', doctor_name), ('Report date', visit_date),
               ('Report type', report_row['report_type'].replace('_', ' ').title())]
    table = Table([[para(label), para(value)] for label, value in details], colWidths=[130, 360])
    table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f1f7f6')),
                                ('LEFTPADDING', (0, 0), (-1, -1), 10), ('TOPPADDING', (0, 0), (-1, -1), 5),
                                ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
    story += [table, para('Findings', 'DemoLabel')]
    story += [para(f"{key.replace('_', ' ')}: {value}") for key, value in findings.items()] or [para('See impression below.')]

    if has_image:
        placeholder = Table([[para('Illustrative placeholder only - synthetic demonstration graphic.\n'
                                    'Not an actual radiograph, scan, waveform or photograph.', 'PlaceholderCaption')]],
                             colWidths=[460], rowHeights=[150])
        placeholder.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#b9c4c2')),
                                          ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eef3f2')),
                                          ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
        story += [Spacer(1, 10), placeholder, para(f"Fig. 1 - {report_row['title']}", 'PlaceholderCaption'), Spacer(1, 10)]

    story += [para('Impression', 'DemoLabel'), para(impression), para('Record notes', 'DemoLabel'),
              para('Fictional demonstration document for application testing. No real laboratory result, '
                   'radiology image, waveform or clinician attestation is supplied.')]

    def footer(canvas, doc):
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#52665f'))
        canvas.drawString(48, 32, 'Sahayog Care | Synthetic seed data | Not for clinical use')
        canvas.drawRightString(A4[0] - 48, 32, f'Page {doc.page}')

    class StableCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            kwargs['invariant'] = 1
            super().__init__(*args, **kwargs)

    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=48, rightMargin=48, topMargin=36, bottomMargin=48,
                             title=report_row['title'], author='Sahayog Care - Synthetic fixtures')
    doc.build(story, onFirstPage=footer, onLaterPages=footer, canvasmaker=StableCanvas)
    return output.getvalue()


def visit(days_ago, reason, severity, symptom_text, symptoms, subjective, objective,
          assessment, plan, medicines=None, reports=None):
    return dict(days_ago=days_ago, reason=reason, severity=severity, symptom_text=symptom_text,
                symptoms=symptoms, soap=dict(subjective=subjective, objective=objective,
                assessment=assessment, plan=plan), medicines=medicines or [], reports=reports or [])


# --- Tracks: one linked visit series per (patient, specialty) -----------
# days_ago values must strictly decrease within a track (oldest first).

TRACKS = [

# 1. Cardiology - Rajesh Kulkarni - hypertension / exertional chest tightness workup.
dict(patient=1, doctor_code='CARD-01', visits=[
  visit(140, 'Cardiology - exertional chest tightness', 'Severe',
    'I get a heavy, pressing feeling in my chest when I climb stairs or walk fast, it goes away after '
    'resting a few minutes. Happening on and off for 2 weeks. Also feel tired a lot lately.',
    ['Chest tightness during physical activity', 'Shortness of breath on exertion', 'Persistent fatigue'],
    ['58-year-old male, exertional chest tightness for 2 weeks, relieved by rest.',
     'Denies chest pain at rest; no radiation to arm, jaw or back today.', 'Reports fatigue with daily activity.'],
    ['BP 158/96 mmHg, HR 88/min, SpO2 97% on room air.', 'Resting ECG: sinus rhythm, no acute ST-T changes.',
     'No pedal oedema; chest clear on auscultation.'],
    ['Pattern consistent with stable exertional angina; newly noted hypertension.',
     'Cardiac risk factors: sedentary lifestyle, family history of coronary artery disease.'],
    ['Start telmisartan and low-dose aspirin as charted.', 'Order fasting lipid profile.',
     'Advise daily walking as tolerated, low-salt diet; review in 3 weeks with lipid results.'],
    medicines=[rx('telmisartan', '21 days', 'Take in the morning', 21), rx('aspirin', '21 days', 'After breakfast', 21)],
    reports=[report('CARDIOLOGY', 'Resting ECG', impression='Sinus rhythm, no acute ischemic changes.')]),
  visit(105, 'Cardiology follow-up - hypertension and lipid review', 'Normal',
    'Chest tightness is less frequent now, maybe once a week when I rush. The BP medicine seems to help. '
    'Still feel a bit tired by evening.',
    ['Chest tightness during physical activity', 'Persistent fatigue'],
    ['Reports improved exertional symptoms on current therapy.', 'Reviewing fasting lipid profile today.'],
    ['BP 136/88 mmHg, HR 80/min.', 'Lipid profile: LDL 162 mg/dL (high), HDL 38 mg/dL, triglycerides 180 mg/dL.'],
    ['Partial response to antihypertensive; dyslipidemia confirmed, LDL above target for cardiac risk.'],
    ['Add atorvastatin at night.', 'Continue telmisartan and aspirin.', 'Order treadmill stress test; review in 5 weeks.'],
    medicines=[rx('telmisartan', '35 days', 'Take in the morning', 35), rx('aspirin', '35 days', 'After breakfast', 35),
               rx('atorvastatin', '35 days', 'At night', 35)],
    reports=[report('LAB', 'Fasting Lipid Profile', LDL='162 mg/dL (high)', HDL='38 mg/dL',
                     Triglycerides='180 mg/dL', impression='Dyslipidemia, LDL above target.')]),
  visit(70, 'Cardiology follow-up - stress test review', 'Normal',
    'Feeling much better, barely notice the chest tightness now even on stairs. Completed the treadmill test last week.',
    ['Chest tightness during physical activity'],
    ['Reports resolution of exertional chest tightness.', 'Reviewing treadmill stress test performed last week.'],
    ['BP 128/82 mmHg, HR 76/min.', 'Treadmill stress test: negative for ischemia at 8.5 METs achieved workload.'],
    ['Good response to therapy; no evidence of inducible ischemia.'],
    ['Continue current medicines unchanged.', 'Continue lifestyle measures; review in 5 weeks.'],
    medicines=[rx('telmisartan', '35 days', 'Take in the morning', 35), rx('aspirin', '35 days', 'After breakfast', 35),
               rx('atorvastatin', '35 days', 'At night', 35)],
    reports=[report('CARDIOLOGY', 'Treadmill Stress Test (TMT)',
                     result='Negative for ischemia, 8.5 METs achieved', impression='No inducible ischemia.')]),
  visit(35, 'Cardiology follow-up - new palpitations', 'Normal',
    'Noticed my heart fluttering for a few seconds, two or three times this week. No chest pain or dizziness with it.',
    ['Palpitations (pounding or fluttering heartbeat)'],
    ['Reports brief self-terminating palpitations, no associated chest pain, syncope or dizziness.'],
    ['BP 124/80 mmHg, HR 78/min regular at rest.', '24-hour Holter monitor: rare isolated ectopic beats, no sustained arrhythmia.'],
    ['Benign ectopy, unlikely to need rhythm-specific treatment at this time.'],
    ['Reassurance; reduce caffeine intake.', 'Continue current cardiac medicines; review in 10 weeks.'],
    medicines=[rx('telmisartan', '70 days', 'Take in the morning', 70), rx('aspirin', '70 days', 'After breakfast', 70),
               rx('atorvastatin', '70 days', 'At night', 70)],
    reports=[report('CARDIOLOGY', '24-hour Holter Monitor', result='Rare isolated ectopic beats',
                     impression='No sustained arrhythmia.')]),
  visit(10, 'Cardiology routine follow-up', 'Normal',
    'Doing well, no chest discomfort or palpitations since last visit. Taking all medicines regularly.',
    ['Persistent fatigue'],
    ['Asymptomatic; reports good adherence to medicines.'],
    ['BP 122/78 mmHg, HR 74/min.', 'No new ECG changes.'],
    ['Hypertension and dyslipidemia well controlled; no residual cardiac symptoms.'],
    ['Continue current medicines.', 'Routine review in 3 months with repeat lipid profile.'],
    medicines=[rx('telmisartan', '90 days', 'Take in the morning', 90), rx('aspirin', '90 days', 'After breakfast', 90),
               rx('atorvastatin', '90 days', 'At night', 90)]),
]),

# 2. Orthopedics - Sunita Patil - knee osteoarthritis.
dict(patient=2, doctor_code='ORTH-02', visits=[
  visit(120, 'Orthopedics - right knee pain', 'Severe',
    'My right knee has been paining for about a month, worse when I climb stairs or get up from sitting. '
    'Some swelling in the evening. No injury that I remember.',
    ['Joint pain', 'Swelling'],
    ['54-year-old female with 1-month history of right knee pain, worse on stairs and rising from sitting.',
     'Reports evening swelling; denies trauma, fever or morning stiffness over 30 minutes.'],
    ['Right knee: mild effusion, crepitus on movement, tenderness over medial joint line.',
     'Range of motion mildly reduced; no instability on examination.'],
    ['Clinical picture consistent with early right knee osteoarthritis.'],
    ['Order X-ray right knee (AP/lateral).', 'Start diclofenac and calcium with vitamin D3.',
     'Advise weight management and quadriceps strengthening exercises; review in 3 weeks with X-ray.'],
    medicines=[rx('diclofenac', '14 days', 'After food', 28), rx('calcium_d3', '30 days', 'After breakfast', 30)],
    reports=[report('IMAGING', 'X-Ray Right Knee (AP/Lateral)',
                     impression='Mild joint space narrowing, early osteophyte formation, medial compartment.')]),
  visit(95, 'Orthopedics follow-up - knee osteoarthritis', 'Normal',
    'Pain has reduced a bit with the tablets. Still some discomfort climbing stairs. Swelling is less now.',
    ['Joint pain'],
    ['Reports partial relief with NSAID course; residual discomfort on stairs.'],
    ['Right knee: minimal effusion, tenderness reduced, range of motion improved.'],
    ['Early osteoarthritis, grade 1-2 changes on X-ray, responding to conservative management.'],
    ['Continue calcium and vitamin D3.', 'Start physiotherapy for quadriceps strengthening.',
     'Ordered ESR/CRP given persistent evening swelling, to rule out an inflammatory cause before '
     'attributing it solely to osteoarthritis.', 'Use diclofenac only during flare-ups going forward; review in 4 weeks.'],
    medicines=[rx('calcium_d3', '30 days', 'After breakfast', 30)],
    reports=[report('LAB', 'ESR & CRP', ESR='18 mm/hr (mildly elevated)', CRP='4 mg/L (within normal limits)',
                     impression='Mild ESR elevation only; CRP normal. Does not suggest an active inflammatory '
                                 'arthritis; consistent with mechanical osteoarthritis.')]),
  visit(65, 'Orthopedics follow-up - knee osteoarthritis', 'Normal',
    'Physiotherapy is helping, stairs are easier now. Occasional mild ache after a long walk.',
    ['Joint pain'],
    ['Reports good response to physiotherapy and activity modification.'],
    ['Right knee: no effusion, good quadriceps tone, full range of motion.'],
    ['Osteoarthritis symptoms well controlled with conservative measures.'],
    ['Continue home exercise programme and calcium/vitamin D3.', 'Review in 8 weeks or sooner if symptoms flare.'],
    medicines=[rx('calcium_d3', '60 days', 'After breakfast', 60)]),
  visit(20, 'Orthopedics routine follow-up', 'Normal',
    'Knee feels fine most days, manage long walks without much trouble now.',
    ['Joint pain'],
    ['Reports sustained improvement, mild occasional ache only after prolonged activity.'],
    ['Right knee: stable examination, no effusion, full range of motion.'],
    ['Osteoarthritis stable on conservative management.'],
    ['Continue home exercises and calcium/vitamin D3.', 'Routine review in 6 months, sooner if symptoms worsen.'],
    medicines=[rx('calcium_d3', '90 days', 'After breakfast', 90)]),
]),

# 3. Dermatology - Farhan Ali - atopic eczema flare.
dict(patient=3, doctor_code='DERM-01', visits=[
  visit(60, 'Dermatology - itchy rash on arms', 'Normal',
    'I have an itchy, dry, red rash on both forearms for about 10 days. Gets worse at night. I have had '
    'eczema before as a child.',
    ['Dry, itchy skin patches'],
    ['29-year-old male with 10-day history of itchy erythematous rash on both forearms, worse at night.',
     'Past history of childhood eczema.'],
    ['Bilateral forearms: erythematous, dry, excoriated plaques; no signs of secondary infection.'],
    ['Atopic eczema flare.'],
    ['Start topical clobetasol for 1 week and oral cetirizine for itching.',
     'Advise fragrance-free moisturiser twice daily and avoiding hot water baths; review in 2 weeks.'],
    medicines=[rx('clobetasol', '7 days', 'Thin layer at night only', 1), rx('cetirizine', '14 days', 'At night', 14)]),
  visit(44, 'Dermatology follow-up - eczema', 'Normal',
    'Rash has calmed down a lot, much less itchy. Skin is still a bit dry.',
    ['Dry, itchy skin patches'],
    ['Reports marked improvement in itching and redness.'],
    ['Forearms: residual dryness, erythema largely resolved, no excoriation.'],
    ['Eczema flare resolving well with treatment.'],
    ['Stop clobetasol; continue moisturiser regularly.', 'Continue cetirizine only if itching recurs; review in 4 weeks.'],
    medicines=[rx('cetirizine', '14 days', 'At night, only if itching recurs', 14)]),
  visit(15, 'Dermatology routine follow-up', 'Normal',
    'Skin has been fine, no rash or itching for the past few weeks. Using moisturiser daily.',
    ['Dry, itchy skin patches'],
    ['Asymptomatic; reports good skin hydration with regular moisturiser use.'],
    ['Forearms: normal skin texture, no erythema or excoriation.'],
    ['Eczema flare resolved; good control with emollients.'],
    ['Continue daily moisturiser.', 'Return if flare recurs; no medicines needed at this time.']),
]),

# 4. Gastroenterology - Lakshmi Reddy - GERD.
dict(patient=4, doctor_code='GAST-01', visits=[
  visit(130, 'Gastroenterology - heartburn and acid reflux', 'Normal',
    'Burning sensation in my chest after meals, especially spicy food, for the last 3 weeks. Also a sour '
    'taste in my mouth sometimes at night.',
    ['Heartburn after meals', 'Acid regurgitation'],
    ['45-year-old female, 3-week history of postprandial burning chest sensation and nocturnal acid regurgitation.',
     'Reports worsening with spicy food and lying down soon after meals.'],
    ['Abdomen soft, non-tender; no alarm features such as weight loss, vomiting blood or difficulty swallowing.'],
    ['Clinical picture consistent with gastro-oesophageal reflux disease (GERD).'],
    ['Start pantoprazole before breakfast.', 'Advise smaller meals, avoiding spicy/fried food and late-night eating, '
     'elevating head of bed.', 'Review in 4 weeks; plan upper GI endoscopy if symptoms persist.'],
    medicines=[rx('pantoprazole', '28 days', 'Before breakfast, empty stomach', 28)]),
  visit(100, 'Gastroenterology follow-up - GERD', 'Normal',
    'Burning sensation is much better with the medicine and diet changes. Still get mild discomfort occasionally.',
    ['Heartburn after meals'],
    ['Reports good symptomatic response to pantoprazole and dietary changes.'],
    ['Abdomen soft, non-tender.'],
    ['GERD, partial symptomatic control.'],
    ['Continue pantoprazole.', 'Reinforce dietary advice; review in 6 weeks.'],
    medicines=[rx('pantoprazole', '42 days', 'Before breakfast, empty stomach', 42)]),
  visit(55, 'Gastroenterology follow-up - persistent reflux', 'Normal',
    'Still get occasional burning, mostly after dinner if I eat late. No vomiting or difficulty swallowing.',
    ['Heartburn after meals', 'Acid regurgitation'],
    ['Reports residual postprandial symptoms related to late meals; no alarm features.'],
    ['Upper GI endoscopy performed: mild oesophagitis (LA Grade A), no Barrett\'s changes, no ulcer.'],
    ['Mild erosive GERD confirmed on endoscopy.'],
    ['Switch to omeprazole for better symptom control.', 'Continue lifestyle measures; review in 6 weeks.'],
    medicines=[rx('omeprazole', '42 days', 'Before breakfast, empty stomach', 42)],
    reports=[report('GASTROENTEROLOGY', 'Upper GI Endoscopy',
                     impression='Mild erosive oesophagitis (LA Grade A), no Barrett\'s changes, no ulcer.')]),
  visit(15, 'Gastroenterology routine follow-up', 'Normal',
    'Much better now, hardly any burning sensation. Managing to avoid late dinners most days.',
    ['Heartburn after meals'],
    ['Reports near-complete resolution of reflux symptoms.'],
    ['Abdomen soft, non-tender.'],
    ['Mild erosive GERD, good response to therapy and lifestyle changes.'],
    ['Continue omeprazole for 4 more weeks then step down to as-needed use.', 'Routine review in 3 months.'],
    medicines=[rx('omeprazole', '28 days', 'Before breakfast, empty stomach', 28)]),
]),

# 5. Orthopedics - Deepak Sharma - tibia fracture recovery.
dict(patient=5, doctor_code='ORTH-05', visits=[
  visit(150, 'Orthopedics - leg injury, road accident', 'Severe',
    'I fell off my motorcycle and my right lower leg is badly swollen and I cannot put weight on it. '
    'Severe pain since the accident this morning.',
    ['Severe pain after an injury', 'Unable to bear weight on a leg'],
    ['34-year-old male, acute right lower leg pain and swelling following a road traffic accident today.',
     'Unable to bear weight; denies loss of sensation in the foot.'],
    ['Right leg: marked swelling and deformity over mid-shaft tibia, severe tenderness; foot warm, pulses palpable, '
     'sensation intact.', 'X-ray tibia-fibula: displaced mid-shaft tibia fracture.'],
    ['Closed displaced mid-shaft tibia fracture, neurovascularly intact.'],
    ['Apply below-knee cast after closed reduction.', 'Start paracetamol for pain and calcium/vitamin D3.',
     'Strict non-weight-bearing; review in 2 weeks with repeat X-ray.'],
    medicines=[rx('paracetamol', '7 days', 'As needed for pain', 21), rx('calcium_d3', '30 days', 'After breakfast', 30)],
    reports=[report('IMAGING', 'X-Ray Tibia-Fibula (AP/Lateral)',
                     impression='Displaced mid-shaft tibial fracture, closed, neurovascularly intact limb.')]),
  visit(136, 'Orthopedics follow-up - cast check', 'Normal',
    'Cast is comfortable, swelling has reduced. Pain is much less now unless I move the leg.',
    ['Severe pain after an injury'],
    ['Reports reduced pain and swelling under cast immobilisation.'],
    ['Cast intact, no pressure areas; toes warm with good capillary refill.',
     'Repeat X-ray: fracture alignment maintained, early callus formation.'],
    ['Fracture healing on track with cast immobilisation.'],
    ['Continue non-weight-bearing in cast.', 'Continue calcium/vitamin D3.', 'Review in 4 weeks with repeat X-ray.'],
    medicines=[rx('calcium_d3', '30 days', 'After breakfast', 30)],
    reports=[report('IMAGING', 'X-Ray Tibia-Fibula - Follow-up',
                     impression='Alignment maintained, early callus formation.')]),
  visit(105, 'Orthopedics follow-up - cast removal', 'Normal',
    'Feels much stronger now. No pain at rest, only slight stiffness in the ankle.',
    ['Joint pain'],
    ['Reports resolution of rest pain; mild ankle stiffness.'],
    ['Cast removed; healing fracture site non-tender, mild ankle stiffness, no deformity.',
     'Repeat X-ray: good callus formation, fracture line less distinct.'],
    ['Fracture healing well; ready to begin partial weight-bearing and rehabilitation.'],
    ['Start physiotherapy for ankle and knee mobilisation.', 'Begin partial weight-bearing with crutches; review in 4 weeks.'],
    reports=[report('IMAGING', 'X-Ray Tibia-Fibula - Union Check',
                     impression='Good callus formation, fracture line less distinct, healing satisfactorily.')]),
  visit(70, 'Orthopedics follow-up - rehabilitation', 'Normal',
    'Walking with crutches is going well, started putting more weight on the leg as advised. Some mild ache by evening.',
    ['Joint pain'],
    ['Reports progressing well with partial weight-bearing and physiotherapy.'],
    ['Gait improving; mild residual swelling by end of day; no tenderness over fracture site.'],
    ['Fracture clinically united; progressing through rehabilitation.'],
    ['Advance to full weight-bearing as tolerated.', 'Continue physiotherapy; review in 6 weeks.']),
  visit(15, 'Orthopedics final follow-up', 'Normal',
    'Walking normally now without crutches, no pain. Back to most daily activities.',
    ['Joint pain'],
    ['Reports full return to weight-bearing activity without pain.'],
    ['Full painless range of motion at knee and ankle; normal gait; no residual deformity.'],
    ['Tibial fracture fully healed with good functional recovery.'],
    ['Discharge from orthopedic follow-up.', 'Advised to resume sports gradually and return if any new symptoms.']),
]),

# 6. Cardiology - Anjali Nair - palpitations / SVT workup.
dict(patient=6, doctor_code='CARD-03', visits=[
  visit(80, 'Cardiology - sudden episodes of racing heartbeat', 'Severe',
    'Sometimes my heart suddenly starts racing very fast for a few minutes, then stops on its own. Happened '
    '3 times this month. Feel a bit dizzy during the episode but no fainting.',
    ['Racing heartbeat (tachycardia)', 'Lightheadedness or near-fainting'],
    ['41-year-old female with recurrent episodes of abrupt-onset rapid heartbeat lasting minutes, '
     'self-terminating, associated with mild lightheadedness.', 'Denies chest pain or syncope.'],
    ['BP 118/76 mmHg, HR 82/min regular at rest.', 'Resting ECG: normal sinus rhythm, no delta wave or pre-excitation.'],
    ['Clinical picture suggestive of paroxysmal supraventricular tachycardia (SVT).'],
    ['Order 24-hour Holter monitor and echocardiography.', 'Advise vagal manoeuvres if an episode recurs; review in 3 weeks.'],
    reports=[report('CARDIOLOGY', '2D Echocardiography', impression='Structurally normal heart, normal LV function.')]),
  visit(59, 'Cardiology follow-up - SVT workup', 'Normal',
    'Had one more episode during the monitoring week, it lasted about 5 minutes. Otherwise feeling fine.',
    ['Racing heartbeat (tachycardia)'],
    ['Reports one captured episode during Holter monitoring.'],
    ['24-hour Holter monitor: captured episode of paroxysmal SVT, rate 165/min, self-terminating; otherwise normal sinus rhythm.'],
    ['Confirmed paroxysmal SVT; structurally normal heart on echocardiography.'],
    ['Start metoprolol for rate control and symptom prevention.', 'Discuss electrophysiology referral if episodes continue; review in 6 weeks.'],
    medicines=[rx('metoprolol', '42 days', 'Morning', 42)],
    reports=[report('CARDIOLOGY', '24-hour Holter Monitor',
                     impression='Captured paroxysmal SVT episode, rate 165/min, self-terminating.')]),
  visit(15, 'Cardiology routine follow-up', 'Normal',
    'No episodes since starting the new tablet. Feeling normal, no dizziness.',
    ['Persistent fatigue'],
    ['Reports no further palpitation episodes on beta-blocker therapy.'],
    ['BP 112/72 mmHg, HR 68/min regular.'],
    ['Good symptomatic control of paroxysmal SVT on metoprolol.'],
    ['Continue metoprolol.', 'Routine review in 3 months; electrophysiology referral only if episodes recur.'],
    medicines=[rx('metoprolol', '90 days', 'Morning', 90)]),
]),

# 7. Dermatology - Rohit Verma - acne vulgaris.
dict(patient=7, doctor_code='DERM-04', visits=[
  visit(90, 'Dermatology - facial acne', 'Normal',
    'I have had pimples on my face, mostly cheeks and forehead, for a few months. Getting worse and leaving '
    'some dark marks. Affecting my confidence.',
    ['Facial acne breakouts'],
    ['22-year-old male with several months of facial acne, worsening, with post-inflammatory hyperpigmentation.'],
    ['Face: multiple comedones and papulopustular lesions over cheeks and forehead, mild post-inflammatory '
     'hyperpigmentation, no nodulocystic lesions.'],
    ['Moderate papulopustular acne vulgaris.'],
    ['Start topical adapalene at night.', 'Advise gentle non-comedogenic cleanser, avoid picking lesions; review in 4 weeks.']),
  visit(62, 'Dermatology follow-up - acne', 'Normal',
    'Some improvement, fewer new pimples. Skin felt a bit dry and irritated for the first week.',
    ['Facial acne breakouts'],
    ['Reports partial improvement; initial retinoid irritation now settled.'],
    ['Face: reduced active lesion count, mild residual hyperpigmentation.'],
    ['Acne vulgaris, responding to topical retinoid therapy.'],
    ['Continue adapalene at night.', 'Add moisturiser for dryness; review in 6 weeks.']),
  visit(20, 'Dermatology follow-up - acne', 'Normal',
    'Face looks much clearer now, only an occasional small pimple during stressful weeks at college.',
    ['Facial acne breakouts'],
    ['Reports significant improvement, infrequent minor breakouts.'],
    ['Face: few residual comedones, hyperpigmentation fading, no active pustules.'],
    ['Acne vulgaris, good response to treatment.'],
    ['Continue adapalene at night, reduce to alternate nights if skin feels dry.', 'Review in 8 weeks.']),
  visit(4, 'Dermatology routine follow-up', 'Normal',
    'Skin is looking good overall, dark marks are fading. Happy with the progress.',
    ['Facial acne breakouts'],
    ['Reports sustained improvement and fading pigmentation.'],
    ['Face: minimal active lesions, fading post-inflammatory marks.'],
    ['Acne vulgaris well controlled; post-inflammatory hyperpigmentation improving.'],
    ['Continue adapalene alternate nights for maintenance.', 'Routine review in 3 months or sooner if flare.']),
]),

# 8. Gastroenterology - Priya Menon - gastritis / H. pylori.
dict(patient=8, doctor_code='GAST-03', visits=[
  visit(75, 'Gastroenterology - upper abdominal pain', 'Normal',
    'Burning pain in my upper stomach, especially when hungry, for about 2 weeks. Feel bloated and a bit nauseous '
    'sometimes after meals.',
    ['Upper abdominal burning pain', 'Bloating'],
    ['37-year-old female with 2-week history of epigastric burning pain, worse on empty stomach, with bloating and '
     'occasional nausea.'],
    ['Abdomen: mild epigastric tenderness, no guarding or rebound; no pallor.'],
    ['Clinical picture consistent with gastritis; rule out H. pylori infection.'],
    ['Order H. pylori stool antigen test.', 'Start pantoprazole and domperidone.',
     'Advise smaller frequent meals, avoid NSAIDs and caffeine; review in 3 weeks with test result.'],
    medicines=[rx('pantoprazole', '21 days', 'Before breakfast, empty stomach', 21),
               rx('domperidone', '14 days', 'Before meals', 14)]),
  visit(54, 'Gastroenterology follow-up - H. pylori positive', 'Normal',
    'Pain has improved somewhat but not completely. Test result came back from the lab.',
    ['Upper abdominal burning pain'],
    ['Reports partial symptomatic improvement; reviewing H. pylori test result.'],
    ['H. pylori stool antigen: positive.', 'Abdomen: mild residual epigastric tenderness.'],
    ['Confirmed H. pylori-associated gastritis.'],
    ['Start H. pylori eradication therapy per standard regimen (prescribed separately by pharmacy protocol).',
     'Continue pantoprazole through eradication course; review in 4 weeks.'],
    medicines=[rx('pantoprazole', '28 days', 'Before breakfast, empty stomach', 28)],
    reports=[report('LAB', 'H. pylori Stool Antigen Test', result='Positive',
                     impression='Confirms H. pylori-associated gastritis.')]),
  visit(20, 'Gastroenterology routine follow-up', 'Normal',
    'Feeling much better, pain is gone, eating normally without discomfort now.',
    ['Upper abdominal burning pain'],
    ['Reports complete resolution of symptoms after eradication therapy.'],
    ['Abdomen: non-tender, soft.'],
    ['H. pylori gastritis, symptomatic resolution after treatment.'],
    ['Continue pantoprazole for 2 more weeks then stop.', 'No further follow-up needed unless symptoms recur.'],
    medicines=[rx('pantoprazole', '14 days', 'Before breakfast, empty stomach', 14)]),
]),

# 9a. Orthopedics - Vikram Choudhary - ankle sprain.
dict(patient=9, doctor_code='ORTH-01', visits=[
  visit(50, 'Orthopedics - twisted ankle playing football', 'Severe',
    'Twisted my left ankle badly playing football yesterday. It is swollen and painful to walk on.',
    ['Severe pain after an injury', 'Unable to bear weight on a leg'],
    ['31-year-old male, acute left ankle injury during sports yesterday, pain and swelling, difficulty '
     'weight-bearing.'],
    ['Left ankle: moderate swelling and bruising over lateral malleolus, tender, no obvious deformity, pulses intact.',
     'X-ray ankle: no fracture seen.'],
    ['Grade 2 lateral ankle ligament sprain, no fracture.'],
    ['Apply RICE protocol (rest, ice, compression, elevation) and ankle brace.',
     'Start diclofenac for pain; non-weight-bearing with crutches for a few days; review in 2 weeks.'],
    medicines=[rx('diclofenac', '7 days', 'After food', 14)],
    reports=[report('IMAGING', 'X-Ray Left Ankle (AP/Lateral/Mortise)', impression='No fracture identified.')]),
  visit(36, 'Orthopedics follow-up - ankle sprain', 'Normal',
    'Swelling has gone down a lot. Can walk short distances now but ankle still feels a bit weak.',
    ['Joint pain'],
    ['Reports reduced swelling, improving weight-bearing tolerance.'],
    ['Left ankle: mild residual swelling, stable on stress testing, improving range of motion.'],
    ['Lateral ligament sprain healing well.'],
    ['Start physiotherapy for ankle strengthening and proprioception.', 'Wean off crutches as tolerated; review in 4 weeks.']),
  visit(8, 'Orthopedics final follow-up', 'Normal',
    'Ankle feels strong again, back to light jogging without pain.',
    ['Joint pain'],
    ['Reports full functional recovery, resuming light sporting activity.'],
    ['Left ankle: full painless range of motion, stable ligaments on stress testing.'],
    ['Ankle sprain fully healed with good functional recovery.'],
    ['Discharge from orthopedic follow-up.', 'Advised gradual return to full sport with continued ankle brace during football for a month.']),
]),

# 9b. Dermatology - Vikram Choudhary - fungal skin infection (separate, unlinked series).
dict(patient=9, doctor_code='DERM-02', visits=[
  visit(200, 'Dermatology - itchy ring-shaped rash on thigh', 'Normal',
    'An itchy, ring-shaped red patch on my inner thigh for about a week, slowly getting bigger. Gets worse '
    'with sweating.',
    ['Dry, itchy skin patches'],
    ['31-year-old male with 1-week history of an enlarging, itchy, annular rash on the inner thigh.'],
    ['Left inner thigh: well-demarcated annular erythematous plaque with central clearing and scaly active border.',
     'KOH mount of skin scraping: branching hyphae seen.'],
    ['Tinea corporis (dermatophyte skin infection).'],
    ['Start oral terbinafine.', 'Advise keeping the area dry, loose cotton clothing, not sharing towels; review in 3 weeks.'],
    medicines=[rx('terbinafine', '14 days', 'Once daily', 14)],
    reports=[report('DERMATOLOGY', 'KOH Mount / Fungal Scraping', result='Branching hyphae seen',
                     impression='Confirms dermatophyte (fungal) infection.')]),
  visit(179, 'Dermatology follow-up - tinea corporis', 'Normal',
    'Rash is fading, much less itchy. Almost finished the tablets.',
    ['Dry, itchy skin patches'],
    ['Reports good response to antifungal therapy.'],
    ['Left inner thigh: resolving plaque, mild residual pigmentation, no active scaly border.'],
    ['Tinea corporis resolving well.'],
    ['Complete remaining course of terbinafine.', 'Continue hygiene measures; review in 3 weeks.']),
  visit(158, 'Dermatology routine follow-up', 'Normal',
    'Rash is completely gone now, just a faint mark left. No itching.',
    ['Dry, itchy skin patches'],
    ['Asymptomatic; reports complete resolution.'],
    ['Left inner thigh: no active lesion, faint post-inflammatory pigmentation only.'],
    ['Tinea corporis resolved.'],
    ['No further medicines needed.', 'Advised to return if the rash recurs.']),
]),

# 10a. Cardiology - Meena Iyer - palpitations and hypertension.
dict(patient=10, doctor_code='CARD-02', visits=[
  visit(95, 'Cardiology - palpitations and raised blood pressure', 'Severe',
    'Noticed my heart pounding occasionally over the last 2 weeks, and the pharmacy checked my BP which was '
    'quite high. Mild headache at times.',
    ['Palpitations (pounding or fluttering heartbeat)', 'Persistent fatigue'],
    ['60-year-old female with 2-week history of intermittent palpitations and incidentally noted elevated '
     'blood pressure, mild headache.'],
    ['BP 168/98 mmHg, HR 90/min irregular.', 'ECG: atrial fibrillation with controlled ventricular rate.'],
    ['Newly diagnosed atrial fibrillation with uncontrolled hypertension.'],
    ['Start metoprolol for rate control and clopidogrel for stroke-risk reduction, plus telmisartan for blood pressure.',
     'Order echocardiography; review in 3 weeks.'],
    medicines=[rx('metoprolol', '21 days', 'Morning', 21), rx('clopidogrel', '21 days', 'After breakfast', 21),
               rx('telmisartan', '21 days', 'Morning', 21)],
    reports=[report('CARDIOLOGY', 'Resting ECG', impression='Atrial fibrillation, controlled ventricular rate.')]),
  visit(74, 'Cardiology follow-up - atrial fibrillation', 'Normal',
    'Feeling steadier, fewer episodes of pounding heart. Blood pressure readings at home are better too.',
    ['Palpitations (pounding or fluttering heartbeat)'],
    ['Reports improved symptom control on current regimen.'],
    ['BP 138/86 mmHg, HR 76/min, rhythm still irregular on palpation.',
     '2D Echocardiography: mildly dilated left atrium, normal LV systolic function.'],
    ['Atrial fibrillation with rate control; hypertension improving.'],
    ['Continue current medicines.', 'Reinforce home BP monitoring; review in 6 weeks.'],
    medicines=[rx('metoprolol', '42 days', 'Morning', 42), rx('clopidogrel', '42 days', 'After breakfast', 42),
               rx('telmisartan', '42 days', 'Morning', 42)],
    reports=[report('CARDIOLOGY', '2D Echocardiography',
                     impression='Mildly dilated left atrium, normal LV systolic function.')]),
  visit(18, 'Cardiology routine follow-up', 'Normal',
    'No major palpitation episodes lately. Home BP readings mostly under control.',
    ['Persistent fatigue'],
    ['Reports stable symptom control; good adherence to medicines.'],
    ['BP 128/80 mmHg, HR 72/min.'],
    ['Atrial fibrillation and hypertension stable on current therapy.'],
    ['Continue current medicines unchanged.', 'Routine review in 3 months.'],
    medicines=[rx('metoprolol', '90 days', 'Morning', 90), rx('clopidogrel', '90 days', 'After breakfast', 90),
               rx('telmisartan', '90 days', 'Morning', 90)]),
]),

# 10b. Gastroenterology - Meena Iyer - acid reflux (separate, unlinked series).
dict(patient=10, doctor_code='GAST-02', visits=[
  visit(170, 'Gastroenterology - persistent acid reflux', 'Normal',
    'Burning sensation behind my chest after meals and when lying down at night, for about a month. '
    'Occasional sour taste in the mouth.',
    ['Heartburn after meals', 'Acid regurgitation'],
    ['60-year-old female with 1-month history of postprandial and nocturnal heartburn with regurgitation.'],
    ['Abdomen soft, non-tender; no alarm features.'],
    ['Clinical picture consistent with GERD; given age, endoscopy recommended to exclude other pathology.'],
    ['Order upper GI endoscopy.', 'Start omeprazole.', 'Advise head-end elevation at night, avoid late meals; review in 4 weeks.'],
    medicines=[rx('omeprazole', '28 days', 'Before breakfast, empty stomach', 28)]),
  visit(142, 'Gastroenterology follow-up - endoscopy review', 'Normal',
    'Symptoms have improved with the medicine. Had the endoscopy done last week.',
    ['Heartburn after meals'],
    ['Reports good symptomatic improvement; reviewing endoscopy findings.'],
    ['Upper GI endoscopy: small hiatus hernia, mild reflux oesophagitis (LA Grade A), no malignancy.'],
    ['GERD with small hiatus hernia, mild erosive oesophagitis.'],
    ['Continue omeprazole.', 'Reinforce lifestyle measures; review in 8 weeks.'],
    medicines=[rx('omeprazole', '56 days', 'Before breakfast, empty stomach', 56)],
    reports=[report('GASTROENTEROLOGY', 'Upper GI Endoscopy',
                     impression='Small hiatus hernia, mild reflux oesophagitis (LA Grade A), no malignancy.')]),
  visit(30, 'Gastroenterology routine follow-up', 'Normal',
    'Doing well, very occasional mild heartburn only if I eat late. Otherwise comfortable.',
    ['Heartburn after meals'],
    ['Reports well-controlled symptoms with occasional minor breakthrough.'],
    ['Abdomen soft, non-tender.'],
    ['GERD with hiatus hernia, well controlled on maintenance therapy.'],
    ['Continue omeprazole at maintenance dose.', 'Routine review in 3 months.'],
    medicines=[rx('omeprazole', '90 days', 'Before breakfast, empty stomach', 90)]),
]),
]

SPECIALTY_OF_DOCTOR = {
    'CARD-01': 'CARD', 'CARD-02': 'CARD', 'CARD-03': 'CARD',
    'ORTH-01': 'ORTH', 'ORTH-02': 'ORTH', 'ORTH-05': 'ORTH',
    'DERM-01': 'DERM', 'DERM-02': 'DERM', 'DERM-04': 'DERM',
    'GAST-01': 'GAST', 'GAST-02': 'GAST', 'GAST-03': 'GAST',
}


def soap_hash(soap: dict) -> str:
    return hashlib.sha256(json.dumps(soap, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_plan(now):
    """Resolve every track into concrete rows + storage objects. No DB/storage calls."""
    doctors_seen = set(t['doctor_code'] for t in TRACKS)
    plan = dict(patients=list(PATIENTS.values()), slots=[], appointments=[],
                prescriptions=[], items=[], reports=[], storage={}, doctors=doctors_seen)
    for track in TRACKS:
        patient = PATIENTS[track['patient']]
        previous_id = None
        for v in track['visits']:
            starts_at = now - timedelta(days=v['days_ago'])
            ends_at = starts_at + timedelta(minutes=30)
            created_at = starts_at - timedelta(days=1)
            appointment_id = uid(f"visit/{track['patient']}/{track['doctor_code']}/{v['days_ago']}")
            slot_id = uid(f"slot/{track['patient']}/{track['doctor_code']}/{v['days_ago']}")
            prefix = f'demo_seed/v1/{appointment_id}'
            transcript_key = f'{prefix}/transcript.json'
            soap_draft_key = f'{prefix}/soap.json'
            finalised_record_key = f'{prefix}/signed.json'
            plan['storage'][transcript_key] = []
            plan['storage'][soap_draft_key] = {'soap': v['soap'], 'suggestions': []}
            # finalised_record_key content is filled in during apply(), once the
            # doctor's resolved id/name are known (see main()).
            plan['slots'].append(dict(id=slot_id, doctor_code=track['doctor_code'],
                                       starts_at=starts_at, ends_at=ends_at))
            appt = dict(id=appointment_id, slot_id=slot_id, patient_id=patient['id'], status='COMPLETED',
                        idempotency_key=f'demo-seed-v1/{appointment_id}', reason=v['reason'], severity=v['severity'],
                        symptoms=[{'label': s} for s in v['symptoms']], symptom_text=v['symptom_text'],
                        specialty_code=SPECIALTY_OF_DOCTOR[track['doctor_code']], consent_recorded=True,
                        created_at=created_at, started_at=starts_at, completed_at=ends_at,
                        linked_appointment_id=previous_id, transcript_key=transcript_key,
                        soap_draft_key=soap_draft_key, finalised_record_key=finalised_record_key,
                        doctor_code=track['doctor_code'], soap=v['soap'])
            plan['appointments'].append(appt)
            plan['prescriptions'].append(dict(appointment_id=appointment_id, doctor_code=track['doctor_code'],
                                               soap_revision=soap_hash(v['soap']), soap_draft_key=soap_draft_key,
                                               reviewed_at=ends_at))
            for pos, m in enumerate(v['medicines']):
                plan['items'].append(dict(appointment_id=appointment_id, position=pos, **m))
            for ri, r in enumerate(v['reports'], 1):
                report_id = uid(f'report/{appointment_id}/{ri}')
                report_key = f'{prefix}/report-{ri}.pdf'
                legacy_json_key = f'{prefix}/report-{ri}.json'  # superseded findings-only object; cleaned up in apply()
                findings_payload = r['findings'] | {'title': r['title'], 'report_type': r['report_type']}
                plan['reports'].append(dict(id=report_id, appointment_id=appointment_id, report_type=r['report_type'],
                                             title=r['title'], findings=findings_payload, object_key=report_key,
                                             legacy_json_key=legacy_json_key, reported_at=ends_at,
                                             patient_number=track['patient'], doctor_code=track['doctor_code']))
            previous_id = appointment_id
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Write to the database and storage; otherwise dry run.')
    parser.add_argument('--with-auth', action='store_true',
                         help='Also provision Supabase Auth logins (requires DEMO_PATIENT_PASSWORD).')
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    plan = build_plan(now)
    n_patients, n_visits = len(plan['patients']), len(plan['appointments'])
    n_meds = len(plan['items'])
    n_reports = len(plan['reports'])
    print(f'Plan: {n_patients} patients, {n_visits} linked/standalone visits across '
          f"{len(plan['doctors'])} doctors, {n_meds} prescribed medicine lines, {n_reports} reports, "
          f"{len(plan['storage'])} storage objects.")
    series_lengths = {}
    for t in TRACKS:
        series_lengths.setdefault(t['patient'], []).append(len(t['visits']))
    for patient_number, lengths in series_lengths.items():
        print(f"  Patient {patient_number} ({PATIENTS[patient_number]['full_name']}): series length(s) {lengths}")

    if not args.apply:
        print('Dry run only. Re-run with --apply to write to the database and storage.')
        return

    from app import storage
    from app.patient.service import _require_admin
    db = _require_admin()

    doctor_rows = db.table('doctors').select('id,doctor_code,full_name,specialty_id').in_(
        'doctor_code', sorted(plan['doctors'])).execute().data
    doctors = {d['doctor_code']: d for d in doctor_rows}
    missing = sorted(plan['doctors'] - doctors.keys())
    if missing:
        raise SystemExit(f'Missing expected synthetic doctors: {missing}. Apply phase_1_3.sql first.')
    specialty_rows = db.table('specialties').select('id,code').execute().data
    specialty_by_code = {s['code']: s['id'] for s in specialty_rows}

    brand_ids = sorted({m['brand_id'] for m in plan['items']})
    brand_rows = db.table('pharmacy_brands').select('brand_id,medicine_id,brand,variant,manufacturer').in_(
        'brand_id', brand_ids).execute().data
    brands = {b['brand_id']: b for b in brand_rows}
    missing_brands = sorted(set(brand_ids) - brands.keys())
    if missing_brands:
        raise SystemExit(f'Missing expected pharmacy brands: {missing_brands}. Apply Phase 4.1 catalogue first.')

    for p in plan['patients']:
        row = dict(id=p['id'], full_name=p['full_name'], phone=p['phone'], email=p['email'],
                   date_of_birth=p['dob'], age=(now.date() - datetime.strptime(p['dob'], '%Y-%m-%d').date()).days // 365,
                   gender=p['gender'], city=p['city'], role='patient')
        db.table('patients').upsert(row, on_conflict='id').execute()
    print(f"Upserted {len(plan['patients'])} patients.")

    for s in plan['slots']:
        doctor = doctors[s['doctor_code']]
        db.table('slots').upsert(dict(id=s['id'], doctor_id=doctor['id'], starts_at=s['starts_at'].isoformat(),
                                       ends_at=s['ends_at'].isoformat(), status='BOOKED'), on_conflict='id').execute()
    print(f"Upserted {len(plan['slots'])} slots.")

    for a in plan['appointments']:
        doctor = doctors[a['doctor_code']]
        plan['storage'][a['finalised_record_key']] = {
            'soap': a['soap'], 'signature': None, 'signed_by': doctor['id'],
            'doctor_name': doctor['full_name'], 'signed_at': a['completed_at'].isoformat(),
            'segments': [], 'is_synthetic': True,
            'signature_note': 'Synthetic seed data for development/testing; no real signature.',
        }
        row = dict(id=a['id'], slot_id=a['slot_id'], patient_id=a['patient_id'], status=a['status'],
                   idempotency_key=a['idempotency_key'], reason=a['reason'], severity=a['severity'],
                   symptoms=a['symptoms'], symptom_text=a['symptom_text'],
                   specialty_id=specialty_by_code[a['specialty_code']], consent_recorded=a['consent_recorded'],
                   created_at=a['created_at'].isoformat(), started_at=a['started_at'].isoformat(),
                   completed_at=a['completed_at'].isoformat(), linked_appointment_id=a['linked_appointment_id'],
                   transcript_key=a['transcript_key'], soap_draft_key=a['soap_draft_key'],
                   finalised_record_key=a['finalised_record_key'])
        db.table('appointments').upsert(row, on_conflict='id').execute()
    print(f"Upserted {len(plan['appointments'])} appointments.")

    for pr in plan['prescriptions']:
        doctor = doctors[pr['doctor_code']]
        db.table('consultation_prescriptions').upsert(dict(
            appointment_id=pr['appointment_id'], doctor_id=doctor['id'], active=False,
            soap_revision=pr['soap_revision'], soap_draft_key=pr['soap_draft_key'],
            reviewed_at=pr['reviewed_at'].isoformat(), updated_at=pr['reviewed_at'].isoformat(),
        ), on_conflict='appointment_id').execute()
    print(f"Upserted {len(plan['prescriptions'])} prescription review rows.")

    db.table('consultation_prescription_items').delete().in_(
        'appointment_id', [a['id'] for a in plan['appointments']]).execute()
    for item in plan['items']:
        b = brands[item['brand_id']]
        db.table('consultation_prescription_items').insert(dict(
            appointment_id=item['appointment_id'], brand_id=b['brand_id'], medicine_id=b['medicine_id'],
            position=item['position'], quantity=item['quantity'], strength_form=item['strength_form'],
            dose=item['dose'], frequency=item['frequency'], duration=item['duration'],
            instructions=item['instructions'],
            details=dict(brand=b['brand'], variant=b['variant'], manufacturer=b['manufacturer'], is_synthetic=True),
        )).execute()
    print(f"Inserted {len(plan['items'])} prescription medicine lines.")

    for r in plan['reports']:
        doctor = doctors[r['doctor_code']]
        patient = PATIENTS[r['patient_number']]
        pdf_bytes = report_pdf(patient['full_name'], doctor['full_name'],
                                r['reported_at'].date().isoformat(), r)
        storage.put_bytes(r['object_key'], pdf_bytes, 'application/pdf')
        storage.delete(r['legacy_json_key'])  # best-effort cleanup of the earlier findings-only object
        db.table('consultation_reports').upsert(dict(
            id=r['id'], appointment_id=r['appointment_id'], report_type=r['report_type'], title=r['title'],
            findings=r['findings'], object_key=r['object_key'], reported_at=r['reported_at'].isoformat(),
            is_synthetic=True, content_type='application/pdf', size_bytes=len(pdf_bytes),
        ), on_conflict='id').execute()
    print(f"Upserted {len(plan['reports'])} report rows with generated PDF report files.")

    for key, payload in plan['storage'].items():
        storage.put_json(key, payload)
    print(f"Wrote {len(plan['storage'])} JSON objects to {storage.backend_name()} storage.")

    if args.with_auth:
        password = os.environ.get('DEMO_PATIENT_PASSWORD', '')
        if len(password) < 12:
            raise SystemExit('Set DEMO_PATIENT_PASSWORD (>=12 chars) to provision Auth logins.')
        for p in plan['patients']:
            row = db.table('patients').select('auth_user_id').eq('id', p['id']).single().execute().data
            if row['auth_user_id']:
                print(f"Auth already linked: {p['full_name']} / {p['phone']}")
                continue
            user = None
            page = 1
            while True:
                users = db.auth.admin.list_users(page=page, per_page=100)
                user = next((u for u in users if u.email == p['email']), None)
                if user or len(users) < 100:
                    break
                page += 1
            if user is None:
                user = db.auth.admin.create_user({
                    'email': p['email'], 'password': password, 'email_confirm': True, 'phone': p['phone'],
                    'user_metadata': {'full_name': p['full_name'], 'role': 'patient', 'demo_seed': 'v1'},
                }).user
            db.table('patients').update({'auth_user_id': str(user.id)}).eq('id', p['id']).execute()
            print(f"Auth ready: {p['full_name']} / {p['phone']}")

    print('Done. Patients can sign in with their phone number; use --with-auth once to enable login.')


if __name__ == '__main__':
    main()
