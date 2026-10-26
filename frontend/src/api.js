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

export function submitIntake(payload) {
  return request("/api/appointments/intake", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function bookSlot({ slotId, patientId, reason }) {
  return request("/api/appointments/book", {
    method: "POST",
    body: JSON.stringify({
      slot_id: slotId,
      patient_id: patientId ?? null,
      reason: reason ?? null,
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
