import { useEffect, useState } from "react";
import { fetchAppointments } from "../../api.js";
import { usePatientAuth } from "../../auth/PatientAuth.jsx";
import "./MyAppointments.css";

/** Format an ISO timestamp as a readable local date + time. */
function formatWhen(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/**
 * My appointments (Phase 1.4).
 *
 * Lists the logged-in patient's appointments (date, doctor, reason, status),
 * per docs/UI_Design.md.
 */
export default function MyAppointments() {
  const { patient } = usePatientAuth();
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!patient?.id) return;
    let active = true;
    setLoading(true);
    fetchAppointments(patient.id)
      .then((data) => {
        if (active) setAppointments(data.appointments || []);
      })
      .catch((err) => {
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [patient?.id]);

  return (
    <section className="ma">
      <h2 className="ma__heading">My appointments</h2>

      {loading && (
        <p className="ma__status" role="status">
          Loading your appointments…
        </p>
      )}
      {error && (
        <p className="ma__status ma__status--error" role="alert">
          {error}
        </p>
      )}

      {!loading && !error && (
        <table className="ma__table">
          <caption className="sr-only">Your booked appointments</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Doctor</th>
              <th scope="col">Reason</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {appointments.length === 0 ? (
              <tr>
                <td colSpan={4} className="ma__empty">
                  No appointments yet. Book one from “Book an appointment”.
                </td>
              </tr>
            ) : (
              appointments.map((a) =>
                a.type === "emergency" ? (
                  <tr key={a.id} className="ma__row--emergency">
                    <td>{formatWhen(a.created_at) }</td>
                    <td>
                      <span className="ma__tag ma__tag--emergency">
                        Emergency
                      </span>
                    </td>
                    <td>{a.reason || "Emergency"}</td>
                    <td>Awaiting care team</td>
                  </tr>
                ) : (
                  <tr key={a.id}>
                    <td>{formatWhen(a.starts_at)}</td>
                    <td>
                      {a.doctor_name || "—"}
                      {a.specialty ? ` (${a.specialty})` : ""}
                    </td>
                    <td>{a.reason || "—"}</td>
                    <td>{a.status || "—"}</td>
                  </tr>
                )
              )
            )}
          </tbody>
        </table>
      )}
    </section>
  );
}
