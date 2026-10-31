import { useEffect, useState } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { pharmacyGet, pharmacyIdentify, pharmacyUpdateStock, pharmacyResolveReservation } from '../../api.js';
import '../patient/PatientLogin.css';
import '../doctor/DoctorPortal.css';
import './Pharmacy.css';
import PrescriptionList from '../../components/PrescriptionList.jsx';

const SESSION = 'sahayog.pharmacist.profile';
const title = value => value ? value[0].toUpperCase() + value.slice(1) : '';
const date = value => value ? new Date(value).toLocaleString('en-IN') : 'Not recorded';

function ReservationBadge({ data }) {
  const status = data.reservation_status || 'NONE';
  const label = data.can_unlock ? 'Overdue · stock still locked' : {
    LOCKED: 'Stock reserved', RELEASED: 'Stock unlocked', DISPENSED: 'Medicines collected', NONE: 'No stock reservation',
  }[status];
  return <span className={`pill pill--${data.can_unlock ? 'danger' : status === 'DISPENSED' ? 'success' : 'neutral'}`}>{label}</span>;
}

function useLoad(id, path, params = {}, revision = 0) {
  const [state, setState] = useState({ loading: true, data: null, error: '' });
  const query = JSON.stringify(params);
  useEffect(() => {
    let current = true;
    setState({ loading: true, data: null, error: '' });
    pharmacyGet(id, path, JSON.parse(query)).then(data => {
      if (current) setState({ loading: false, data, error: '' });
    }).catch(error => {
      if (current) setState({ loading: false, data: null, error: error.message });
    });
    return () => { current = false; };
  }, [id, path, query, revision]);
  return state;
}

function Feedback({ state }) {
  return state.loading ? <p role="status">Loading…</p> : state.error ? <p role="alert">{state.error}</p> : null;
}

function Pager({ offset, total, setOffset }) {
  return <div className="pharmacy__pager">
    <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button>
    <span>{total ? `${offset + 1}–${Math.min(offset + 50, total)} of ${total}` : '0 results'}</span>
    <button disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}>Next</button>
  </div>;
}

function Login({ onSignIn }) {
  const [phone, setPhone] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const { profile } = await pharmacyIdentify(phone.trim());
      onSignIn(profile); navigate('/pharmacist/stock', { replace: true });
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }
  return <main className="login" id="main-content">
    <Link className="login__brand" to="/">Sahayog Care</Link>
    <section className="login__card" aria-labelledby="pharmacist-login-title">
      <h1 className="login__title" id="pharmacist-login-title">Pharmacist sign in</h1>
      <form className="login__form" onSubmit={submit}>
        <p className="login__intro">Enter your registered phone number to continue.</p>
        <label className="login__field">Phone number<input type="tel" required autoComplete="tel" value={phone} onChange={e => setPhone(e.target.value)} /></label>
        <button className="login__submit" disabled={busy}>{busy ? 'Please wait…' : 'Continue'}</button>
      </form>
      {error && <p role="alert" className="login__error">{error}</p>}
    </section>
  </main>;
}

