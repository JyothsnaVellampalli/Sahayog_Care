"""Build v2 linked history, SQL and printable reports offline. No service calls."""
import hashlib
import json
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'database/demo_patient_history'


def uid(value, version=2):
    return str(uuid5(NAMESPACE_URL, f'sahayog/demo-history/v{version}/' + value))


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def report_pdf(patient, visit, report):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('DemoTitle', parent=styles['Title'], fontSize=21, leading=26, textColor=colors.HexColor('#125c58'), spaceAfter=15))
    styles.add(ParagraphStyle('DemoBody', parent=styles['BodyText'], fontSize=10.5, leading=16, spaceAfter=10))
    styles.add(ParagraphStyle('DemoLabel', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#125c58'), spaceBefore=15, spaceAfter=8))
    styles.add(ParagraphStyle('DemoBanner', parent=styles['BodyText'], fontSize=9, leading=13, alignment=TA_CENTER, textColor=colors.HexColor('#7c3829'), backColor=colors.HexColor('#fff2e7'), borderPadding=9))
    def paragraph(text, style='DemoBody'):
        return Paragraph(escape(text), styles[style])
    story = [paragraph('SAHAYOG CARE / DEMONSTRATION RECORD', 'DemoLabel'),
             paragraph(report['title'], 'DemoTitle'),
             paragraph('SYNTHETIC DATA - NOT A REAL PATIENT OR CLINICAL REPORT', 'DemoBanner'), Spacer(1, 20)]
    details = [('Patient', patient['full_name']), ('Date of birth', patient['date_of_birth']),
               ('Report date', report['date']), ('Appointment date', visit['date']),
               ('Doctor reference', visit['doctor']), ('Report type', report['type'].replace('_', ' '))]
    table = Table([[paragraph(label), paragraph(value)] for label, value in details], colWidths=[125, 365])
    table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f1f7f6')),
                              ('LEFTPADDING', (0,0), (-1,-1), 10), ('TOPPADDING',(0,0),(-1,-1),5)]))
    story += [table, paragraph('Clinical context', 'DemoLabel'), paragraph(visit['reason']), paragraph('Findings', 'DemoLabel')]
    story += [paragraph(f'{i}. {finding}') for i, finding in enumerate(report['findings'], 1)]
    story += [paragraph('Impression', 'DemoLabel'), paragraph(report['impression']),
              paragraph('Record notes', 'DemoLabel'), paragraph('Fictional historical document for application testing. No real laboratory, radiology image, surgeon attestation or doctor signature is supplied. Medication entries elsewhere in this dataset are fictional chart data, not treatment instructions.'),
              paragraph('Report ID: ' + report['id'])]
    def footer(canvas, doc):
        canvas.setFont('Helvetica', 8); canvas.setFillColor(colors.HexColor('#52665f'))
        canvas.drawString(48, 32, 'Sahayog Care | Synthetic history v2 | Not for clinical use')
        canvas.drawRightString(A4[0]-48, 32, f'Page {doc.page}')
    class StableCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            kwargs['invariant'] = 1
            super().__init__(*args, **kwargs)
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=48, rightMargin=48, topMargin=36, bottomMargin=48,
                            title=report['title'], author='Sahayog Care - Synthetic fixtures')
    doc.build(story, onFirstPage=footer, onLaterPages=footer, canvasmaker=StableCanvas)
    return output.getvalue()


