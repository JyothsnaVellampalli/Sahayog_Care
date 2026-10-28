import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { doctorIdentify } from "../../api.js";
import { useDoctorAuth } from "../../auth/DoctorAuth.jsx";
import "../patient/PatientLogin.css";

/**
 * Doctor sign-in (Phase 2.1, dev-stage).
 *
 * Doctors are identified by phone number alone — no password, no OTP. Each
 * doctor is pre-seeded with a unique phone number; entering it looks up the
 * profile and signs the doctor in.
 */
export default function DoctorLogin() {
  const navigate = useNavigate();
  const { signIn } = useDoctorAuth();

  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await doctorIdentify(phone.trim());
      if (result?.error) {
        setError(result.error);
        return;
      }
      if (result?.profile) {
        signIn(result);
        navigate("/doctor");
        return;
      }
      setError("Unexpected response. Please try again.");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login" id="main-content">
      <p className="login__brand">Sahayog Care</p>

      <section className="login__card" aria-labelledby="doctor-login-title">
        <h1 className="login__title" id="doctor-login-title">
          Doctor sign in
        </h1>

        <form className="login__form" onSubmit={handleSubmit}>
          <p className="login__intro">
            Enter your registered phone number to continue.
          </p>
          <label className="login__field">
            <span>Phone number</span>
            <input
              type="tel"
              autoComplete="tel"
              required
              placeholder="+91XXXXXXXXXX"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
          </label>
          <button className="login__submit" type="submit" disabled={busy}>
            {busy ? "Please wait…" : "Continue"}
          </button>
        </form>

        {error && (
          <p className="login__error" role="alert">
            {error}
          </p>
        )}
      </section>
    </main>
  );
}