function StockEditor({ row, id, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [quantity, setQuantity] = useState(String(row.stock_quantity ?? ''));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function save(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await pharmacyUpdateStock(id, row.brand_id, Number(quantity));
      setEditing(false); onSaved();
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }
  if (!editing) return <button onClick={() => setEditing(true)} aria-label={`Update stock for ${row.brand}`}>Update stock</button>;
  return <form onSubmit={save} className="pharmacy__count">
    <input aria-label={`Count for ${row.brand}`} type="number" min={row.locked_quantity || 0} max="2147483647" step="1" required value={quantity} onChange={e => setQuantity(e.target.value)} />
    <button disabled={busy}>Save</button><button type="button" disabled={busy} onClick={() => setEditing(false)}>Cancel</button>
    {error && <p role="alert">{error}</p>}
  </form>;
}

function Stock({ id }) {
  const [filters, setFilters] = useState({ brand: '', specialty: '', composition: '', stock: '' });
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState('');
  const options = useLoad(id, 'filters', {}, revision);
  const state = useLoad(id, 'stock', { ...filters, offset }, revision);
  function filter(key, value) { setFilters(old => ({ ...old, [key]: value })); setOffset(0); }
  return <section aria-labelledby="stock-title">
    <div className="pharmacy__heading"><div><h1 id="stock-title">Medicine stock</h1><p>Browse brands, compositions and availability.</p></div>
      <button onClick={() => setRevision(v => v + 1)}>Refresh</button></div>
    <p className="pharmacy__note">Demo quantities are randomly seeded. Counts are per catalogue brand entry; verify the exact strength and pack before recording physical stock.</p>
    <div className="pharmacy__filters">
      {[['brand', 'Brand', 'brands'], ['specialty', 'Specialty', 'specialties'], ['composition', 'Composition', 'compositions']].map(([key, label, source]) =>
        <label key={key}>{label}<select value={filters[key]} onChange={e => filter(key, e.target.value)}>
          <option value="">All {source}</option>{(options.data?.[source] || []).map(value => <option key={value} value={value}>{title(value)}</option>)}
        </select></label>)}
      <label>Stock<select value={filters.stock} onChange={e => filter('stock', e.target.value)}>
        <option value="">All stock</option><option value="in_stock">In stock</option><option value="low_stock">Low stock (1–10)</option>
        <option value="out_of_stock">Out of stock</option><option value="unknown">Not counted</option>
      </select></label>
      <button onClick={() => { setFilters({ brand: '', specialty: '', composition: '', stock: '' }); setOffset(0); }}>Clear filters</button>
    </div>
    {options.error && <p role="alert">Could not load filters: {options.error}</p>}
    <p role="status">{notice}</p><Feedback state={state} />
    {state.data && <>
      {!state.data.items.length ? <p>No medicines match these filters.</p> : <div className="pharmacy__table" tabIndex="0" role="region" aria-label="Medicine stock table">
        <table><thead><tr><th scope="col">Brand / variant</th><th scope="col">Composition / specialty</th><th scope="col">Stock units</th><th scope="col">Action</th></tr></thead>
          <tbody>{state.data.items.map(row => <tr key={row.brand_id}>
            <td><strong>{row.brand}</strong><span>{row.variant}</span><span>{row.manufacturer || 'Manufacturer not supplied'}</span>
              {/* <small>Source: {row.source_status === 'web_confirmed' ? 'Previously web-confirmed; verify pack' : 'Unverified; verify pack'}</small> */}
            </td>
            <td>{row.pharmacy_medicines.composition}<span>{title(row.pharmacy_medicines.specialty)}</span></td>
            <td><strong>{row.available_quantity ?? row.stock_quantity ?? 'Not counted'} available</strong>
            <span>{row.locked_quantity || 0} reserved · {row.stock_quantity ?? 'Unknown'} total</span>
            {/* <span>{row.stock_is_demo ? 'Demo count' : 'Updated count'}</span> */}
            </td>
            <td><StockEditor row={row} id={id} onSaved={() => { setNotice(`Stock updated for ${row.brand}.`); setRevision(v => v + 1); }} /></td>
          </tr>)}</tbody></table>
      </div>}
      <Pager offset={offset} total={state.data.total} setOffset={setOffset} />
    </>}
  </section>;
}

function Consultations({ id }) {
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const state = useLoad(id, 'consultations', { offset }, revision);
  return <section aria-labelledby="signed-title">
    <div className="pharmacy__heading"><div><h1 id="signed-title">Signed consultations</h1><p>Completed consultations, newest first.</p></div><button onClick={() => setRevision(v => v + 1)}>Refresh</button></div>
    <Feedback state={state} />
    {state.data && <>{!state.data.items.length && <p>No signed consultations yet.</p>}
      <div className="pharmacy__visits">{state.data.items.map(row => <Link className="pharmacy__visit" key={row.id} to={`/pharmacist/consultations/${row.id}`}>
        <strong>{row.patients?.full_name || 'Patient'}</strong><span>{row.slots?.doctors?.full_name || 'Doctor'}</span>
        <ReservationBadge data={row} />
        <span>Signed {date(row.completed_at)}</span><span>View signed summary →</span>
      </Link>)}</div><Pager offset={offset} total={state.data.total} setOffset={setOffset} />
    </>}
  </section>;
}

function SignedDetail({ id }) {
  const { appointmentId } = useParams();
  const [revision, setRevision] = useState(0);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [actionNotice, setActionNotice] = useState('');
  const state = useLoad(id, `consultations/${encodeURIComponent(appointmentId)}`, {}, revision);
  async function resolve(action) {
    const message = action === 'release' ? 'Confirm the patient has not collected these medicines and unlock all reserved stock?' : 'Confirm the patient has collected all prescribed medicines? This deducts the reserved quantities from stock.';
    if (!window.confirm(message)) return;
    setActionBusy(true); setActionError(''); setActionNotice('');
    try {
      await pharmacyResolveReservation(id, appointmentId, action);
      setActionNotice(action === 'release' ? 'Reserved stock unlocked.' : 'Medicines marked collected. Stock updated.');
      setRevision(value => value + 1);
    } catch (error) { setActionError(error.message); }
    finally { setActionBusy(false); }
  }
  return <section>
    <Link to="/pharmacist/consultations">← Signed consultations</Link><h1>Signed consultation</h1>
    <Feedback state={state} /><button disabled={actionBusy || state.loading} onClick={() => setRevision(v => v + 1)}>Refresh consultation</button>
    {actionError && <p role="alert">{actionError}</p>}{actionNotice && <p role="status">{actionNotice}</p>}
    {state.data && <article className="pharmacy__summary"><h2>{state.data.patient_name || 'Patient'}</h2>
      <p>{state.data.doctor_name} · {date(state.data.signed_at)}</p>
      <div className="pharmacy__reservation">
        <ReservationBadge data={state.data} />
        {state.data.reservation_status === 'LOCKED' && <>
          <p>{state.data.can_unlock ? 'This consultation was signed at least 24 hours ago and its stock is still reserved. Confirm collection status before unlocking.' : `Stock can be unlocked after ${date(state.data.release_available_at)} if the patient has not collected the medicines.`}</p>
          <div className="pharmacy__reservation-actions">
            <button disabled={actionBusy} onClick={() => resolve('dispense')}>Mark collected</button>
            <button disabled={actionBusy || !state.data.can_unlock} onClick={() => resolve('release')}>Unlock stock</button>
          </div>
        </>}
      </div>
      {['subjective', 'objective', 'assessment', 'plan'].map(key => <section key={key}><h3>{title(key)}</h3>
        <ul>{(state.data.soap?.[key] || []).map((line, i) => <li key={i}>{line}</li>)}</ul>
        {!state.data.soap?.[key]?.length && <p>Not recorded.</p>}</section>)}
      <section><h3>Prescribed medicines</h3><PrescriptionList items={state.data.prescription} /></section>
      {state.data.signature && <img className="pharmacy__signature" src={state.data.signature} alt="Doctor signature" />}
      <p>Signed by {state.data.doctor_name || 'Doctor'}</p>
    </article>}
  </section>;
}

export default function PharmacyApp() {
  const navigate = useNavigate();
  const [profile, setProfile] = useState(() => {
    try { const saved = JSON.parse(sessionStorage.getItem(SESSION)); return saved?.id ? saved : null; } catch { return null; }
  });
  function signIn(next) {
    sessionStorage.setItem(SESSION, JSON.stringify(next)); setProfile(next);
  }
  if (!profile) return <Routes><Route path="login" element={<Login onSignIn={signIn} />} /><Route path="*" element={<Navigate to="/pharmacist/login" replace />} /></Routes>;
  return <div className="dportal pharmacy">
    <a className="skip-link" href="#pharmacy-content">Skip to content</a>
    <header className="dportal__header">
      <div className="dportal__left">
        <button className="dportal__brand" type="button" onClick={() => navigate('/')} aria-label="Sahayog Care home">
          <span className="dportal__brand-mark" aria-hidden="true" />
          Sahayog Care
        </button>
      <nav className="dportal__nav" aria-label="Pharmacist portal sections">
        {[['stock', 'Stock'], ['consultations', 'Signed consultations']].map(([path, label]) => <NavLink key={path} to={`/pharmacist/${path}`} className={({ isActive }) => `dportal__navitem${isActive ? ' dportal__navitem--active' : ''}`}>{label}</NavLink>)}
      </nav>
      </div>
      <div className="dportal__profile">
        <span className="dportal__name">{profile.full_name || 'Pharmacist'}</span>
        <span className="dportal__avatar" aria-hidden="true">{(profile.full_name || 'Pharmacist').trim().split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase()}</span>
        <button className="dportal__signout" type="button" onClick={() => { sessionStorage.removeItem(SESSION); setProfile(null); }}>Sign out</button>
      </div>
    </header>
    <main className="dportal__content" id="pharmacy-content" tabIndex="-1"><Routes>
      <Route path="stock" element={<Stock id={profile.id} />} />
      <Route path="consultations" element={<Consultations id={profile.id} />} />
      <Route path="consultations/:appointmentId" element={<SignedDetail id={profile.id} />} />
      <Route path="*" element={<Navigate to="/pharmacist/stock" replace />} />
    </Routes></main>
  </div>;
}
