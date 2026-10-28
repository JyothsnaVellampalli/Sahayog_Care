// Thin API client for the Sahayog Care backend.
// Base URL comes from VITE_API_BASE_URL (see frontend/.env.example); defaults
// to the local FastAPI server.

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = JSON.stringify(body.detail);
    } catch {
      // ignore json parse errors; keep the default message
    }
    throw new Error(detail);
  }
  return response.json();
}

export function fetchSymptoms() {
  return request("/api/symptoms");
}

export function fetchAppSettings() {
  return request("/api/settings");
}

export function submitIntake(payload) {
  return request("/api/appointments/intake", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function bookSlot({ slotId, patientId, reason, idempotencyKey, symptoms, severity, history }) {
  return request("/api/appointments/book", {
    method: "POST",
    body: JSON.stringify({
      slot_id: slotId,
      patient_id: patientId ?? null,
      reason: reason ?? null,
      idempotency_key: idempotencyKey,
      symptoms: symptoms || [],
      severity,
      history,
    }),
  });
}

// --- Patient auth (Phase 1.4) ---

export function patientLookup(phone) {
  return request("/api/patients/lookup", {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
}

export function patientLogin(phone, password) {
  return request("/api/patients/login", {
    method: "POST",
    body: JSON.stringify({ phone, password }),
  });
}

export function patientRegister(payload) {
  return request("/api/patients/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchAppointments(patientId) {
  return request(`/api/patients/${patientId}/appointments`);
}

export function fetchPatientProfile(patientId, token) {
  return request(`/api/patients/${encodeURIComponent(patientId)}/profile`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export function savePatientProfile(patientId, token, payload) {
  return request(`/api/patients/${encodeURIComponent(patientId)}/profile`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
}

// --- Doctor (Phase 2.1) ---

const API_BASE_URL_DOCTOR = API_BASE_URL;

export function doctorLookup(phone) {
  return request("/api/doctors/lookup", {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
}

// Phone-only identification (dev-stage: no password, no OTP). Returns { profile }.
export function doctorIdentify(phone) {
  return request("/api/doctors/identify", {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
}

export function doctorSignatureStatus(doctorId) {
  return request(`/api/doctors/${doctorId}/signature`);
}

export async function uploadDoctorSignature(doctorId, file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(
    `${API_BASE_URL_DOCTOR}/api/doctors/${doctorId}/signature`,
    { method: "POST", body: form }
  );
  if (!res.ok) throw new Error(`Upload failed (${res.status})`);
  return res.json();
}

export function fetchConsultations(doctorId, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v != null && v !== "")
  ).toString();
  return request(
    `/api/doctors/${doctorId}/consultations${qs ? `?${qs}` : ""}`
  );
}

export function fetchConsultation(consultationId) {
  return request(`/api/doctors/consultations/${consultationId}`);
}

export function startConsultation(consultationId, consent) {
  return request(`/api/doctors/consultations/${consultationId}/start`, {
    method: "POST",
    body: JSON.stringify({ consent }),
  });
}

export function fetchTranscript(consultationId) {
  return request(`/api/doctors/consultations/${consultationId}/transcript`);
}

export async function generateSoap(consultationId) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  try {
    return await request(`/api/doctors/consultations/${consultationId}/soap`, {
      method: "POST", signal: controller.signal,
    });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("SOAP generation or saving timed out. Please retry the summary.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export function fetchSoap(consultationId) {
  return request(`/api/doctors/consultations/${consultationId}/soap`);
}

export function saveSoap(consultationId, soap) {
  return request(`/api/doctors/consultations/${consultationId}/soap`, {
    method: "PUT", body: JSON.stringify(soap),
  });
}

export function signConsultation(consultationId, doctorId, soap) {
  return request(`/api/doctors/consultations/${consultationId}/sign`, {
    method: "POST", body: JSON.stringify({ doctor_id: doctorId, soap }),
  });
}

// Speakers are detected automatically server-side (no speaker argument).
export async function transcribeAudio(consultationId, blob, { session = 1, recordingId } = {}) {
  const form = new FormData();
  const ext = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
  form.append("file", blob, `recording.${ext}`);
  form.append("session", String(session));
  form.append("recording_id", recordingId);
  return request(
    `/api/doctors/consultations/${consultationId}/transcribe`,
    { method: "POST", headers: {}, body: form }
  );
}

export function fetchTranscriptionJob(consultationId, recordingId, signal) {
  return request(`/api/doctors/consultations/${consultationId}/transcription-jobs/${recordingId}`, { signal });
}

export function appendTranscriptSegment(consultationId, payload) {
  return request(
    `/api/doctors/consultations/${consultationId}/transcript/segment`,
    { method: "POST", body: JSON.stringify(payload) }
  );
}

export function editTranscriptSegment(consultationId, index, text) {
  return request(
    `/api/doctors/consultations/${consultationId}/transcript/segment`,
    { method: "PUT", body: JSON.stringify({ index, text }) }
  );
}

export function fetchAppointmentDetail(patientId, appointmentId, accessToken) {
  return request(`/api/patients/${encodeURIComponent(patientId)}/appointments/${encodeURIComponent(appointmentId)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function updateAppointmentDetails(patientId, appointmentId, accessToken, payload) {
  return request(`/api/patients/${encodeURIComponent(patientId)}/appointments/${encodeURIComponent(appointmentId)}`, {
    method: "PUT", headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` }, body: JSON.stringify(payload),
  });
}
