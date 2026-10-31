import { useEffect, useRef, useState } from 'react';
import { fetchDoctorMedicines, fetchPrescription, savePrescription, savePrescriptionWorkspace } from '../../api.js';
import PrescriptionList from '../../components/PrescriptionList.jsx';
import './PrescriptionEditor.css';

const fields = ['strength_form', 'dose', 'frequency', 'duration', 'instructions'];
const labels = { strength_form: 'Strength / form', dose: 'Dose', frequency: 'Frequency', duration: 'Duration', instructions: 'Instructions (optional)' };
const title = text => text ? text[0].toUpperCase() + text.slice(1) : '';

function MedicinePicker({ doctorId, chosen, onAdd, onClose }) {
  const dialog = useRef(null);
  const [catalogue, setCatalogue] = useState(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [search, setSearch] = useState('');
  const [specialty, setSpecialty] = useState('');
  const [form, setForm] = useState('');
  const [inStock, setInStock] = useState(false);
  const [selected, setSelected] = useState([]);
  useEffect(() => {
    const node = dialog.current;
    node.showModal();
    return () => node.close();
  }, []);
  useEffect(() => {
    let active = true;
    setError('');
    fetchDoctorMedicines(doctorId).then(data => {
      if (active) { setCatalogue(data); setSpecialty(data.default_specialty); }
    }).catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [doctorId, retry]);
  const rows = (catalogue?.items || []).filter(row =>
    (!specialty || row.specialty === specialty) && (!form || row.forms.includes(form)) &&
    (!inStock || row.available_quantity > 0) &&
    [row.brand, row.generic_name, row.composition, row.variant].join(' ').toLowerCase().includes(search.toLowerCase().trim()));
  const forms = [...new Set((catalogue?.items || []).flatMap(row => row.forms))].sort();
  return <dialog className="rx-picker" ref={dialog} onCancel={onClose} aria-labelledby="medicine-picker-title">
    <header className="rx__head"><div><h2 id="medicine-picker-title">Add medicine</h2><p>Pharmacy catalogue · Select medicines for this consultation</p></div>
      <button type="button" className="btn btn--secondary" onClick={onClose} aria-label="Close medicine list">×</button></header>
    <div className="rx-picker__filters">
      <label>Search medicines<input autoFocus value={search} onChange={e => setSearch(e.target.value)} placeholder="Brand, generic or composition" /></label>
      <div className="rx-picker__filter-row"><label>Specialty<select value={specialty} onChange={e => setSpecialty(e.target.value)}>
        <option value="">All specialties</option>{(catalogue?.specialties || []).map(value => <option key={value} value={value}>{title(value)}</option>)}</select></label>
        <label>Form<select value={form} onChange={e => setForm(e.target.value)}><option value="">All forms</option>{forms.map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="rx-picker__checkbox"><input type="checkbox" checked={inStock} onChange={e => setInStock(e.target.checked)} />In stock only</label>
        <button type="button" className="btn btn--secondary" onClick={() => { setSearch(''); setSpecialty(''); setForm(''); setInStock(false); }}>Clear filters</button>
      </div>
    </div>
    <div className="rx-picker__results">
      {error ? <div role="alert"><p>{error}</p><button className="btn btn--secondary" onClick={() => setRetry(v => v + 1)}>Retry catalogue</button></div>
        : !catalogue ? <p role="status">Loading medicines…</p> : <>
          <p role="status">{rows.length} results</p>
          {!rows.length && <p>No medicines match these filters.</p>}
          {rows.map(row => <label key={row.brand_id} className="rx-picker__medicine">
            <input type="checkbox" disabled={chosen.includes(row.brand_id)} checked={chosen.includes(row.brand_id) || selected.includes(row.brand_id)}
              onChange={e => setSelected(old => e.target.checked ? [...old, row.brand_id] : old.filter(id => id !== row.brand_id))} />
            <span><strong>{row.brand}</strong><span>{row.generic_name} · {row.variant}</span><small>{row.composition}</small></span>
            <span className={`pill pill--${row.available_quantity > 0 ? 'success' : 'neutral'}`}>{row.available_quantity == null ? 'Not counted' : row.available_quantity > 0 ? `${row.available_quantity} available` : 'Out of stock'}</span>
          </label>)}
        </>}
    </div>
    <footer className="rx-picker__footer"><span>{selected.length} selected</span><button type="button" className="btn btn--secondary" onClick={onClose}>Cancel</button>
      <button type="button" className="btn btn--primary" disabled={!selected.length} onClick={() => { onAdd(catalogue.items.filter(row => selected.includes(row.brand_id))); onClose(); }}>Add to prescription</button></footer>
  </dialog>;
}

export default function PrescriptionEditor({ consultationId, doctorId, soap, closed, locked, processing = false, onReady }) {
  const [items, setItems] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [revision, setRevision] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [picker, setPicker] = useState(false);
  const [retry, setRetry] = useState(0);
  const backupKey = `sahayog.prescription.draft.${doctorId}.${consultationId}`;
  const dirty = useRef(false);
  const pendingWrite = useRef(null);
  const writes = useRef(Promise.resolve());
  const timer = useRef(null);
  const editVersion = useRef(0);
  function workspaceItems(rows) {
    return rows.map(item => ({ ...Object.fromEntries(['brand_id', 'brand', 'variant', ...fields].map(key => [key, item[key] || ''])),
      quantity: item.quantity === '' || item.quantity == null ? null : Number(item.quantity) }));
  }
  function flush() {
    clearTimeout(timer.current);
    if (!pendingWrite.current) return writes.current;
    const rows = pendingWrite.current;
    const version = editVersion.current;
    pendingWrite.current = null;
    writes.current = writes.current.catch(() => {}).then(() => savePrescriptionWorkspace(consultationId, doctorId, workspaceItems(rows)));
    writes.current.then(() => {
      if (version === editVersion.current) setNotice('Draft autosaved. Review it after SOAP is ready.');
    }).catch(() => setNotice('Server autosave unavailable. Your draft is kept in this browser; retry saving before signing.'));
    return writes.current;
  }
  function queue(rows) {
    pendingWrite.current = rows;
    clearTimeout(timer.current);
    timer.current = setTimeout(flush, 500);
  }
  useEffect(() => {
    const savePending = () => { flush().catch(() => {}); };
    const onVisibility = () => { if (document.visibilityState === 'hidden') savePending(); };
    window.addEventListener('pagehide', savePending);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('pagehide', savePending);
      document.removeEventListener('visibilitychange', onVisibility);
      savePending();
    };
  }, [consultationId, doctorId]);
  useEffect(() => {
    let active = true;
    onReady(false); setLoaded(false); setError(''); setNotice('');
    fetchPrescription(consultationId, doctorId).then(data => {
      if (!active) return;
      let backup;
      try { backup = JSON.parse(localStorage.getItem(backupKey)); } catch { /* optional backup */ }
      const recover = !closed && backup?.items && (!data.workspace_updated_at || backup.updatedAt > data.workspace_updated_at);
      const rows = recover ? backup.items : data.items;
      dirty.current = recover || !data.reviewed;
      setItems(rows); setSuggestions(data.suggestions || []); setRevision(data.soap_revision);
      setReviewed(data.reviewed && !recover); setLoaded(true); onReady(data.reviewed && !recover);
      if (recover) { setNotice('Restored your prescription draft.'); queue(rows); }
      if (closed) { try { localStorage.removeItem(backupKey); } catch { /* optional */ } }
    }).catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [consultationId, doctorId, closed, retry, onReady]);
  useEffect(() => {
    if (!loaded || closed) return;
    let active = true;
    if (processing) { onReady(false); return; }
    fetchPrescription(consultationId, doctorId).then(data => {
      if (!active) return;
      setRevision(data.soap_revision); setSuggestions(data.suggestions || []);
      const ready = data.reviewed && !dirty.current;
      setReviewed(ready); onReady(ready);
    }).catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [soap, processing, loaded, closed, consultationId, doctorId, onReady]);
  function change(next) {
    dirty.current = true; editVersion.current += 1;
    setItems(next); setReviewed(false); onReady(false); setNotice('Saving draft…');
    try { localStorage.setItem(backupKey, JSON.stringify({ items: next, updatedAt: new Date().toISOString() })); }
    catch { setNotice('Browser backup unavailable. Keep this screen open until autosave completes.'); }
    queue(next);
  }
  function add(rows) {
    const ids = new Set(items.map(item => item.brand_id));
    change([...items, ...rows.filter(row => !ids.has(row.brand_id)).map(row => ({ ...row, strength_form: '', dose: '', frequency: '', duration: '', instructions: '', quantity: '' }))]);
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(''); onReady(false);
    try {
      await flush();
      const result = await savePrescription(consultationId, doctorId, { soap_revision: revision,
        items: items.map(item => ({ ...Object.fromEntries(['brand_id', ...fields].map(key => [key, item[key] || ''])), quantity: Number(item.quantity) })) });
      dirty.current = false;
      try { localStorage.removeItem(backupKey); } catch { /* optional */ }
      setItems(result.items); setReviewed(true); onReady(true); setNotice('Prescription saved and reviewed.');
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }
  return <section className="rx" aria-labelledby="prescription-title">
    <header className="rx__head"><div><h2 id="prescription-title">Medicines</h2><p>Prescription for this consultation</p></div>
      {!closed && <button type="button" className="btn btn--secondary" disabled={!loaded || locked || busy} onClick={() => setPicker(true)}>+ Add medicine</button>}</header>
    {!loaded && !error && <p className="rx__body" role="status">Loading prescription…</p>}
    {error && <div className="rx__body" role="alert"><p>{error}</p><button type="button" className="btn btn--secondary" onClick={() => { if (!loaded || window.confirm('Reload the saved prescription and discard unsaved edits?')) setRetry(v => v + 1); }}>Reload prescription</button></div>}
    {loaded && (closed ? <div className="rx__body"><PrescriptionList items={items} /></div> : <>
      {suggestions.some(row => !items.some(item => item.brand_id === row.brand_id)) && <div className="rx__body">
        <p><span className="pill pill--neutral">Mentioned in SOAP</span> Catalogue matches for review. A mention may describe past use or a medicine to avoid.</p>
        <div className="rx__suggestions">{suggestions.filter(row => !items.some(item => item.brand_id === row.brand_id)).map(row => <article key={row.brand_id}>
          <strong>{row.brand}</strong><p>{row.variant}</p><p>{row.reason}</p><div className="rx__actions">
            <button type="button" className="btn btn--primary" disabled={locked || busy} onClick={() => add([row])}>Add {row.brand}</button>
            <button type="button" className="btn btn--secondary" disabled={locked || busy} onClick={() => setSuggestions(old => old.filter(item => item.brand_id !== row.brand_id))}>Dismiss {row.brand}</button>
          </div></article>)}</div>
      </div>}
      <form onSubmit={save}><fieldset disabled={locked || busy} className="rx__body">
        {!items.length && <p>No medicines selected. Add a medicine, or save an empty prescription if none are needed.</p>}
        {items.map((item, index) => <div key={item.brand_id} className="rx__item">
          <div className="rx__medicine"><strong>{item.brand}</strong><span>{item.variant}</span></div>
          {fields.map(key => <label key={key}>{labels[key]}<input aria-label={`${labels[key]} for ${item.brand}`} required={key !== 'instructions'} maxLength={key === 'instructions' ? 500 : 150}
            value={item[key] || ''} onChange={e => change(items.map((row, i) => i === index ? { ...row, [key]: e.target.value } : row))} /></label>)}
          <label>Stock quantity<input aria-label={`Stock quantity for ${item.brand}`} type="number" required min="1" max="1000000" step="1" value={item.quantity ?? ''}
            onChange={e => change(items.map((row, i) => i === index ? { ...row, quantity: e.target.value } : row))} /></label>
          <button type="button" className="btn btn--secondary" aria-label={`Remove ${item.brand}`} onClick={() => change(items.filter((_, i) => i !== index))}>×</button>
        </div>)}
        <p className="rx__hint">Confirm strength, form and instructions. Enter the total stock units to reserve; stock is reserved when you sign, not when you save the draft.</p>
        <div className="rx__actions"><button type="submit" className="btn btn--primary" disabled={!revision || processing}>{busy ? 'Saving…' : 'Save prescription'}</button><span>{processing || !revision ? 'Draft autosaves while SOAP is processing. Review and save when SOAP is ready.' : reviewed ? 'Reviewed' : 'Review required before signing'}</span></div>
        <p role="status">{notice}</p>
      </fieldset></form>
    </>)}
    {picker && <MedicinePicker doctorId={doctorId} chosen={items.map(item => item.brand_id)} onAdd={add} onClose={() => setPicker(false)} />}
  </section>;
}
