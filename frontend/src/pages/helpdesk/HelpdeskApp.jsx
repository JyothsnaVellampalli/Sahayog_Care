import { useEffect, useState } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { helpdeskGet, helpdeskIdentify } from '../../api.js';
import Reports from '../../components/Reports.jsx';
import PrescriptionList from '../../components/PrescriptionList.jsx';
import '../patient/PatientLogin.css';
import '../doctor/DoctorPortal.css';
import '../doctor/ConsultationsList.css';
import '../doctor/ConsultationView.css';
import './Helpdesk.css';

const SESSION = 'sahayog.helpdesk.session';
function loadSession() { try { return JSON.parse(localStorage.getItem(SESSION) || 'null'); } catch { return null; } }
function localDate() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function initials(name) {
  if (!name) return 'HD';
  const parts = name.trim().split(/\s+/);
  return (parts[0]?.[0] || 'H').concat(parts[1]?.[0] || '').toUpperCase();
}

export default function HelpdeskApp() {
  const [staff, setStaff] = useState(loadSession);
  const navigate = useNavigate();
  function signOut() { localStorage.removeItem(SESSION); setStaff(null); navigate('/helpdesk/login'); }
  if (!staff) return <Routes>
    <Route path="login" element={<Login onLogin={profile => { localStorage.setItem(SESSION, JSON.stringify(profile)); setStaff(profile); navigate('/helpdesk/consultations'); }} />} />
    <Route path="*" element={<Navigate to="/helpdesk/login" replace />} />
  </Routes>;
  return <div className="dportal">
    <a className="skip-link" href="#helpdesk-content">Skip to content</a>
    <header className="dportal__header">
      <div className="dportal__left">
        <button className="dportal__brand" type="button" onClick={() => navigate('/')} aria-label="Sahayog Care home">
          <span className="dportal__brand-mark" aria-hidden="true" />
          Sahayog Care
        </button>
        <nav className="dportal__nav" aria-label="Helpdesk portal sections">
          <NavLink to="/helpdesk/consultations" className={({ isActive }) => `dportal__navitem${isActive ? ' dportal__navitem--active' : ''}`}>Consultations</NavLink>
        </nav>
      </div>
      <div className="dportal__profile">
        <span className="dportal__name">{staff.full_name || 'Helpdesk'}</span>
        <span className="dportal__avatar" aria-hidden="true">{initials(staff.full_name)}</span>
        <button className="dportal__signout" type="button" onClick={signOut}>Sign out</button>
      </div>
    </header>
    <main className="dportal__content" id="helpdesk-content" tabIndex="-1"><Routes>
      <Route path="login" element={<Navigate to="/helpdesk/consultations" replace />} />
      <Route path="consultations" element={<Consultations staff={staff} />} />
      <Route path="consultations/:consultationId" element={<ReadConsultation staff={staff} />} />
      <Route path="*" element={<Navigate to="/helpdesk/consultations" replace />} />
    </Routes></main></div>;
}

