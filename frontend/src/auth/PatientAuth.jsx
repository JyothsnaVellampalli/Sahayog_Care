import { createContext, useContext, useEffect, useMemo, useState } from "react";

/**
 * Patient auth context (Phase 1.4).
 *
 * Holds the logged-in patient profile and access token. Persisted to
 * localStorage so a page refresh keeps the session. This is dev-stage auth
 * (phone + password, no OTP); the token is a real Supabase Auth JWT that will
 * carry roles for future authorization.
 */

const STORAGE_KEY = "sahayog.patient.session";

const PatientAuthContext = createContext(null);

function loadSession() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function PatientAuthProvider({ children }) {
  const [session, setSession] = useState(loadSession);

  useEffect(() => {
    if (session) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [session]);

  const value = useMemo(
    () => ({
      patient: session?.profile ?? null,
      accessToken: session?.access_token ?? null,
      isAuthenticated: Boolean(session?.profile),
      signIn: (authResponse) => setSession(authResponse),
      updateProfile: (profile) => setSession(current => current ? { ...current, profile } : current),
      signOut: () => setSession(null),
    }),
    [session]
  );

  return (
    <PatientAuthContext.Provider value={value}>
      {children}
    </PatientAuthContext.Provider>
  );
}

export function usePatientAuth() {
  const ctx = useContext(PatientAuthContext);
  if (!ctx) {
    throw new Error("usePatientAuth must be used within PatientAuthProvider");
  }
  return ctx;
}
