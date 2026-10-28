import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
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

export default function BookAppointment() {
  const { patient } = usePatientAuth();
  const [activeTab, setActiveTab] = useState("symptoms");
  const slotTabRef = useRef(null);
  useEffect(() => {
    if (activeTab === "slots") slotTabRef.current?.focus();
  }, [activeTab]);

  const [catalogue, setCatalogue] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);

  const [selectedIds, setSelectedIds] = useState([]);
  const [details, setDetails] = useState({}); // id -> { severity, duration_days }
  const [freeText, setFreeText] = useState("");

  const [draftStatus, setDraftStatus] = useState("");
  const draftKey = "sahayog.intake.draft." + patient?.id;
  useEffect(() => {
    try {
      const draft = JSON.parse(sessionStorage.getItem(draftKey) || "null");
      if (draft && Array.isArray(draft.selectedIds) && draft.details && typeof draft.freeText === "string") {
        setSelectedIds(draft.selectedIds); setDetails(draft.details); setFreeText(draft.freeText);
        setDraftStatus("Saved draft restored.");
      }
    } catch { setDraftStatus("The saved draft could not be restored."); }
  }, [draftKey]);
  function saveDraft() {
    try {
      sessionStorage.setItem(draftKey, JSON.stringify({ selectedIds, details, freeText }));
      setDraftStatus("Draft saved for this browser tab.");
    } catch { setDraftStatus("Could not save the draft. Please keep this page open."); }
  }
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const locationVersion = useRef(0);
  useEffect(() => {
    function resetSuggestions() {
      locationVersion.current += 1;
      setResult(null); setActiveTab("symptoms");
    }
    window.addEventListener("patient-location-changed", resetSuggestions);
    return () => window.removeEventListener("patient-location-changed", resetSuggestions);
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true); setLoadError(null);
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
  }, [retry]);

  const byId = useMemo(() => {
    const map = {};
    for (const s of catalogue) map[s.id] = s;
    return map;
  }, [catalogue]);

  function addSymptom(id) {
    setResult(null);
    if (!id || selectedIds.includes(id)) return;
    setSelectedIds((prev) => [...prev, id]);
    setDetails((prev) => ({
      ...prev,
      [id]: { severity: "", duration_days: "" },
    }));
  }

  function removeSymptom(id) {
    setResult(null);
    setSelectedIds((prev) => prev.filter((x) => x !== id));
    setDetails((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  function updateDetail(id, field, value) {
    setResult(null);
    setDetails((prev) => ({ ...prev, [id]: { ...prev[id], [field]: value } }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const requestedLocationVersion = locationVersion.current;
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
      if (requestedLocationVersion !== locationVersion.current && data.outcome !== "emergency") return;
      setResult(data);
      setActiveTab("slots");
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
      <div className="ba__status ba__status--error" role="alert">
        <p>Could not load symptoms: {loadError}</p>
        <button className="btn btn--secondary" onClick={() => setRetry(retry + 1)}>Try again</button>
      </div>
    );

  return (
    <section className="ba">
      <h1 className="ba__heading">Book an appointment</h1>
      <p className="ba__intro">
        Tell us what you're experiencing. This helps the doctor prepare before your consultation.
      </p>

      <div className="ba__tabs" role="tablist" aria-label="Booking steps" onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === "Home" || !result ? "symptoms" : event.key === "End" ? "slots" : activeTab === "symptoms" ? "slots" : "symptoms";
        setActiveTab(next);
        document.getElementById("booking-tab-" + next)?.focus();
      }}>
        <button type="button" role="tab" id="booking-tab-symptoms" aria-controls="booking-panel-symptoms" aria-selected={activeTab === "symptoms"} tabIndex={activeTab === "symptoms" ? 0 : -1} onClick={() => setActiveTab("symptoms")}>1. Symptoms</button>
        <button type="button" role="tab" id="booking-tab-slots" ref={slotTabRef} aria-controls="booking-panel-slots" aria-selected={activeTab === "slots"} tabIndex={activeTab === "slots" ? 0 : -1} disabled={!result} onClick={() => setActiveTab("slots")}>2. Slot booking</button>
      </div>
      <div role="tabpanel" id="booking-panel-symptoms" aria-labelledby="booking-tab-symptoms" hidden={activeTab !== "symptoms"}>
      <form className="ba" onSubmit={handleSubmit}>
      <fieldset className="ba__card" disabled={submitting}>
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
              <div className="ba__detail" key={id} role="group" aria-labelledby={`symptom-${id}`}>
                <h2 className="ba__detail-name" id={`symptom-${id}`}>{name}</h2>

                <fieldset className="ba__severity">
                  <legend>Severity</legend>
                  <div className="ba__segments">
                    {SEVERITIES.map(sv => <label key={sv}>
                      <input type="radio" name={"severity-" + id} value={sv} required
                        checked={details[id]?.severity === sv}
                        onChange={() => updateDetail(id, "severity", sv)} />
                      <span>{sv}</span>
                    </label>)}
                  </div>
                </fieldset>
                <label className="ba__detail-field">
                  <span>Duration (days)</span>
                  <input
                    type="number"
                    min="0" max="3650" required
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
              </div>
            );
          })}
        </div>
      )}

      {/* Age and gender come from the patient's profile (Phase 1.4), so the
          form no longer asks for them. */}

      {/* Free-text box */}
      <div className="ba__row">
        <label className="ba__label" htmlFor="free-text">
          Anything else the doctor should know? (optional)
        </label>
        <textarea
          id="free-text"
          className="ba__textarea"
          rows={4}
          maxLength={4000}
          placeholder="Medicines you're taking, past conditions, anything that makes symptoms better or worse..."
          value={freeText}
          onChange={(e) => { setFreeText(e.target.value); setResult(null); }}
        />
      </div>

      <div className="ba__actions">
      <button type="button" className="btn btn--secondary" onClick={saveDraft}>Save draft</button>
      <button className="ba__submit" type="submit" disabled={!canSubmit}>
        {submitting ? "Checking…" : "Show available slots"}
      </button>

      </div>
      <p role="status" className="ba__draft-status">{draftStatus}</p>
      </fieldset>
      {submitError && (
        <p className="ba__status ba__status--error" role="alert">
          {submitError}
        </p>
      )}

      </form>
      </div>
      <div role="tabpanel" id="booking-panel-slots" aria-labelledby="booking-tab-slots" hidden={activeTab !== "slots"}>
        {result && <IntakeResult result={result} />}
      </div>
    </section>
  );
}

