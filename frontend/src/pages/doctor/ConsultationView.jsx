import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  appendTranscriptSegment,
  editTranscriptSegment,
  fetchConsultation,
  fetchTranscript,
  startConsultation,
  generateSoap,
  fetchSoap,
  saveSoap,
  signConsultation,
  fetchAppSettings,
} from "../../api.js";
import {
  SEVERITY_META,
  SEVERITY_FALLBACK,
  STATUS_META,
  formatSlotTime,
  personLine,
} from "./consultationMeta.js";
import { useAudioRecorder } from "./useAudioRecorder.js";
import { useSarvamTranscription } from "./useSarvamTranscription.js";
import "./ConsultationView.css";
import { useDoctorAuth } from "../../auth/DoctorAuth.jsx";

/**
 * Consultation view (Phase 2.1, design screens 3 & 4).
 *
 * Flow: collapsible patient details -> consent checkbox + "Start consultation"
 * (sets IN_PROGRESS) -> capture audio -> Sarvam transcription and speaker turns.
 * Saved SOAP is reviewed and signed to close the visit and lock its content.
 */

function fmtMMSS(total) {
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

const DETAIL_SECTIONS = [
  { key: "symptoms", label: "Symptoms" },
  { key: "history", label: "History" },
  { key: "allergies", label: "Allergies" },
  { key: "vitals", label: "Vitals" },
];

export default function ConsultationView() {
  const { consultationId } = useParams();
  return <ConsultationContent key={consultationId} />;
}

function ConsultationContent() {
  const { consultationId } = useParams();
  const navigate = useNavigate();
  const { doctor } = useDoctorAuth();

  const [detail, setDetail] = useState(null);
  const [showTranscripts, setShowTranscripts] = useState(false);
  useEffect(() => {
    let active = true;
    fetchAppSettings().then((config) => {
      if (active) setShowTranscripts(config.show_speech_transcripts === true);
    }).catch(() => { /* Keep validation-only content hidden if settings fail. */ });
    return () => { active = false; };
  }, []);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [consent, setConsent] = useState(false);
  const [starting, setStarting] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(true);

  const [segments, setSegments] = useState([]);
  const [busyTranscribe, setBusyTranscribe] = useState(false);
  const [note, setNote] = useState(null);
  const [soap, setSoap] = useState(null);
  const [soapBusy, setSoapBusy] = useState(false);
  const [soapError, setSoapError] = useState(null);
  const [soapEditing, setSoapEditing] = useState(false);
  const [soapFields, setSoapFields] = useState({});
  const [soapLoaded, setSoapLoaded] = useState(false);
  const [signed, setSigned] = useState(null);
  const [signing, setSigning] = useState(false);
  const closed = ["COMPLETED", "CANCELLED", "NO_SHOW"].includes(detail?.status);
  const soapRequest = useRef(0);

  // Session increments each time recording resumes (drives "Resumed" divider).
  const sessionRef = useRef(1);
  const transcriptRevision = useRef(0);
  const [editingIndex, setEditingIndex] = useState(null);
  const [editingText, setEditingText] = useState("");

  const sarvam = useSarvamTranscription(consultationId, (saved) => {
    transcriptRevision.current += 1;
    setSegments(saved);
    sessionRef.current = saved.reduce((m, s) => Math.max(m, s.session || 1), sessionRef.current);
  }, detail?.status === "IN_PROGRESS");
  const recorder = useAudioRecorder((blob) => sarvam.submit(blob, sessionRef.current));
  const transcriptBusy = busyTranscribe || sarvam.busy;

  // Loading a visit only reads saved SOAP; generation is an explicit action.
  useEffect(() => {
    let active = true;
    fetchSoap(consultationId).then((saved) => {
      if (!active) return;
      setSoap(saved.soap);
      setSigned(saved.signature ? saved : null);
      setSoapLoaded(true);
    }).catch((err) => { if (active) setSoapError(err.message); });
    return () => { active = false; };
  }, [consultationId]);

  useEffect(() => () => { soapRequest.current += 1; }, []);

  useEffect(() => {
    if (closed || (!recorder.recording && !sarvam.pending)) return;
    function warnOnLeave(event) { event.preventDefault(); event.returnValue = ""; }
    window.addEventListener("beforeunload", warnOnLeave);
    return () => window.removeEventListener("beforeunload", warnOnLeave);
  }, [recorder.recording, sarvam.pending, closed]);

  async function handleGenerateSoap() {
    if (closed || signing) return;
    const request = ++soapRequest.current;
    setSoapBusy(true);
    setSoapError(null);
    setSoapEditing(false);
    try {
      const draft = await generateSoap(consultationId);
      if (request === soapRequest.current) setSoap(draft);
    } catch (err) {
      if (request === soapRequest.current) setSoapError(err.message);
    } finally {
      if (request === soapRequest.current) setSoapBusy(false);
    }
  }

  function editSummary() {
    setSoapFields(Object.fromEntries(Object.entries(soap).map(([key, values]) => [key, values.join("\n")])));
    setSoapEditing(true);
  }

  async function applySummaryEdits() {
    setSoapBusy(true);
    setSoapError(null);
    const edited = Object.fromEntries(Object.entries(soapFields).map(([key, text]) =>
      [key, text.split("\n").map((line) => line.trim()).filter(Boolean)]));
    try {
      setSoap(await saveSoap(consultationId, edited));
      setSoapEditing(false);
    } catch (err) { setSoapError(err.message); }
    finally { setSoapBusy(false); }
  }

  async function handleSign() {
    setSigning(true);
    setSoapError(null);
    try {
      const completed = await signConsultation(consultationId, doctor.id, soap);
      setDetail(completed);
      setSoapEditing(false);
      const saved = await fetchSoap(consultationId);
      setSoap(saved.soap);
      setSigned(saved);
    } catch (err) { setSoapError(err.message); }
    finally { setSigning(false); }
  }

  const loadDetail = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await fetchConsultation(consultationId);
      if (d?.error) {
        setError(d.error);
      } else {
        setDetail(d);
        setConsent(Boolean(d.consent_recorded));
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [consultationId]);

  const loadTranscript = useCallback(async () => {
    const revision = transcriptRevision.current;
    try {
      const t = await fetchTranscript(consultationId);
      if (revision !== transcriptRevision.current) return;
      const segs = Array.isArray(t?.segments) ? t.segments : [];
      setSegments(segs);
      const maxSession = segs.reduce((m, s) => Math.max(m, s.session || 1), 1);
      sessionRef.current = maxSession;
    } catch (err) {
      setNote(`Could not load the saved transcript: ${err.message}`);
    }
  }, [consultationId]);

  useEffect(() => {
    loadDetail();
    loadTranscript();
  }, [loadDetail, loadTranscript]);

  const started = detail?.status === "IN_PROGRESS" || detail?.status === "COMPLETED";

  async function handleStart() {
    if (!consent) return;
    setStarting(true);
    setError(null);
    try {
      const res = await startConsultation(consultationId, true);
      if (res?.error) setError(res.error);
      else {
        setDetail((d) => ({ ...d, status: "IN_PROGRESS", consent_recorded: true }));
        setDetailsOpen(false);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  }

  async function handleMicToggle() {
    if (recorder.recording) {
      recorder.stop();
    } else {
      // Resuming after a prior session starts a new session block.
      if (segments.length > 0) sessionRef.current += 1;
      recorder.start();
    }
  }

  function beginEdit(index, text) {
    setEditingIndex(index);
    setEditingText(text);
  }

  async function saveEdit() {
    if (editingIndex == null) return;
    setBusyTranscribe(true);
    try {
      const res = await editTranscriptSegment(
        consultationId,
        editingIndex,
        editingText
      );
      if (res?.segments) setSegments(res.segments);
      setEditingIndex(null);
      setEditingText("");
    } catch (err) {
      setNote(err.message);
    } finally {
      setBusyTranscribe(false);
    }
  }

  async function addManualSegment() {
    setBusyTranscribe(true);
    try {
      const res = await appendTranscriptSegment(consultationId, {
        speaker: null,
        text: "(type here)",
        session: sessionRef.current,
      });
      if (res?.segments) {
        setSegments(res.segments);
        beginEdit(res.segments.length - 1, "");
      }
    } catch (err) {
      setNote(err.message);
    } finally {
      setBusyTranscribe(false);
    }
  }

  const sev = SEVERITY_META[detail?.severity] || SEVERITY_FALLBACK;
  const st = STATUS_META[detail?.status] || STATUS_META.SCHEDULED;
  const editedCount = useMemo(
    () => segments.filter((s) => s.edited).length,
    [segments]
  );

  if (loading) return <p className="cview__loading">Loading consultation…</p>;
  if (error && !detail)
    return (
      <div className="cview">
        <p className="cview__error" role="alert">
          {error}
        </p>
        <button className="btn btn--secondary" onClick={() => navigate(-1)}>
          Back
        </button>
      </div>
    );

  return (
    <section className="cview" aria-labelledby="cview-title">
      <fieldset disabled={signing} className="cview__content">
      <button className="cview__back" onClick={() => navigate("/doctor/consultations")}>
        ← Consultations
      </button>

      {/* Collapsible patient bar */}
      <div className="cview__patient">
        <button
          className="cview__patient-head"
          onClick={() => setDetailsOpen((o) => !o)}
          aria-expanded={detailsOpen}
        >
          <span
            className={"cview__chevron" + (detailsOpen ? " cview__chevron--open" : "")}
            aria-hidden="true"
          >
            ▸
          </span>
          <span className="cview__patient-name" id="cview-title">
            {personLine(
              detail.patient_name,
              detail.patient_age,
              detail.patient_gender
            )}
          </span>
          <span className="cview__slot">{formatSlotTime(detail.starts_at)}</span>
          <span className={`pill ${sev.pill}`}>{sev.label}</span>
          <span className={`pill ${st.pill}`}>{st.label}</span>
        </button>

        {detailsOpen && (
          <div className="cview__details">
            {DETAIL_SECTIONS.map((sec) => {
              let value = detail[sec.key];
              if (sec.key === "symptoms")
                value = (detail.symptoms || []).join(", ");
              return (
                <div className="cview__detail" key={sec.key}>
                  <span className="cview__detail-label">
                    {sec.label.toUpperCase()}
                  </span>
                  <span className="cview__detail-value">
                    {value || "—"}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Recorder panel */}
      {!closed && <div className="cview__scribe">
        {!started ? (
          <div className="cview__consent-block">
            <label className="cview__consent">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />
              <span>
                Patient has consented to recording this consultation and sending
                the audio to Sarvam for transcription and speaker separation.
              </span>
            </label>
            <button
              className="btn btn--primary"
              onClick={handleStart}
              disabled={!consent || starting}
            >
              {starting ? "Starting…" : "Start consultation"}
            </button>
          </div>
        ) : (
          <div className="cview__mic-block">
            <button
              type="button"
              className={
                "cview__mic" + (recorder.recording ? " cview__mic--rec" : "")
              }
              onClick={handleMicToggle}
              disabled={transcriptBusy || soapBusy || soapEditing || Boolean(sarvam.pending) || recorder.starting || !recorder.supported || editingIndex != null}
              aria-label={recorder.recording ? "Stop listening" : "Start listening"}
              style={{
                "--mic-level": recorder.recording ? recorder.level : 0,
              }}
            >
              <span className="cview__mic-halo" aria-hidden="true" />
              <span className="cview__mic-icon" aria-hidden="true">
                {recorder.recording ? "■" : "🎤"}
              </span>
            </button>

            {recorder.recording ? (
              <>
                <p className="cview__listening">
                  Listening {fmtMMSS(recorder.elapsed)}
                </p>
                <div className="cview__eq" aria-hidden="true">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <span
                      key={i}
                      className="cview__eq-bar"
                      style={{
                        animationDelay: `${i * 0.12}s`,
                        height: `${8 + recorder.level * 28 + (i % 2) * 6}px`,
                      }}
                    />
                  ))}
                </div>
                <p className="cview__hint">Tap the circle to stop</p>
              </>
            ) : (
              <p className="cview__hint">
                {sarvam.busy ? "Transcribing recording…" : soapBusy ? "Translating and preparing summary…" : recorder.starting ? "Opening microphone…" : "Tap the circle to speak"}
              </p>
            )}

            {/* <p className="cview__diar-hint">
              Speak in English, Hindi, Telugu, or a mix. Press Stop to send this
              recording to Sarvam. The transcript will show Person 1, Person 2,
              and other detected speakers after processing.
            </p>
            <p className="cview__diar-hint">
              Speaker numbers apply within each recording. Resuming starts a new
              recording; the same number may refer to a different person.
            </p> */}
          </div>
        )}

        {!recorder.supported && (
          <p className="cview__note" role="status">
            Microphone recording is unavailable. Use a supported browser over HTTPS or localhost, or add notes manually.
          </p>
        )}
        {recorder.error && (
          <p className="cview__error" role="alert">
            {recorder.error}
          </p>
        )}
        {note && (
          <p className="cview__note" role="status">
            {note}
          </p>
        )}
      </div>}

        {!closed && sarvam.note && (
          <div className="cview__live" role="status">
            <p>{sarvam.note}</p>
            {sarvam.pending && !sarvam.busy && <div>
              {(!sarvam.pending.failed || sarvam.pending.blob) && (
                <button className="btn btn--secondary" onClick={sarvam.retry}>
                  {sarvam.pending.failed ? "Retry processing" : sarvam.pending.uploaded ? "Check again" : "Retry upload"}
                </button>
              )}
              <button className="btn btn--secondary" onClick={() => {
                if (window.confirm("Discard this pending recording from this tab? Any submitted Sarvam job may continue processing.")) sarvam.discard();
              }}>Discard pending recording</button>
            </div>}
          </div>
        )}

      {/* Transcript */}
      {showTranscripts && <div className="cview__transcript">
        <div className="cview__transcript-head">
          <h2 className="cview__transcript-title">Transcript</h2>
          <span className="cview__transcript-meta">
            {segments.length} segment{segments.length === 1 ? "" : "s"}
            {editedCount > 0 ? ` · ${editedCount} edited` : ""}
          </span>
          {started && !closed && (
            <button
              type="button"
              className="cview__add"
              onClick={addManualSegment}
              disabled={recorder.recording || recorder.starting || transcriptBusy || soapBusy || soapEditing || Boolean(sarvam.pending) || editingIndex != null}
            >
              + Add note
            </button>
          )}
        </div>

        {segments.length === 0 ? (
          <p className="cview__transcript-empty">
            No transcript yet. Start listening or add a note to capture the conversation.
          </p>
        ) : (
          <ol className="cview__rows">
            {segments.map((seg, i) => {
              const prev = segments[i - 1];
              const showDivider = seg.recording_id
                ? seg.recording_id !== prev?.recording_id
                : prev && (seg.session || 1) > (prev.session || 1);
              return (
                <li key={i}>
                  {showDivider && (
                    <div className="cview__resumed">
                      Recording {seg.session || 1} · {seg.ts} · Speaker numbers are local to this recording
                    </div>
                  )}
                  <div
                    className={
                      "cview__row" +
                      " cview__row--plain" +
                      (seg.edited ? " cview__row--edited" : "")
                    }
                  >
                    <div className="cview__row-top">
                      {seg.speaker && (
                        <span className="cview__row-speaker">{seg.speaker}</span>
                      )}
                      <span className="cview__row-ts">
                        {seg.start_seconds != null
                          ? `${fmtMMSS(Math.floor(seg.start_seconds))} – ${fmtMMSS(Math.floor(seg.end_seconds))}`
                          : seg.ts}
                      </span>
                      {seg.edited && (
                        <span className="cview__row-edited">Edited</span>
                      )}
                      {!closed && editingIndex !== i && (
                        <button
                          type="button"
                          className="cview__row-edit"
                          onClick={() => beginEdit(i, seg.text)}
                          disabled={recorder.recording || recorder.starting || transcriptBusy || soapBusy || soapEditing || Boolean(sarvam.pending)}
                        >
                          Edit
                        </button>
                      )}
                    </div>
                    {!closed && editingIndex === i ? (
                      <div className="cview__edit">
                        <textarea
                          value={editingText}
                          onChange={(e) => setEditingText(e.target.value)}
                          rows={2}
                          autoFocus
                        />
                        <div className="cview__edit-actions">
                          <button
                            className="btn btn--secondary"
                            onClick={() => setEditingIndex(null)}
                            disabled={busyTranscribe}
                          >
                            Cancel
                          </button>
                          <button
                            className="btn btn--primary"
                            onClick={saveEdit}
                            disabled={busyTranscribe || !editingText.trim()}
                          >
                            Save
                          </button>
                        </div>
                      </div>
                    ) : (
                      <p className="cview__row-text">{seg.text}</p>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      }
      {/* Saved SOAP and the final signature snapshot. */}
      <div className="cview__soap">
        <div className="cview__soap-head">
          <h2 className="cview__transcript-title">Clinical summary</h2>
          <span className="pill pill--neutral">{closed ? "Closed" : "Unsigned draft"}</span>
          {!closed && soap && !soapEditing && <button className="cview__row-edit" onClick={editSummary}
            disabled={soapBusy || recorder.recording || recorder.starting || transcriptBusy || Boolean(sarvam.pending) || editingIndex != null}>
            Edit summary
          </button>}
        </div>
        {!closed && <p className="cview__soap-hint">
          Review the saved summary and apply any edits before signing. Regenerate only when you want a new summary from the transcript.
        </p>}
        {!soapLoaded && !soapError && <p role="status">Loading saved summary...</p>}
        {!closed && soapLoaded && !soapEditing && <button className="btn btn--secondary" onClick={handleGenerateSoap}
          disabled={!segments.length || soapBusy || recorder.recording || recorder.starting || transcriptBusy || Boolean(sarvam.pending) || editingIndex != null}>
          {soap ? "Regenerate summary" : "Generate summary"}
        </button>}
        {soapBusy && <p role="status">Translating and preparing your SOAP summary…</p>}
        {soapError && <div role="alert"><p className="cview__error">{soapError}</p>
          <button className="btn btn--secondary" onClick={() => window.location.reload()}>Reload saved summary</button>
        </div>}
        {soap && <div className="cview__soap-sections" aria-live="polite">
          {["subjective", "objective", "assessment", "plan"].map((key) => (
            <section key={key}>
              <h3 id={`soap-${key}`}>{key[0].toUpperCase() + key.slice(1)}</h3>
              {!closed && soapEditing ? <textarea aria-labelledby={`soap-${key}`} rows={3}
                value={soapFields[key] || ""}
                onChange={(event) => setSoapFields((fields) => ({ ...fields, [key]: event.target.value }))} />
                : soap[key].length ? <ul>{soap[key].map((text, i) => <li key={i}>{text}</li>)}</ul>
                : <p>Not documented in the transcript.</p>}
            </section>
          ))}
        </div>}
        {!closed && soapEditing && <div className="cview__edit-actions">
          <button disabled={soapBusy} className="btn btn--secondary" onClick={() => setSoapEditing(false)}>Cancel</button>
          <button disabled={soapBusy} className="btn btn--primary" onClick={applySummaryEdits}>Apply edits</button>
        </div>}
        {closed && signed?.signature && <div className="cview__signature">
          <img src={signed.signature} alt={`Signature of ${signed.doctor_name || "doctor"}`} />
          <p>{signed.doctor_name}</p>
          <p>Signed and closed {new Date(signed.signed_at).toLocaleString()}</p>
        </div>}
      </div>
      {!closed && started && soap && <div className="cview__close">
        <button className="btn btn--primary" onClick={handleSign}
          disabled={!doctor?.id || doctor.id !== detail.doctor_id || !soapLoaded || soapBusy || soapEditing || recorder.recording || recorder.starting || transcriptBusy || Boolean(sarvam.pending) || editingIndex != null}>
          {signing ? "Signing and closing..." : "Sign and close"}
        </button>
        <p>Signing closes this consultation and locks its summary and transcript.</p>
      </div>}
      </fieldset>
    </section>
  );
}
