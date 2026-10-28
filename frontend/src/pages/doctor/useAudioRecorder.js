import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Minimal MediaRecorder wrapper for the Consultation Scribe (Phase 2.1).
 *
 * start() opens the mic; stop() delivers the captured audio Blob to onComplete
 * (so the caller can POST it to the transcribe endpoint). Also
 * exposes an elapsed-seconds counter and a 0..1 `level` for the listening
 * animation, derived from the Web Audio analyser.
 */
export function useAudioRecorder(onComplete) {
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const completeRef = useRef(onComplete);
  completeRef.current = onComplete;
  const mountedRef = useRef(true);
  const startingRef = useRef(false);
  const supported = Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);

  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const timerRef = useRef(null);
  const rafRef = useRef(null);
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);

  const cleanup = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    timerRef.current = null;
    rafRef.current = null;
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    analyserRef.current = null;
    setLevel(0);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const recorder = mediaRecorderRef.current;
      if (recorder) {
        recorder.onstop = recorder.ondataavailable = recorder.onerror = null;
        if (recorder.state !== "inactive") recorder.stop();
      }
      cleanup();
    };
  }, [cleanup]);

  const tickLevel = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser) return;
    const data = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteTimeDomainData(data);
    // RMS deviation from the 128 midpoint -> rough 0..1 loudness.
    let sum = 0;
    for (let i = 0; i < data.length; i += 1) {
      const v = (data[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / data.length);
    setLevel(Math.min(1, rms * 3));
    rafRef.current = requestAnimationFrame(tickLevel);
  }, []);

  const start = useCallback(async () => {
    if (startingRef.current || mediaRecorderRef.current?.state === "recording") return;
    startingRef.current = true;
    setStarting(true);
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mountedRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;

      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        const ctx = new AudioCtx();
        const source = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        audioCtxRef.current = ctx;
        analyserRef.current = analyser;
        rafRef.current = requestAnimationFrame(tickLevel);
      }

      const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"]
        .find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        cleanup();
        setRecording(false);
        mediaRecorderRef.current = null;
        if (mountedRef.current) completeRef.current?.(blob);
      };
      recorder.onerror = () => {
        setError("Recording was interrupted. Any captured audio will be processed when recording stops.");
        if (recorder.state !== "inactive") recorder.stop();
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
      setElapsed(0);
      const began = Date.now();
      timerRef.current = setInterval(() => {
        const seconds = Math.floor((Date.now() - began) / 1000);
        setElapsed(seconds);
        // Stay below Sarvam's two-hour per-file limit.
        if (seconds >= 7190 && recorder.state === "recording") recorder.stop();
      }, 1000);
    } catch (err) {
      setError(
        err?.name === "NotAllowedError"
          ? "Microphone permission denied."
          : "Could not access the microphone."
      );
      cleanup();
      setRecording(false);
    } finally {
      startingRef.current = false;
      if (mountedRef.current) setStarting(false);
    }
  }, [cleanup, tickLevel]);

  const stop = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }, []);

  return { supported, starting, recording, elapsed, level, error, start, stop };
}
