import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import AppointmentEditor from "./AppointmentEditor.jsx";
import PrescriptionList from '../../components/PrescriptionList.jsx';
import { fetchAppointmentDetail } from "../../api.js";
import { usePatientAuth } from "../../auth/PatientAuth.jsx";
import { formatWhen, StatusPill } from "./MyAppointments.jsx";
import "./MyAppointments.css";

function Notes({ items, empty }) {
  return Array.isArray(items) && items.length ? <ul>{items.map((text, index) => <li key={index}>{text}</li>)}</ul> : <p className="detail__muted">{empty}</p>;
}
export default function AppointmentDetail() {
  const { appointmentId } = useParams();
  const [params, setParams] = useSearchParams();
  const [saved, setSaved] = useState(false);
  const { patient, accessToken } = usePatientAuth();
  const [appointment, setAppointment] = useState(null);
  const [error, setError] = useState(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setAppointment(null); setError(null);
    fetchAppointmentDetail(patient.id, appointmentId, accessToken)
      .then(data => { if (active) setAppointment(data); })
      .catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [patient.id, appointmentId, accessToken, retry]);
  function downloadSummary() {
    const a = appointment;
    const text = ["Sahayog Care - Consultation summary", formatWhen(a.starts_at), a.doctor_name,
      ...Object.entries(a.soap || {}).flatMap(([key, values]) => ["", key.toUpperCase(), ...(Array.isArray(values) ? values : [])]),
      '', 'PRESCRIBED MEDICINES', ...(a.prescription || []).map(item => `${item.brand} - ${item.strength_form}: ${item.dose}, ${item.frequency}, ${item.duration}. Quantity: ${item.quantity ?? 'Not recorded'}. ${item.instructions || ''}`),
      "", `Signed by ${a.signed_by || a.doctor_name} on ${formatWhen(a.signed_at)}`].join("\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `consultation-${a.id}.txt`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const a = appointment;
  return <section className="detail">
    <Link className="detail__back" to="/patient/my-appointments">&larr; My appointments</Link>
    <h1 className="detail__heading">Appointment details</h1>
    {saved && <p role="status">Appointment details saved.</p>}
    {error ? <div role="alert"><p>{error}</p><button className="btn btn--secondary" onClick={() => setRetry(retry + 1)}>Try again</button></div> : !a ? <p role="status">Loading appointment details...</p> : <>
      <div className="detail__overview">
        <dl><dt>Date</dt><dd>{formatWhen(a.starts_at)}</dd></dl>
        <dl><dt>Doctor</dt><dd>{a.doctor_name || "To be assigned"}</dd></dl>
        <dl><dt>Reason</dt><dd>{a.reason || "Not provided"}</dd></dl>
        <StatusPill status={a.status} />
      </div>
      <div className="detail__grid">
        <section className="detail__card"><h2>Symptoms</h2><div className="detail__body">
          {a.status === "BOOKED" && params.get("edit") === "1" ? <AppointmentEditor appointment={a} patientId={patient.id} accessToken={accessToken} onCancel={() => setParams({})} onSaved={() => { setSaved(true); setParams({}); setRetry(retry + 1); }} /> : <>
          {a.symptoms?.length ? <ul className="detail__symptoms">{a.symptoms.map((s, i) => <li key={i}>
            <strong>{typeof s === "string" ? s : s.label || s.id}</strong>
            {typeof s === "object" && <><span className={`pill pill--${s.severity === "severe" ? "danger" : s.severity === "moderate" ? "warning" : "neutral"}`}>{s.severity || "Not recorded"}</span><span>{typeof s.duration_days === "number" ? `${s.duration_days} day(s)` : "Duration not recorded"}</span></>}
          </li>)}</ul> : <p className="detail__muted">No symptoms recorded.</p>}
          {a.symptom_text && <p><strong>Your note:</strong> {a.symptom_text}</p>}
          {a.status === "BOOKED" && <button className="btn btn--secondary" onClick={() => { setSaved(false); setParams({ edit: "1" }); }}>Edit details</button>}
          </>}
        </div></section>
        <section className="detail__card"><h2>Medicines</h2><div className="detail__body">{a.signed_at ? <PrescriptionList items={a.prescription} /> : <p className="detail__muted">Prescribed medicines will appear after the doctor signs the consultation.</p>}</div></section>
        <section className="detail__card"><h2>Consultation</h2><div className="detail__body">
          <strong>What the doctor found</strong><Notes items={a.soap?.objective} empty="Consultation notes will appear after the doctor signs the summary." />
          {a.soap && <><strong>Care plan</strong><Notes items={a.soap.plan} empty="No plan recorded." /></>}
          {a.signed_at && <p className="detail__muted">Signed by {a.signed_by || a.doctor_name} on {formatWhen(a.signed_at)}</p>}
        </div></section>
        <section className="detail__card"><h2>Summary</h2><div className="detail__body">
          <Notes items={a.soap?.assessment} empty="Your signed summary is not available yet." />
          <div className="detail__actions">{a.soap && <button className="btn btn--secondary" onClick={downloadSummary}>Download summary</button>}
          <Link className="btn btn--primary" to="/patient/book-appointment">Book follow-up</Link></div>
        </div></section>
      </div>
    </>}
  </section>;
}
