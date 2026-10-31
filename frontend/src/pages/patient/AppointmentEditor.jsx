import { useEffect, useState } from "react";
import { fetchSymptoms, updateAppointmentDetails } from "../../api.js";
import SymptomMultiSelect from "../../components/SymptomMultiSelect.jsx";
import "./BookAppointment.css";

export default function AppointmentEditor({ appointment, patientId, accessToken, onSaved, onCancel }) {
  const [catalogue, setCatalogue] = useState(null);
  const [symptoms, setSymptoms] = useState((appointment.symptoms || []).filter(s => typeof s === "object").map(s => ({ symptom_id: s.id || s.symptom_id, severity: ["mild", "moderate", "severe"].includes(s.severity) ? s.severity : "", duration_days: typeof s.duration_days === "number" ? s.duration_days : "" })));
  const [symptom_text, setSymptomText] = useState(appointment.symptom_text || "");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { let active = true; fetchSymptoms().then(data => { if (active) setCatalogue(data.symptoms); }).catch(err => { if (active) setError(err.message); }); return () => { active = false; }; }, []);
  const remove = id => setSymptoms(current => current.filter(s => s.symptom_id !== id));
  function update(id, key, value) { setSymptoms(current => current.map(s => s.symptom_id === id ? { ...s, [key]: value } : s)); }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      await updateAppointmentDetails(patientId, appointment.id, accessToken, { symptoms: symptoms.map(s => ({ ...s, severity: s.severity || null, duration_days: s.duration_days === "" ? null : Number(s.duration_days) })), symptom_text });
      onSaved();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <form className="ba" onSubmit={save} aria-label="Edit appointment symptoms">
    <h2>Edit symptoms and notes</h2>
    <p className="detail__muted">These details update your existing appointment. To request a different doctor or slot, book a new appointment.</p>
    {error && <p role="alert">{error}</p>}
    {catalogue ? <>
      <SymptomMultiSelect options={catalogue} selectedIds={symptoms.map(s => s.symptom_id)} onRemove={remove} onAdd={id => setSymptoms(current => [...current, { symptom_id: id, severity: "", duration_days: "" }])} />
      {symptoms.map(s => <fieldset className="ba__detail" key={s.symptom_id}>
        <legend>{catalogue.find(c => c.id === s.symptom_id)?.label || s.symptom_id}</legend>
        <p>Catalogue severity: {catalogue.find(c => c.id === s.symptom_id)?.severity}</p>
        <label className="ba__detail-field">Duration (days)<input type="number" min="0" max="3650" value={s.duration_days} onChange={e => update(s.symptom_id, "duration_days", e.target.value)} /></label>
        <button type="button" className="ba__remove" onClick={() => remove(s.symptom_id)}>Remove</button>
      </fieldset>)}
      <label className="ba__row">Your note<textarea className="ba__textarea" maxLength={4000} rows={4} value={symptom_text} onChange={e => setSymptomText(e.target.value)} /></label>
    </> : !error && <p role="status">Loading symptoms...</p>}
    <div className="detail__actions"><button className="btn btn--primary" disabled={busy || !catalogue}>{busy ? "Saving..." : "Save changes"}</button><button className="btn btn--secondary" type="button" disabled={busy} onClick={onCancel}>Cancel</button></div>
  </form>;
}
