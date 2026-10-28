import { useEffect, useMemo, useState } from "react";
import { bookSlot, fetchSymptoms, submitIntake } from "../../api.js";
import SymptomMultiSelect from "../../components/SymptomMultiSelect.jsx";
import { usePatientAuth } from "../../auth/PatientAuth.jsx";
import "./BookAppointment.css";

/** Format an ISO timestamp as a readable local date + time. */
function formatSlot(iso) {
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
 * Book an appointment — symptom intake form (Phase 1.2).
 *
 * Per docs/UI_Design.md:
 *  - multi-select dropdown to pick symptoms (first row),
 *  - a detail row per selected symptom (severity, duration, remove),
 *  - a free-text box for extra detail,
 *  - submit categorises the condition (Emergency / Severe / Normal).
 */

const SEVERITIES = ["mild", "moderate", "severe"];

const CATEGORY_STYLES = {
  Emergency: { bg: "#fce8e6", fg: "#c5221f", label: "Emergency" },
  Severe: { bg: "#fef7e0", fg: "#b06000", label: "Severe" },
  Normal: { bg: "#e6f4ea", fg: "#188038", label: "Normal" },
  "Need more information": { bg: "#f1f3f4", fg: "#5f6368", label: "Need more information" },
};

export default function BookAppointment() {
  const { patient } = usePatientAuth();

  const [catalogue, setCatalogue] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(true);

  const [selectedIds, setSelectedIds] = useState([]);
  const [details, setDetails] = useState({}); // id -> { severity, duration_days }
  const [freeText, setFreeText] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [submitError, setSubmitError] = useState(null);

  useEffect(() => {
    let active = true;
    fetchSymptoms()
      .then((data) => {
        if (active) setCatalogue(data.symptoms || []);
      })
      .catch((err) => {
        if (active) setLoadError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const byId = useMemo(() => {
    const map = {};
    for (const s of catalogue) map[s.id] = s;
    return map;
  }, [catalogue]);

  function addSymptom(id) {
    if (!id || selectedIds.includes(id)) return;
    setSelectedIds((prev) => [...prev, id]);
    setDetails((prev) => ({
      ...prev,
      [id]: { severity: "", duration_days: "" },
    }));
  }

  function removeSymptom(id) {
    setSelectedIds((prev) => prev.filter((x) => x !== id));
    setDetails((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  function updateDetail(id, field, value) {
    setDetails((prev) => ({ ...prev, [id]: { ...prev[id], [field]: value } }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitError(null);
    setResult(null);
    setSubmitting(true);
    try {
      const payload = {
        patient_id: patient?.id ?? null,
        symptoms: selectedIds.map((id) => ({
          symptom_id: id,
          severity: details[id]?.severity || null,
          duration_days:
            details[id]?.duration_days === "" ||
            details[id]?.duration_days == null
              ? null
              : Number(details[id].duration_days),
        })),
        free_text: freeText || null,
        // Age and gender come from the patient profile (Phase 1.4), not the form.
      };
      const data = await submitIntake(payload);
      setResult(data);
    } catch (err) {
      setSubmitError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit =
    !submitting && (selectedIds.length > 0 || freeText.trim().length > 0);

  if (loading)
    return (
      <p className="ba__status" role="status">
        Loading symptoms…
      </p>
    );
  if (loadError)
    return (
      <p className="ba__status ba__status--error" role="alert">
        Could not load symptoms: {loadError}
      </p>
    );

  return (
    <form className="ba" onSubmit={handleSubmit}>
      <h2 className="ba__heading">Book an appointment</h2>
      <p className="ba__intro">
        Add your symptoms and any detail. We use this to understand how urgent
        your condition is.
      </p>

      {/* Row 1: searchable multi-select */}
      <div className="ba__row">
        <SymptomMultiSelect
          options={catalogue}
          selectedIds={selectedIds}
          onAdd={addSymptom}
          onRemove={removeSymptom}
          label="Symptoms"
        />
      </div>

      {/* Per-symptom detail rows */}
      {selectedIds.length > 0 && (
        <div className="ba__details">
          {selectedIds.map((id) => {
            const name = byId[id]?.label || id;
            return (
              <fieldset className="ba__detail" key={id}>
                <legend className="ba__detail-name">{name}</legend>

                <label className="ba__detail-field">
                  <span>Severity</span>
                  <select
                    value={details[id]?.severity || ""}
                    onChange={(e) => updateDetail(id, "severity", e.target.value)}
                    aria-label={`Severity of ${name}`}
                  >
                    <option value="">—</option>
                    {SEVERITIES.map((sv) => (
                      <option key={sv} value={sv}>
                        {sv}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="ba__detail-field">
                  <span>Duration (days)</span>
                  <input
                    type="number"
                    min="0"
                    value={details[id]?.duration_days ?? ""}
                    onChange={(e) =>
                      updateDetail(id, "duration_days", e.target.value)
                    }
                    aria-label={`Duration in days of ${name}`}
                  />
                </label>

                <button
                  type="button"
                  className="ba__remove"
                  onClick={() => removeSymptom(id)}
                  aria-label={`Remove ${name}`}
                >
                  Remove
                </button>
              </fieldset>
            );
          })}
        </div>
      )}

      {/* Age and gender come from the patient's profile (Phase 1.4), so the
          form no longer asks for them. */}

      {/* Free-text box */}
      <div className="ba__row">
        <label className="ba__label" htmlFor="free-text">
          Anything else? (optional)
        </label>
        <textarea
          id="free-text"
          className="ba__textarea"
          rows={4}
          placeholder="Describe how you feel in your own words."
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
        />
      </div>

      <button className="ba__submit" type="submit" disabled={!canSubmit}>
        {submitting ? "Checking…" : "Show available slots"}
      </button>

      {submitError && (
        <p className="ba__status ba__status--error" role="alert">
          {submitError}
        </p>
      )}

      {result && <IntakeResult result={result} />}
    </form>
  );
}

function IntakeResult({ result }) {
  const classification = result.classification || {};
  const category = classification.category;
  const style = category ? CATEGORY_STYLES[category] : null;
  const scores = classification.scores || {};
  const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]);

  return (
    <section
      className="ba__result"
      aria-live="polite"
      aria-labelledby="ba-result-heading"
    >
      <h3 className="ba__result-heading" id="ba-result-heading">
        Assessment
      </h3>

      {category ? (
        <div
          className="ba__badge"
          style={{ backgroundColor: style?.bg, color: style?.fg }}
        >
          {style?.label || category}
        </div>
      ) : (
        <div className="ba__badge ba__badge--muted">Could not assess</div>
      )}

      {ranked.length > 0 && (
        <ul className="ba__scores">
          {ranked.map(([label, value]) => {
            const pct = Math.round(value * 100);
            return (
              <li
                key={label}
                className="ba__score"
                aria-label={`${label}: ${pct} percent`}
              >
                <span className="ba__score-label" aria-hidden="true">
                  {label}
                </span>
                <span className="ba__score-bar" aria-hidden="true">
                  <span className="ba__score-fill" style={{ width: `${pct}%` }} />
                </span>
                <span className="ba__score-value" aria-hidden="true">
                  {pct}%
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {/* Emergency: show the handled-later message, no booking. */}
      {result.outcome === "emergency" && (
        <p className="ba__emergency" role="alert">
          {result.emergency_message}
        </p>
      )}

      {/* Non-emergency: specialty + doctor/slot selection. */}
      {result.outcome === "booking" && <BookingSection result={result} />}

      {result.note && <p className="ba__note">{result.note}</p>}

      {Object.keys(result.removed_identifiers || {}).length > 0 && (
        <p className="ba__privacy">
          For your privacy, personal details you typed were removed before
          analysis.
        </p>
      )}
    </section>
  );
}

function BookingSection({ result }) {
  const { patient } = usePatientAuth();
  const [bookedSlotId, setBookedSlotId] = useState(null);
  const [bookingError, setBookingError] = useState(null);
  const [pendingSlot, setPendingSlot] = useState(null);
  const [bookingKeys] = useState(() => new Map());

  const specialtyName = result.specialty?.name;
  const category = result.classification?.category;
  const reason = specialtyName ? `${specialtyName} - ${category}` : category;

  async function handleBook(slotId) {
    setBookingError(null);
    setPendingSlot(slotId);
    if (!bookingKeys.has(slotId)) bookingKeys.set(slotId, crypto.randomUUID());
    try {
      const res = await bookSlot({
        slotId,
        patientId: patient?.id,
        reason,
        idempotencyKey: bookingKeys.get(slotId),
        symptoms: result.symptoms,
        severity: category,
        history: result.deidentified_text,
      });
      if (res.ok) {
        setBookedSlotId(slotId);
      } else {
        setBookingError(res.reason || "Could not book this slot.");
      }
    } catch (err) {
      setBookingError(err.message);
    } finally {
      setPendingSlot(null);
    }
  }

  const doctors = result.doctors || [];

  if (bookedSlotId) {
    return (
      <p className="ba__booked" role="status">
        Your appointment slot is reserved. We will confirm the details shortly.
      </p>
    );
  }

  return (
    <div className="booking">
      {specialtyName && (
        <p className="booking__specialty">
          Suggested specialty: <strong>{specialtyName}</strong>
        </p>
      )}

      {result.severe_guidance && (
        <p className="booking__severe" role="status">
          {result.severe_guidance}
        </p>
      )}

      {doctors.length === 0 ? (
        <p className="ba__note">
          No doctors with open slots are available right now. Please try again
          later.
        </p>
      ) : (
        <ul className="booking__doctors" aria-label="Available doctors">
          {doctors.map((doc) => (
            <li key={doc.id} className="doctor">
              <div className="doctor__head">
                <span className="doctor__name">{doc.full_name}</span>
                <span className="doctor__meta">
                  {doc.facility_name ? `${doc.facility_name}` : ""}
                  {doc.city ? ` · ${doc.city}` : ""}
                  {doc.years_experience != null
                    ? ` · ${doc.years_experience} yrs`
                    : ""}
                </span>
              </div>

              {doc.slots.length === 0 ? (
                <p className="doctor__noslots">No open slots.</p>
              ) : (
                <ul
                  className="doctor__slots"
                  aria-label={`Open slots for ${doc.full_name}`}
                >
                  {doc.slots.map((slot) => (
                    <li key={slot.id}>
                      <button
                        type="button"
                        className="slot"
                        onClick={() => handleBook(slot.id)}
                        disabled={pendingSlot === slot.id}
                        aria-label={`Book ${formatSlot(slot.starts_at)} with ${doc.full_name}`}
                      >
                        {pendingSlot === slot.id
                          ? "Booking…"
                          : formatSlot(slot.starts_at)}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}

      {bookingError && (
        <p className="ba__status ba__status--error" role="alert">
          {bookingError}
        </p>
      )}
    </div>
  );
}
