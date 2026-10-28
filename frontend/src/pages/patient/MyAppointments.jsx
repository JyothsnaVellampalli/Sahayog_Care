import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fetchAppointments } from "../../api.js";
import { usePatientAuth } from "../../auth/PatientAuth.jsx";
import "./MyAppointments.css";

export function formatWhen(iso) {
  if (!iso) return "Time to be confirmed";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "Time to be confirmed" : date.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
export function StatusPill({ status }) {
  const label = { BOOKED: "Scheduled", SCHEDULED: "Scheduled", COMPLETED: "Completed", CANCELLED: "Cancelled", IN_PROGRESS: "In progress", EMERGENCY_PENDING: "Awaiting care team" }[status] || status || "Pending";
  const color = ["BOOKED", "SCHEDULED"].includes(status) ? "success" : status === "CANCELLED" || status === "EMERGENCY_PENDING" ? "danger" : status === "IN_PROGRESS" ? "warning" : "neutral";
  return <span className={`pill pill--${color}`}>{label}</span>;
}
export default function MyAppointments() {
  const { patient } = usePatientAuth();
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retry, setRetry] = useState(0);
  const [params, setParams] = useSearchParams();
  const filter = ["upcoming", "past"].includes(params.get("filter")) ? params.get("filter") : "all";
  useEffect(() => {
    let active = true;
    setLoading(true); setError(null);
    fetchAppointments(patient.id).then(data => { if (active) setAppointments(data.appointments || []); })
      .catch(err => { if (active) setError(err.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [patient.id, retry]);
  const visible = appointments.filter(a => {
    const past = a.type !== "emergency" && (["COMPLETED", "CANCELLED"].includes(a.status) || (a.starts_at && new Date(a.starts_at).getTime() < Date.now()));
    return filter === "all" || (filter === "past" ? past : !past);
  });
  return <section className="ma">
    <div className="ma__header"><div><h1 className="ma__heading">My appointments</h1>
      <p className="ma__intro">Select an appointment to see its symptoms, consultation notes and summary.</p></div>
      <div className="ma__filters" role="group" aria-label="Filter appointments">
        {["all", "upcoming", "past"].map(value => <button key={value} type="button" aria-pressed={filter === value} onClick={() => setParams(value === "all" ? {} : { filter: value })}>{value}</button>)}
      </div>
    </div>
    {loading && <p role="status">Loading your appointments...</p>}
    {error && <div role="alert"><p>{error}</p><button className="btn btn--secondary" onClick={() => setRetry(retry + 1)}>Try again</button></div>}
    {!loading && !error && <div className="ma__table-wrap"><table className="ma__table">
      <caption className="sr-only">Your {filter} appointments</caption>
      <thead><tr><th scope="col">Date</th><th scope="col">Doctor</th><th scope="col">Reason</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Details</span></th></tr></thead>
      <tbody>{visible.map(a => <tr key={`${a.type}-${a.id}`}>
        <td data-label="Date">{formatWhen(a.starts_at || a.created_at)}</td>
        <td data-label="Doctor">{a.type === "emergency" ? "Emergency care" : a.doctor_name || "To be assigned"}{a.specialty && <small>{a.specialty}</small>}</td>
        <td data-label="Reason">{a.reason || "Not provided"}</td>
        <td data-label="Status"><StatusPill status={a.status} /></td>
        <td>{a.type === "emergency" ? <span className="ma__pending">Pending care team review</span> : <Link className="ma__view" to={`/patient/my-appointments/${a.id}`} aria-label={`View details for appointment with ${a.doctor_name || "doctor"} on ${formatWhen(a.starts_at)}`}>View details <span aria-hidden="true">›</span></Link>}</td>
      </tr>)}</tbody>
    </table>{visible.length === 0 && <div className="ma__empty"><p>No {filter === "all" ? "" : filter + " "}appointments found.</p><Link className="btn btn--primary" to="/patient/book-appointment">Book an appointment</Link></div>}</div>}
  </section>;
}