function Login({ onLogin }) {
  const [phone, setPhone] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function submit(e) { e.preventDefault(); setBusy(true); setError('');
    try { onLogin((await helpdeskIdentify(phone.trim())).profile); } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <main className="login" id="main-content">
    <Link className="login__brand" to="/">Sahayog Care</Link>
    <section className="login__card" aria-labelledby="helpdesk-login-title">
      <h1 className="login__title" id="helpdesk-login-title">Helpdesk sign in</h1>
      <form className="login__form" onSubmit={submit}>
        <p className="login__intro">Enter your registered phone number to continue.</p>
        <label className="login__field">
          <span>Phone number</span>
          <input required type="tel" autoComplete="tel" placeholder="+91XXXXXXXXXX" value={phone} onChange={e => setPhone(e.target.value)} />
        </label>
        <button className="login__submit" type="submit" disabled={busy}>{busy ? 'Please wait…' : 'Continue'}</button>
      </form>
      {error && <p className="login__error" role="alert">{error}</p>}
    </section>
  </main>;
}

function Consultations({ staff }) {
  const [filters, setFilters] = useState({ doctors: [], specialties: [] });
  const [day, setDay] = useState(localDate); const [from, setFrom] = useState('00:00'); const [to, setTo] = useState('23:59');
  const [doctor, setDoctor] = useState(''); const [specialty, setSpecialty] = useState('');
  const [page, setPage] = useState(0); const [data, setData] = useState(null); const [error, setError] = useState(''); const [retry, setRetry] = useState(0);
  useEffect(() => { let active = true; helpdeskGet(staff.id, 'filters').then(value => { if (active) setFilters(value); }).catch(err => { if (active) setError(err.message); }); return () => { active = false; }; }, [staff.id, retry]);
  useEffect(() => {
    let active = true; setData(null); setError('');
    if (!day || !from || !to || from > to) { setError('Choose a valid day and time range.'); return; }
    helpdeskGet(staff.id, 'consultations', { date_from: new Date(`${day}T${from}:00`).toISOString(), date_to: new Date(`${day}T${to}:59.999`).toISOString(), doctor_id: doctor, specialty_id: specialty, page })
      .then(value => { if (active) setData(value); }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [staff.id, day, from, to, doctor, specialty, page, retry]);
  function change(setter, value) { setter(value); setPage(0); }
  return <section className="clist"><h1>Consultations</h1><p>All patients and doctors. Open a consultation to view its records.</p>
    <div className="helpdesk-filters">
      <div><label htmlFor="helpdesk-doctor">Doctor</label><select id="helpdesk-doctor" value={doctor} onChange={e => change(setDoctor, e.target.value)}><option value="">All doctors</option>{filters.doctors.map(d => <option key={d.id} value={d.id}>{d.full_name}</option>)}</select></div>
      <div><label htmlFor="helpdesk-specialty">Specialty</label><select id="helpdesk-specialty" value={specialty} onChange={e => change(setSpecialty, e.target.value)}><option value="">All specialties</option>{filters.specialties.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></div>
      <label>Day<input type="date" value={day} onChange={e => change(setDay, e.target.value)} /></label>
      <label>From time<input type="time" value={from} onChange={e => change(setFrom, e.target.value)} /></label>
      <label>To time<input type="time" value={to} onChange={e => change(setTo, e.target.value)} /></label>
    </div>
    {error ? <div role="alert">{error} <button onClick={() => setRetry(retry+1)}>Retry</button></div> : !data ? <p role="status">Loading consultations...</p> : <>
      {!data.consultations.length && <p>No consultations in this range.</p>}
      <ul className="helpdesk-list">{data.consultations.map(c => <li key={c.id}><Link to={`/helpdesk/consultations/${c.id}`}>
        <strong>{c.patients?.full_name || 'Patient'}</strong><span>{new Date(c.slots?.starts_at).toLocaleString()}</span>
        <span>{c.slots?.doctors?.full_name} · {c.specialties?.name}</span><span>{c.reason}</span><span className="pill pill--neutral">{c.status.replaceAll('_', ' ')}</span>
      </Link></li>)}</ul>
      <div className="record-tools"><button className="btn btn--secondary" disabled={page === 0} onClick={() => setPage(page-1)}>Previous page</button><span>Page {page+1} · {data.count} consultations</span><button className="btn btn--secondary" disabled={(page+1)*50 >= data.count} onClick={() => setPage(page+1)}>Next page</button></div>
    </>}
  </section>;
}

function ReadConsultation({ staff }) {
  const { consultationId } = useParams(); const [data, setData] = useState(null); const [error, setError] = useState(''); const [retry, setRetry] = useState(0);
  useEffect(() => { let active = true; setData(null); setError('');
    helpdeskGet(staff.id, `consultations/${consultationId}`).then(value => { if (active) setData(value); }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [staff.id, consultationId, retry]);
  return <section className="cview"><Link className="cview__back" to="/helpdesk/consultations">← Consultations</Link>
    {error ? <div role="alert">{error} <button onClick={() => setRetry(retry+1)}>Retry</button></div> : !data ? <p role="status">Loading consultation...</p> : <>
      <div className="cview__patient"><div className="helpdesk-overview"><h1>{data.patient_name}</h1><span>{new Date(data.starts_at).toLocaleString()}</span><span className="pill pill--neutral">{data.status}</span></div>
        <div className="cview__details"><div><strong>Symptoms</strong><p>{data.symptoms?.join(', ') || 'No symptoms recorded.'}</p></div><div><strong>Patient symptom description</strong><p>{data.symptom_text || 'No description recorded.'}</p></div></div>
      </div>
      <div className="record-tools">{data.linked_appointment_id && <Link to={`/helpdesk/consultations/${data.linked_appointment_id}`} target="_blank" rel="noopener noreferrer">Previous related consultation ↗</Link>}
        <Reports appointmentId={consultationId} helpdeskId={staff.id} canUpload /></div>
      <div className="cview__soap"><div className="cview__soap-head"><h2 className="cview__transcript-title">SOAP summary</h2><span className="pill pill--neutral">{data.signed_at ? 'Signed' : 'Unsigned draft'}</span></div>
        {data.soap ? <div className="cview__soap-sections">{['subjective','objective','assessment','plan'].map(key => <section key={key}><h3>{key[0].toUpperCase() + key.slice(1)}</h3>{data.soap[key]?.length ? <ul>{data.soap[key].map((text,i) => <li key={i}>{text}</li>)}</ul> : <p>Not documented.</p>}</section>)}</div> : <p>No summary recorded yet.</p>}
      </div>
      <div className="cview__soap"><h2>Medicines</h2><PrescriptionList items={data.prescription || []} /></div>
      {data.signed_at && <div className="cview__signature">{data.signature && <img src={data.signature} alt={`Signature of ${data.doctor_name}`} />}<p>Signed by {data.doctor_name} · {new Date(data.signed_at).toLocaleString()}</p></div>}
    </>}
  </section>;
}
