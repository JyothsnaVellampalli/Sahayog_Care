import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchConsultations } from "../../api.js";
import { useDoctorAuth } from "../../auth/DoctorAuth.jsx";
import {
  SEVERITY_META,
  SEVERITY_FALLBACK,
  STATUS_META,
  formatSlotTime,
  personLine,
} from "./consultationMeta.js";
import "./ConsultationsList.css";

/**
 * Doctor home: today's consultations (Phase 2.1, design screen 2).
 *
 * Date range segmented control (Today / This week / Custom) + status filter
 * pills. Each card shows a severity-coloured left border, slot time, patient
 * line, symptom chips, and status + severity pills. Click opens the view.
 */

const STATUS_FILTERS = [
  { key: "", label: "All" },
  { key: "SCHEDULED", label: "Scheduled" },
  { key: "IN_PROGRESS", label: "In progress" },
  { key: "COMPLETED", label: "Completed" },
];

// --- date range helpers (local time -> ISO bounds the API filters on) ---

function startOfDay(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}
function endOfDay(d) {
  const x = new Date(d);
  x.setHours(23, 59, 59, 999);
  return x;
}
function todayRange() {
  const now = new Date();
  return { from: startOfDay(now), to: endOfDay(now) };
}
function weekRange() {
  const now = new Date();
  const day = now.getDay(); // 0 Sun..6 Sat
  const mondayOffset = (day + 6) % 7;
  const monday = startOfDay(now);
  monday.setDate(monday.getDate() - mondayOffset);
  const sunday = endOfDay(monday);
  sunday.setDate(sunday.getDate() + 6);
  return { from: monday, to: sunday };
}

function toInputDate(d) {
  return d.toISOString().slice(0, 10);
}

export default function ConsultationsList() {
  const navigate = useNavigate();
  const { doctor } = useDoctorAuth();

  const [range, setRange] = useState("today"); // today | week | custom
  const [customDate, setCustomDate] = useState(toInputDate(new Date()));
  const [status, setStatus] = useState("");

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const bounds = useMemo(() => {
    if (range === "week") return weekRange();
    if (range === "custom") {
      const base = new Date(`${customDate}T00:00:00`);
      return { from: startOfDay(base), to: endOfDay(base) };
    }
    return todayRange();
  }, [range, customDate]);

  const load = useCallback(async () => {
    if (!doctor?.id) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchConsultations(doctor.id, {
        date_from: bounds.from.toISOString(),
        date_to: bounds.to.toISOString(),
        status: status || undefined,
      });
      setItems(Array.isArray(data?.consultations) ? data.consultations : []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [doctor?.id, bounds, status]);

  useEffect(() => {
    load();
  }, [load]);

  const scheduledCount = items.filter(
    (c) => c.status === "SCHEDULED"
  ).length;

  return (
    <section className="clist" aria-labelledby="clist-title">
      <header className="clist__head">
        <div>
          <h1 className="clist__title" id="clist-title">
            Consultations
          </h1>
          <p className="clist__count">
            {loading
              ? "Loading…"
              : `${items.length} in view · ${scheduledCount} scheduled`}
          </p>
        </div>

        <div className="clist__range" role="group" aria-label="Date range">
          {[
            { key: "today", label: "Today" },
            { key: "week", label: "This week" },
            { key: "custom", label: "Custom" },
          ].map((opt) => (
            <button
              key={opt.key}
              type="button"
              className={
                "clist__seg" + (range === opt.key ? " clist__seg--active" : "")
              }
              onClick={() => setRange(opt.key)}
              aria-pressed={range === opt.key}
            >
              {opt.label}
            </button>
          ))}
          {range === "custom" && (
            <input
              type="date"
              className="clist__date"
              value={customDate}
              onChange={(e) => setCustomDate(e.target.value)}
              aria-label="Custom date"
            />
          )}
        </div>
      </header>

      <div className="clist__filters" role="group" aria-label="Status filter">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.key || "all"}
            type="button"
            className={
              "clist__filter" +
              (status === f.key ? " clist__filter--active" : "")
            }
            onClick={() => setStatus(f.key)}
            aria-pressed={status === f.key}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <p className="clist__error" role="alert">
          {error}
        </p>
      )}

      {!loading && !error && items.length === 0 && (
        <p className="clist__empty">No consultations in this range.</p>
      )}

      <ul className="clist__cards" role="list">
        {items.map((c) => {
          const sev = SEVERITY_META[c.severity] || SEVERITY_FALLBACK;
          const st = STATUS_META[c.status] || STATUS_META.SCHEDULED;
          const symptoms = Array.isArray(c.symptoms) ? c.symptoms : [];
          return (
            <li key={`${c.type}-${c.id}`}>
              <button
                type="button"
                className="ccard"
                disabled={c.type === "emergency"}
                style={{ borderLeftColor: sev.color }}
                onClick={() =>
                  navigate(`/doctor/consultations/${c.id}`)
                }
              >
                <div className="ccard__main">
                  <span className="ccard__time">
                    {c.type === "emergency" ? "Awaiting manual assignment" : formatSlotTime(c.starts_at)}
                  </span>
                  <span className="ccard__name">
                    {personLine(c.patient_name, c.patient_age, c.patient_gender)}
                  </span>
                  <div className="ccard__symptoms">
                    {symptoms.slice(0, 3).map((s, i) => (
                      <span className="ccard__chip" key={i}>
                        {s}
                      </span>
                    ))}
                    {symptoms.length > 3 && (
                      <span className="ccard__chip ccard__chip--more">
                        +{symptoms.length - 3} more
                      </span>
                    )}
                  </div>
                </div>
                <div className="ccard__meta">
                  <span className={`pill ${st.pill}`}>{st.label}</span>
                  <span className={`pill ${sev.pill}`}>{sev.label}</span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
