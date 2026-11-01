import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchReports, reportBlob, uploadReport } from '../api.js';
import './Reports.css';

export default function Reports({ appointmentId, patientId, accessToken, doctorId, helpdeskId, canUpload = false }) {
  const [open, setOpen] = useState(false);
  const headers = useMemo(() => patientId ? { 'X-Patient-Id': patientId, Authorization: `Bearer ${accessToken}` }
    : helpdeskId ? { 'X-Helpdesk-Id': helpdeskId } : { 'X-Doctor-Id': doctorId }, [patientId, accessToken, doctorId, helpdeskId]);
  return <><button type="button" className="btn btn--secondary" onClick={() => setOpen(true)}>Reports</button>
    {open && <ReportDialog key={appointmentId} appointmentId={appointmentId} headers={headers} canUpload={canUpload} onClose={() => setOpen(false)} />}</>;
}

function ReportDialog({ appointmentId, headers, canUpload, onClose }) {
  const dialog = useRef(null);
  const [reports, setReports] = useState([]);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [url, setUrl] = useState('');
  const [fileError, setFileError] = useState('');
  const fileInput = useRef(null);
  const selected = reports[index];
  useEffect(() => {
    const focus = document.activeElement; const modal = dialog.current; modal.showModal();
    return () => { modal.close(); focus?.focus(); };
  }, []);
  useEffect(() => {
    let active = true; setLoading(true); setError('');
    fetchReports(appointmentId, headers).then(data => { if (active) { setReports(data.reports || []); setIndex(i => Math.min(i, Math.max(0, (data.reports || []).length - 1))); } })
      .catch(err => { if (active) setError(err.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [appointmentId, headers, retry]);
  useEffect(() => {
    setUrl(''); setFileError('');
    if (!selected?.content_type) return;
    let objectUrl; const controller = new AbortController();
    reportBlob(appointmentId, selected.id, headers, controller.signal).then(blob => {
      if (controller.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);
    }).catch(err => { if (!controller.signal.aborted) setFileError(err.message); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [appointmentId, selected, headers, retry]);
  async function add(event) {
    event.preventDefault();
    if (!file || file.size > 10 * 1024 * 1024 || !['application/pdf', 'image/png', 'image/jpeg'].includes(file.type)) {
      setError('Choose a PDF, PNG or JPEG up to 10 MB.'); return;
    }
    setSaving(true); setError('');
    try {
      const added = await uploadReport(appointmentId, headers, file, title.trim());
      setReports([...reports, added]); setIndex(reports.length); setFile(null); setTitle(''); fileInput.current.value = '';
    } catch (err) { setError(err.message); }
    finally { setSaving(false); }
  }
  return <dialog className="reports" ref={dialog} aria-labelledby="reports-title" onCancel={e => { e.preventDefault(); if (!saving) onClose(); }}>
    <header className="reports__head"><div><h2 id="reports-title">Reports</h2><p>Tests, scans and supporting documents</p></div><button className="btn btn--secondary" onClick={onClose} disabled={saving} aria-label="Close reports">Close</button></header>
    {error && <div role="alert"><p>{error}</p><button className="btn btn--secondary" disabled={saving} onClick={() => setRetry(retry + 1)}>Refresh reports</button></div>}
    {loading ? <p role="status">Loading reports...</p> : !reports.length ? <p>No reports added yet.</p> : <>
      <div className="reports__navigation"><button className="btn btn--secondary" disabled={index === 0} onClick={() => setIndex(index - 1)}>Previous report</button><span aria-live="polite">{index + 1} of {reports.length}</span><button className="btn btn--secondary" disabled={index === reports.length - 1} onClick={() => setIndex(index + 1)}>Next report</button></div>
      <h3>{selected.title}</h3><p>{new Date(selected.reported_at).toLocaleString()}</p>
      <div className="reports__preview">
        {fileError ? <div role="alert">{fileError} <button onClick={() => setRetry(retry + 1)}>Retry file</button></div>
          : selected.content_type ? !url ? <p role="status">Loading file...</p> : selected.content_type === 'application/pdf'
            ? <iframe title={selected.title} src={url} referrerPolicy="no-referrer" /> : <img src={url} alt={selected.title} />
          : <p>{typeof selected.findings?.findings === 'string' ? selected.findings.findings : 'No file attached to this report.'}</p>}
      </div>
      {url && <a className="btn btn--secondary" href={url} download={`${selected.title}.${selected.content_type === 'application/pdf' ? 'pdf' : selected.content_type === 'image/png' ? 'png' : 'jpg'}`}>Download report</a>}
    </>}
    {canUpload && <form className="reports__upload" onSubmit={add}><h3>Add report</h3>
      <label>Report title<input required maxLength={160} value={title} disabled={saving} onChange={e => setTitle(e.target.value)} /></label>
      <label>PDF or image (up to 10 MB)<input ref={fileInput} required type="file" accept="application/pdf,image/png,image/jpeg" disabled={saving} onChange={e => setFile(e.target.files[0] || null)} /></label>
      <button className="btn btn--primary" disabled={saving || loading || !file || !title.trim()}>{saving ? 'Uploading...' : 'Add report'}</button>
    </form>}
  </dialog>;
}
