import { useEffect, useRef, useState } from "react";
import { usePatientAuth } from "../../auth/PatientAuth.jsx";
import { fetchPatientProfile, savePatientProfile } from "../../api.js";
import "./PatientProfile.css";

export default function PatientProfile({ onClose }) {
  const { patient, accessToken, updateProfile } = usePatientAuth();
  const dialog = useRef(null);
  const [profile, setProfile] = useState(null);
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const previousFocus = document.activeElement;
    const modal = dialog.current;
    modal.showModal();
    let active = true;
    fetchPatientProfile(patient.id, accessToken).then(data => {
      if (!active) return;
      setProfile(data); setName(data.full_name || ""); setCity(data.city || "");
    }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; modal.close(); previousFocus?.focus(); };
  }, [patient.id, accessToken]);

  async function save(event) {
    event.preventDefault(); setSaving(true); setError("");
    try {
      const updated = await savePatientProfile(patient.id, accessToken, { full_name: name.trim(), city });
      updateProfile(updated);
      // A location change invalidates doctor suggestions cached by the intake page.
      if (updated.city !== profile.city) {
        window.dispatchEvent(new Event("patient-location-changed"));
      }
      onClose();
    } catch (err) { setError(err.message); }
    finally { setSaving(false); }
  }
  return <dialog className="patient-profile" ref={dialog} aria-labelledby="profile-title" onCancel={event => { event.preventDefault(); if (!saving) onClose(); }}>
    <div className="patient-profile__heading"><h2 id="profile-title">Your profile</h2><button type="button" onClick={onClose} disabled={saving} aria-label="Close profile">×</button></div>
    {error && <p role="alert">{error}</p>}
    {!profile && !error && <p role="status">Loading profile…</p>}
    {profile && <form onSubmit={save}>
      <label>Full name<input autoFocus required maxLength={120} value={name} onChange={event => setName(event.target.value)} disabled={saving} /></label>
      <label>Location<select required value={city} onChange={event => setCity(event.target.value)} disabled={saving}><option value="" disabled>Select location</option><option>Pune</option><option>Hyderabad</option></select></label>
      <dl>{[["Phone", profile.phone], ["Email", profile.email], ["Age", profile.age], ["Gender", profile.gender], ["Role", profile.role], ["Patient ID", profile.id]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? "Not provided"}</dd></div>)}</dl>
      <p className="patient-profile__hint">Contact the care team to change other details.</p>
      <button type="submit" disabled={saving || !name.trim()}>{saving ? "Saving…" : "Save changes"}</button>
    </form>}
  </dialog>;
}