def build_manifest():
    source = json.loads((OUT / 'cases.json').read_text(encoding='utf-8'))
    manifest = {'version': source['version'], 'as_of': source['as_of'], 'patients': [], 'visits': [], 'objects': {}, 'files': {}}
    for p in source['patients']:
        n = p['number']
        patient = {k: p[k] for k in ('full_name', 'date_of_birth', 'gender', 'city', 'scenario')}
        patient.update(id=uid(f'patient/{n}', 1), phone=f'+91970000000{n}', email=f'sahayog.demo.patient{n}@example.com', expected_visits=len(p['visits']))
        manifest['patients'].append(patient)
        previous = None
        for index, v in enumerate(p['visits'], 1):
            aid = uid(f'visit/{n}/{index}')
            prefix = f'demo_patient_history/v2/{aid}'
            start = datetime.fromisoformat(v['date'] + 'T10:00:00+05:30')
            end = (start + timedelta(minutes=30)).isoformat()
            medicines = [dict(source['medicines'][key]) for key in v['medicines']]
            soap = {'subjective': v['subjective'] + ([p['history']] if index == 1 else []),
                    'objective': v['objective'] + [f"{r['title']} ({r['date']}): {r['impression']}" for r in v['reports']],
                    'assessment': v['assessment'] + ['Synthetic demonstration record.'],
                    'plan': v['plan'] + [f"Recorded prescription: {m['name']} {m['strength_form']}; {m['dose']}; {m['frequency']}; {m['duration']}." for m in medicines]}
            visit = dict(id=aid, patient_id=patient['id'], slot_id=uid(f'slot/{n}/{index}'), linked_appointment_id=previous,
                         doctor_code=v['doctor'], reason=v['reason'], severity=v['severity'],
                         symptoms=[{'label': s} for s in v['symptoms']], symptom_text=v['subjective'][0],
                         created_at=(start-timedelta(days=1)).isoformat(), starts_at=start.isoformat(), completed_at=end,
                         transcript_key=prefix+'/transcript.json', soap_draft_key=prefix+'/soap.json', finalised_record_key=prefix+'/signed.json',
                         soap_revision=hashlib.sha256(json.dumps(soap, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                         medicines=medicines, reports=[])
            manifest['objects'][visit['transcript_key']] = {}
            manifest['objects'][visit['soap_draft_key']] = {'soap': soap, 'suggestions': []}
            manifest['objects'][visit['finalised_record_key']] = {'soap': soap, 'signed_at': end, 'doctor_code': v['doctor'],
                'signature': None, 'segments': [], 'is_synthetic': True, 'signature_note': 'Synthetic historical import; no real signature.'}
            for rindex, original in enumerate(v['reports'], 1):
                report = {**original, 'id': uid(f'report/{n}/{index}/{rindex}'), 'appointment_id': aid, 'is_synthetic': True}
                report['reported_at'] = original['date'] + 'T09:00:00+05:30'
                pdf = report_pdf(patient, v, report)
                filename = f'reports/patient-{n}-visit-{index}-report-{rindex}.pdf'
                path = OUT / filename; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(pdf)
                report.update(object_key=prefix+f'/report-{rindex}.pdf', content_type='application/pdf', size_bytes=len(pdf))
                manifest['files'][report['object_key']] = {'path': filename, 'content_type': 'application/pdf', 'size_bytes': len(pdf), 'sha256': hashlib.sha256(pdf).hexdigest()}
                manifest['objects'][prefix+f'/report-{rindex}.json'] = report
                visit['reports'].append(report)
            manifest['visits'].append(visit)
            previous = aid
    return manifest


def build_sql(manifest):
    # Stable v1 identities make replacement narrowly scoped and preserve patient logins.
    legacy = [{'id': uid(f'visit/{n}/{v}', 1), 'slot_id': uid(f'slot/{n}/{v}', 1), 'patient_id': uid(f'patient/{n}', 1),
               'reports': [uid(f'report/{n}/{v}/{r}', 1) for r in (1,2)]} for n in range(1,6) for v in (1,2)]
    payload = {k: manifest[k] for k in ('version', 'patients', 'visits')}
    template = (ROOT / 'scripts/patient_history_seed_template.sql').read_text(encoding='utf-8')
    return template.replace('__PAYLOAD__', literal(json.dumps(payload))).replace('__LEGACY__', literal(json.dumps(legacy)))


def build():
    manifest = build_manifest()
    (OUT/'storage_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    (OUT/'seed.sql').write_text(build_sql(manifest), encoding='utf-8')
    print(f"Built {len(manifest['patients'])} patients, {len(manifest['visits'])} linked/standalone visits, "
          f"{len(manifest['files'])} PDF reports and {len(manifest['objects'])} JSON objects.")


if __name__ == '__main__':
    build()
