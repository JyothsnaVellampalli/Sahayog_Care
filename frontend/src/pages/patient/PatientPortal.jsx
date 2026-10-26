import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { usePatientAuth } from "../../auth/PatientAuth.jsx";
import "./PatientPortal.css";

/**
 * Patient portal layout (Phase 1.2, patient identity in 1.4).
 *
 * Per docs/UI_Design.md: a header with "Sahayog Care" at the left and the
 * patient profile (name) at the right, and nav items with "Book an appointment"
 * as the default. Renders an <Outlet /> for the active section.
 */

const NAV = [
  { to: "book-appointment", label: "Book an appointment" },
  { to: "my-appointments", label: "My appointments" },
];

export default function PatientPortal() {
  const navigate = useNavigate();
  const { patient, signOut } = usePatientAuth();
  const patientName = patient?.full_name || "Patient";

  function handleSignOut() {
    signOut();
    navigate("/");
  }

  return (
    <div className="portal">
      <a className="skip-link" href="#portal-content">
        Skip to content
      </a>

      <header className="portal__header">
        <button
          className="portal__brand"
          type="button"
          onClick={() => navigate("/")}
          aria-label="Sahayog Care home"
        >
          Sahayog Care
        </button>
        <div className="portal__profile">
          <span className="portal__avatar" aria-hidden="true">
            {patientName.charAt(0).toUpperCase()}
          </span>
          <span className="portal__name">{patientName}</span>
          <button
            className="portal__signout"
            type="button"
            onClick={handleSignOut}
          >
            Sign out
          </button>
        </div>
      </header>

      <nav className="portal__nav" aria-label="Patient portal sections">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              "portal__navitem" + (isActive ? " portal__navitem--active" : "")
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main className="portal__content" id="portal-content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
