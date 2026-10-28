import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useDoctorAuth } from "../../auth/DoctorAuth.jsx";
import "./DoctorPortal.css";

/**
 * Doctor portal layout (Phase 2.1). Header mirrors the patient portal: brand
 * left, doctor name + avatar right. Nav: Consultations (default), Profile.
 */

const NAV = [
  { to: "consultations", label: "Consultations" },
  { to: "profile", label: "Profile" },
];

function initials(name) {
  if (!name) return "DR";
  const parts = name.replace(/^dr\.?\s*/i, "").trim().split(/\s+/);
  return (parts[0]?.[0] || "D").concat(parts[1]?.[0] || "").toUpperCase();
}

export default function DoctorPortal() {
  const navigate = useNavigate();
  const { doctor, signOut } = useDoctorAuth();
  const name = doctor?.full_name || "Doctor";

  function handleSignOut() {
    signOut();
    navigate("/doctor/login", { replace: true });
  }

  return (
    <div className="dportal">
      <a className="skip-link" href="#dportal-content">
        Skip to content
      </a>

      <header className="dportal__header">
        <div className="dportal__left">
          <button
            className="dportal__brand"
            type="button"
            onClick={() => navigate("/")}
            aria-label="Sahayog Care home"
          >
            <span className="dportal__brand-mark" aria-hidden="true" />
            Sahayog Care
          </button>
          <nav className="dportal__nav" aria-label="Doctor portal sections">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={`/doctor/${item.to}`}
                className={({ isActive }) =>
                  "dportal__navitem" +
                  (isActive ? " dportal__navitem--active" : "")
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="dportal__profile">
          <span className="dportal__name">{name}</span>
          <span className="dportal__avatar" aria-hidden="true">
            {initials(name)}
          </span>
          <button
            className="dportal__signout"
            type="button"
            onClick={handleSignOut}
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="dportal__content" id="dportal-content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
