# Phase 1.5 - Patient UI and local doctor suggestions

## UI and routes

The patient portal now follows the desktop and mobile references in `docs/Design`, using the shared teal theme in `frontend/src/theme.css`. Landing, sign-in, registration, assessment, emergency guidance, doctor selection, slot booking, and doctor consultation flows remain available.

- `/patient/book-appointment`: searchable symptoms, keyboard-accessible severity groups, exact duration in days, notes, tab-scoped drafts, and doctor/slot selection. Booking has two keyboard-accessible tabs: Symptoms and Slot booking. Successful intake automatically opens Slot booking; returning to Symptoms preserves the form. Editing symptoms invalidates the old slot result until resubmission. Classification grades and probability bars are not displayed; urgent-care and earliest-slot guidance remain available.
- `/patient/my-appointments?filter=all|upcoming|past`: appointment history and pending emergency cases. All is the default so existing history stays visible.
- `/patient/my-appointments/:appointmentId`: symptoms, notes, signed clinical summary, text download, and follow-up booking.
- `/patient/my-appointments/:appointmentId?edit=1`: edit symptoms and notes while the appointment is still BOOKED. Starting the consultation prevents further patient edits through an atomic status condition.

Drafts are scoped to the patient and browser tab. Explicit Save draft restores the form after navigation or refresh; booking and sign-out remove the saved draft. The existing Show available slots action is retained because the patient must still choose a doctor and slot before booking.

The detail screen releases only the immutable signed SOAP snapshot of a completed visit. Unsigned drafts are not shown. The medicines panel explicitly says Under construction because there is no separate structured prescription source yet. The signed care plan remains visible; medication details are not inferred from it.

New detail GET/PUT requests require a Supabase bearer token belonging to the patient in the URL. Detail lookup and updates also constrain the appointment by patient ID. No database migration is needed beyond the existing shared-appointment and signed-consultation schema.

## Location filtering

For a patient intake, the backend reads `patients.city` from the stored profile. `doctors_with_slots` matches it against `hospitals.city` using case-insensitive equality after whitespace normalization. It filters before querying slots, retains specialty and active-doctor filtering, and keeps the existing availability ordering.

No matching city means no cross-city fallback. Missing profile location or failed profile lookup produces a clear message and no doctor suggestions. Anonymous legacy API callers retain their earlier behavior. This is city matching, not distance/geolocation matching; city aliases are not inferred.

## Accessibility and responsive behavior

Shared tokens provide readable status colors. Forms use associated labels, native radio keyboard behavior, visible focus, error/status messages, and reduced-motion support. Page navigation moves focus to the main region and updates the document title. Both portals use explicit navigation paths, including links from the doctor signature gate. Mobile navigation sits at the bottom with content padding; the appointment table becomes stacked rows.

## Verification

From `frontend`:

```sh
npm run build
npm run test:e2e
```

The Playwright suite uses installed Microsoft Edge in headless mode and starts Vite on port 5174. Its fixtures do not call production services. Seven scenarios cover booking/drafts/history/downloads at 1440, 390 and 320px, editing and unavailable records, emergency/no-slot/error states, doctor navigation and consultation consent, and sign-in/registration. Axe scans check WCAG A/AA rules and the tests assert no horizontal overflow. Screenshots are written under ignored `frontend/test-results/` for visual review.

From `backend`:

```sh
.venv/Scripts/python.exe -m pytest tests/test_intake_graph.py tests/test_location_filter.py tests/test_patient_details.py tests/test_shared_appointments.py tests/test_signed_consultation.py -q
```

33 focused backend tests pass. Live Supabase/OpenRouter integration and real microphone recording are not exercised by these fixture-based checks. Automated accessibility checks supplement, rather than replace, manual assistive-technology review.
