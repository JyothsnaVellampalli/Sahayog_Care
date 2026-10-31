import { useEffect, useRef, useState } from 'react';
import { fetchConsultationProcessing, retryConsultationProcessing, transcribeAudio, fetchTranscript, fetchSoap, generateSoap } from '../../api.js';
import { loadAudioDraft, saveAudioDraft, deleteAudioDraft } from './audioDrafts.js';

/** Server jobs own processing. Browser state only tracks an unacknowledged upload. */
export function useSarvamTranscription(consultationId, onComplete, enabled = true, onSoap) {
  const [upload, setUpload] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [jobList, setJobs] = useState([]);
  const [ready, setReady] = useState(false);
  const [note, setNote] = useState(null);
  const [pollError, setPollError] = useState('');
  const [revision, setRevision] = useState(0);
  const completeRef = useRef(onComplete);
  const soapRef = useRef(onSoap);
  completeRef.current = onComplete;
  soapRef.current = onSoap;
  const seen = useRef(new Set());
  const inFlight = useRef(false);
  useEffect(() => {
    let active = true;
    loadAudioDraft(consultationId).then(item => {
      if (active && item) { setUpload(item); setNote('A saved recording is ready to upload. Select Retry upload.'); }
    }).catch(() => {});
    return () => { active = false; };
  }, [consultationId]);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    let timer;
    const controller = new AbortController();
    async function poll() {
      try {
        const data = await fetchConsultationProcessing(consultationId, controller.signal);
        if (!active) return;
        const jobs = data.jobs || [];
        setJobs(jobs); setReady(true); setPollError('');
        const unseen = jobs.filter(job => job.state === 'SUCCEEDED' && !seen.current.has(job.id));
        if (unseen.some(job => job.kind === 'TRANSCRIPTION')) {
          const transcript = await fetchTranscript(consultationId);
          if (!active) return;
          completeRef.current(transcript.segments || []);
        }
        if (unseen.some(job => job.kind === 'SOAP')) {
          const saved = await fetchSoap(consultationId);
          if (!active) return;
          soapRef.current?.(saved);
        }
        unseen.forEach(job => seen.current.add(job.id));
      } catch (error) {
        if (active) setPollError('Could not refresh processing status. Saved jobs continue on the server.');
      } finally {
        if (active) timer = setTimeout(poll, 3000);
      }
    }
    poll();
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [consultationId, enabled, revision]);

  function watch(job) {
    if (job) setJobs(old => [job, ...old.filter(item => item.id !== job.id)]);
    setRevision(value => value + 1);
  }
  async function send(item) {
    if (inFlight.current) return;
    inFlight.current = true; setUpload(item); setUploading(true); setNote('Saving and uploading audio…');
    let backedUp = false;
    try {
      try { await saveAudioDraft(consultationId, item); backedUp = true; }
      catch { setNote('Browser audio backup is unavailable. Keep this screen open until upload finishes.'); }
      const response = await transcribeAudio(consultationId, item.blob, { session: item.session, recordingId: item.id });
      watch(response.job);
      await deleteAudioDraft(consultationId).catch(() => {});
      setUpload(null); setNote(null);
    } catch (error) { setNote(`${error.message} ${backedUp ? 'Retry uploading this saved recording.' : 'The recording remains in this tab. Keep it open and retry uploading.'}`); }
    finally { inFlight.current = false; setUploading(false); }
  }
  function submit(blob, session) {
    if (!blob?.size) { setNote('No audio was captured. Please record again.'); return; }
    send({ id: crypto.randomUUID(), blob, session });
  }
  async function retryJob(job) {
    try { watch((await retryConsultationProcessing(consultationId, job.id)).job); }
    catch (error) { setNote(error.message); }
  }
  async function startSoap() { watch((await generateSoap(consultationId)).job); }
  const active = jobList.filter(job => ['QUEUED', 'RUNNING'].includes(job.state));
  const audioJob = active.find(job => job.kind === 'TRANSCRIPTION');
  const soapJob = active.find(job => job.kind === 'SOAP');
  const latestFailed = ['TRANSCRIPTION', 'SOAP'].map(kind => jobList.find(job => job.kind === kind)).filter(job => job?.state === 'FAILED');
  const pending = upload ? { ...upload, uploaded: false } : audioJob ? { id: audioJob.id, uploaded: true } : null;
  return { pending, uploading, processingReady: ready, pollError, jobs: jobList, failedJobs: latestFailed,
    busy: uploading || Boolean(audioJob), soapBusy: Boolean(soapJob),
    note: uploading ? 'Uploading audio…' : audioJob ? 'Processing audio… Your recording is saved. You can select medicines while we prepare your transcript.' : note,
    submit, startSoap, retryJob, retry: () => upload ? send(upload) : setRevision(value => value + 1),
    discard: async () => { await deleteAudioDraft(consultationId); setUpload(null); setNote(null); },
  };
}
