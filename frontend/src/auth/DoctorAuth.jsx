import { createContext, useContext, useEffect, useMemo, useState } from "react";

/**
 * Doctor auth context (Phase 2.1). Holds the identified doctor profile,
 * persisted to localStorage. Dev-stage identification is phone-only: there is
 * no password, no OTP and no session token — just the doctor profile.
 */

const STORAGE_KEY = "sahayog.doctor.session";

const DoctorAuthContext = createContext(null);

function loadSession() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function DoctorAuthProvider({ children }) {
  const [session, setSession] = useState(loadSession);

  useEffect(() => {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else localStorage.removeItem(STORAGE_KEY);
  }, [session]);

  const value = useMemo(
    () => ({
      doctor: session?.profile ?? null,
      isAuthenticated: Boolean(session?.profile),
      signIn: (authResponse) => setSession(authResponse),
      signOut: () => setSession(null),
      // Update just the signature flag after upload, without re-login.
      setHasSignature: (value) =>
        setSession((s) =>
          s ? { ...s, profile: { ...s.profile, has_signature: value } } : s
        ),
    }),
    [session]
  );

  return (
    <DoctorAuthContext.Provider value={value}>
      {children}
    </DoctorAuthContext.Provider>
  );
}

export function useDoctorAuth() {
  const ctx = useContext(DoctorAuthContext);
  if (!ctx) throw new Error("useDoctorAuth must be used within DoctorAuthProvider");
  return ctx;
}
