import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  patientLogin,
  patientLookup,
  patientRegister,
} from "../../api.js";
import { usePatientAuth } from "../../auth/PatientAuth.jsx";
import "./PatientLogin.css";

/**
 * Patient login / registration (Phase 1.4).
 *
 * Step 1: phone + password. We look the phone up:
 *   - exists  -> log in with phone + password.
 *   - new     -> go to step 2 for details (name, age, gender*, email, city),
 *                then register.
 *
 * Dev-stage auth: no OTP. On success we store the session and go to the portal.
 */
export default function PatientLogin() {
  const navigate = useNavigate();
  const { signIn } = usePatientAuth();

  const [step, setStep] = useState("credentials"); // or "details"
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");

  // Details (registration) fields.
  const [fullName, setFullName] = useState("");
  const [age, setAge] = useState("");
  const [gender, setGender] = useState("");
  const [email, setEmail] = useState("");
  const [city, setCity] = useState("Pune");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  function handleAuthResult(result) {
    if (result?.error) {
      setError(result.error);
      return false;
    }
    if (result?.profile && result?.access_token) {
      signIn(result);
      navigate("/patient");
      return true;
    }
    setError("Unexpected response. Please try again.");
    return false;
  }

  async function handleCredentials(event) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { exists } = await patientLookup(phone);
      if (exists) {
        const result = await patientLogin(phone, password);
        handleAuthResult(result);
      } else {
        // New phone: collect details.
        setStep("details");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleRegister(event) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await patientRegister({
        phone,
        password,
        full_name: fullName,
        age: Number(age),
        gender,
        email,
        city,
      });
      handleAuthResult(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login" id="main-content">
      <p className="login__brand">Sahayog Care</p>

      <section
        className="login__card"
        aria-labelledby="login-title"
      >
        <h1 className="login__title" id="login-title">
          {step === "credentials" ? "Patient sign in" : "Create your profile"}
        </h1>

        {step === "credentials" ? (
          <form className="login__form" onSubmit={handleCredentials}>
            <p className="login__intro">
              Enter your phone number and password to continue. New here? We'll
              set up your profile next.
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

            <label className="login__field">
              <span>Password</span>
              <input
                type="password"
                autoComplete="current-password"
                required
                minLength={6}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>

            <button className="login__submit" type="submit" disabled={busy}>
              {busy ? "Please wait…" : "Continue"}
            </button>
          </form>
        ) : (
          <form className="login__form" onSubmit={handleRegister}>
            <p className="login__intro">
              This phone number is new. Please add your details.
            </p>

            <label className="login__field">
              <span>Full name</span>
              <input
                type="text"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
              />
            </label>

            <div className="login__row">
              <label className="login__field">
                <span>Age</span>
                <input
                  type="number"
                  min="0"
                  max="120"
                  required
                  value={age}
                  onChange={(e) => setAge(e.target.value)}
                />
              </label>

              <label className="login__field">
                <span>Gender (required)</span>
                <select
                  required
                  value={gender}
                  onChange={(e) => setGender(e.target.value)}
                >
                  <option value="" disabled>
                    Select…
                  </option>
                  <option value="female">Female</option>
                  <option value="male">Male</option>
                  <option value="other">Other</option>
                </select>
              </label>
            </div>

            <label className="login__field">
              <span>Email</span>
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>

            <label className="login__field">
              <span>Location</span>
              <select value={city} onChange={(e) => setCity(e.target.value)}>
                <option value="Pune">Pune</option>
                <option value="Hyderabad">Hyderabad</option>
              </select>
            </label>

            <button className="login__submit" type="submit" disabled={busy}>
              {busy ? "Creating…" : "Create profile & continue"}
            </button>
          </form>
        )}

        {error && (
          <p className="login__error" role="alert">
            {error}
          </p>
        )}
      </section>
    </main>
  );
}
