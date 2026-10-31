import { useNavigate } from "react-router-dom";
import "./LandingPage.css";

/**
 * Landing page — profile selector.
 *
 * Per docs/UI_Design.md: "A blank page with a profile selector - Patient,
 * Doctor, Front desk. The UI should look similar to google chrome asking to
 * select a profile while launching."
 *
 * Selecting the Patient profile navigates to the patient portal. Doctor and
 * Front desk portals arrive in later phases (their buttons are disabled with an
 * accessible explanation).
 */

const PROFILES = [
  {
    id: "pharmacist",
    label: "Pharmacist",
    initial: "Rx",
    color: "var(--color-primary)",
    description: "View medicine stock and signed consultations.",
    ready: true,
  },
  {
    id: "patient",
    label: "Patient",
    initial: "P",
    color: "var(--color-primary)",
    description: "Find a doctor, book, and ask about your records.",
    ready: true,
  },
  {
    id: "doctor",
    label: "Doctor",
    initial: "D",
    color: "var(--color-primary-hover)",
    description: "Review consultations and sign notes.",
    ready: true,
  },
  {
    id: "front-desk",
    label: "Front desk",
    initial: "F",
    color: "var(--color-neutral)",
    description: "Help patients and manage appointments.",
    ready: false,
  },
];

export default function LandingPage() {
  const navigate = useNavigate();

  function handleSelect(profile) {
    if (profile.id === "pharmacist") navigate("/pharmacist/login");
    if (profile.id === "patient") {
      navigate("/patient/login");
    } else if (profile.id === "doctor") {
      navigate("/doctor/login");
    }
  }

  return (
    <main className="landing" id="main-content">
      <p className="landing__brand">Sahayog Care</p>

      <section className="landing__picker" aria-labelledby="landing-title">
        <h1 className="landing__title" id="landing-title">
          Who is using Sahayog Care?
        </h1>
        <p className="landing__subtitle">Select a profile to continue</p>

        <ul className="profiles" role="list">
          {PROFILES.map((profile) => (
            <li key={profile.id}>
              <button
                type="button"
                className="profile"
                onClick={() => handleSelect(profile)}
                disabled={!profile.ready}
                aria-describedby={`profile-desc-${profile.id}`}
              >
                <span
                  className="profile__avatar"
                  style={{ backgroundColor: profile.color }}
                  aria-hidden="true"
                >
                  {profile.initial}
                </span>
                <span className="profile__label">
                  {profile.label}
                  {!profile.ready && (
                    <span className="profile__soon"> (coming soon)</span>
                  )}
                </span>
                <span
                  className="profile__description"
                  id={`profile-desc-${profile.id}`}
                >
                  {profile.description}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
