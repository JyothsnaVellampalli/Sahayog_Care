/**
 * Shared presentation helpers for the doctor consultation screens (Phase 2.1).
 * Keeps severity/status -> label + pill-class mapping in one place so the list
 * and the detail view stay consistent.
 */

// Severity uses the same triage categories as the booking flow:
// Emergency / Severe / Normal. Keep this the single source for the doctor side.
export const SEVERITY_META = {
  Emergency: {
    label: "Emergency",
    pill: "pill--danger",
    color: "var(--color-danger)",
  },
  Severe: {
    label: "Severe",
    pill: "pill--warning",
    color: "var(--color-warning)",
  },
  Normal: {
    label: "Normal",
    pill: "pill--success",
    color: "var(--color-success)",
  },
};

// Fallback when a consultation has no severity set yet.
export const SEVERITY_FALLBACK = {
  label: "Unassessed",
  pill: "pill--neutral",
  color: "var(--color-neutral)",
};

export const STATUS_META = {
  EMERGENCY_PENDING: { label: "Awaiting care team", pill: "pill--danger" },
  NO_SHOW: { label: "No show", pill: "pill--neutral" },
  SCHEDULED: { label: "Scheduled", pill: "pill--neutral" },
  IN_PROGRESS: { label: "In progress", pill: "pill--warning" },
  COMPLETED: { label: "Completed", pill: "pill--success" },
  CANCELLED: { label: "Cancelled", pill: "pill--neutral" },
};

/** Format an ISO datetime as a local "h:mm AM/PM" time, or a dash if missing. */
export function formatSlotTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** "Ravi Kumar · 54 / M" style line; omits missing parts gracefully. */
export function personLine(name, age, gender) {
  const parts = [];
  if (age != null && gender) parts.push(`${age} / ${gender}`);
  else if (age != null) parts.push(String(age));
  else if (gender) parts.push(gender);
  return parts.length ? `${name || "Patient"} · ${parts.join(" ")}` : name || "Patient";
}
