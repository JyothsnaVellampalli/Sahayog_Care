import { useEffect, useRef, useState } from "react";
import { fetchTranscriptionJob, transcribeAudio } from "../../api.js";

/** Upload once, poll without overlapping requests, resume jobs after refresh. */
export function useSarvamTranscription(consultationId, onComplete, enabled = true) {
  const key = `sahayog.transcription.${consultationId}`;
  const [pending, setPending] = useState(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(key));
      return saved?.id ? { ...saved, uploaded: true } : null;
    } catch { return null; }
  });
  const [uploading, setUploading] = useState(false);
  const [polling, setPolling] = useState(Boolean(pending));
  const [note, setNote] = useState(null);
  const completeRef = useRef(onComplete);
  completeRef.current = onComplete;

  async function upload(item) {
    setPending(item);
    setUploading(true);
    setNote("Uploading recording to Sarvam…");
    try {
      await transcribeAudio(consultationId, item.blob, { session: item.session, recordingId: item.id });
      // Persist only job identity, never audio or the API key in browser storage.
      try { sessionStorage.setItem(key, JSON.stringify({ id: item.id, session: item.session })); } catch { /* storage may be disabled */ }
      setPending({ ...item, uploaded: true });
      setPolling(true);
      setNote("Sarvam is transcribing and separating speakers…");
    } catch (err) {
      setNote(`${err.message} The recording is retained in this tab for retry.`);
    } finally { setUploading(false); }
  }

  useEffect(() => {
    if (!enabled || !pending?.uploaded || !polling) return;
    let active = true;
    let timer;
    let attempts = 0;
    const controller = new AbortController();
    async function poll() {
      try {
        const result = await fetchTranscriptionJob(consultationId, pending.id, controller.signal);
        if (!active) return;
        if (result.state === "Completed") {
          completeRef.current(result.segments || []);
          setNote(result.note || "Transcript saved. Speaker numbers apply within this recording.");
          setPending(null);
          setPolling(false);
          try { sessionStorage.removeItem(key); } catch { /* optional storage */ }
        } else if (result.state === "Failed") {
          setNote(result.note);
          setPending((item) => ({ ...item, failed: true }));
          setPolling(false);
        } else if (++attempts >= 120) {
          setNote("Sarvam is still processing. Select Check again to continue waiting.");
          setPolling(false);
        } else {
          setNote("Sarvam is transcribing and separating speakers…");
          timer = setTimeout(poll, 5000);
        }
      } catch (err) {
        if (!active) return;
        setNote(`${err.message} Select Check again to resume this job.`);
        setPolling(false);
      }
    }
    poll();
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [consultationId, key, pending?.id, pending?.uploaded, polling, enabled]);

  function submit(blob, session) {
    if (!blob?.size) { setNote("No audio was captured. Please record again."); return; }
    upload({ id: crypto.randomUUID(), blob, session, uploaded: false });
  }

  function retry() {
    if (!pending) return;
    if (pending.uploaded && !pending.failed) setPolling(true);
    else if (pending.blob) upload({ ...pending, id: pending.failed ? crypto.randomUUID() : pending.id, uploaded: false, failed: false });
  }

  function discard() {
    setPending(null);
    setPolling(false);
    setNote(null);
    try { sessionStorage.removeItem(key); } catch { /* optional storage */ }
  }

  return { pending, busy: uploading || polling, note, submit, retry, discard };
}