function IntakeResult({ result }) {
  return (
    <section className="ba__result" aria-labelledby="ba-result-heading">
      <h2 className="ba__result-heading" id="ba-result-heading">Slot booking</h2>
      {/* Emergency: show the handled-later message, no booking. */}
      {result.outcome === "emergency" && (
        <p className="ba__emergency" role="alert">
          It looks like an emergency. Our team will contact you immediately to help you get care.
        </p>
      )}

      {/* Non-emergency: specialty + doctor/slot selection. */}
      {result.outcome === "emergency" && result.specialty?.name && <p>Suggested specialty: <strong>{result.specialty.name}</strong></p>}
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
        try { sessionStorage.removeItem("sahayog.intake.draft." + patient?.id); } catch {}
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
        Your appointment is booked. <Link to="/patient/my-appointments">View my appointments</Link>
      </p>
    );
  }

  return (
    <div className="booking">
      <p className="booking__location">{patient?.city ? "Showing doctors in " + patient.city + "." : "A city is needed in your profile to find local doctors."}</p>
      {specialtyName && (
        <p className="booking__specialty">
          Suggested specialty: <strong>{specialtyName}</strong>
        </p>
      )}

      {result.severe_guidance && (
        <p className="booking__severe" role="status">
          Please choose the earliest available slot.
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
                        disabled={pendingSlot !== null}
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
