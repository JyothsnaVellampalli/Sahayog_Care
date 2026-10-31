import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import LandingPage from "./pages/LandingPage.jsx";
import PatientLogin from "./pages/patient/PatientLogin.jsx";
import PatientPortal from "./pages/patient/PatientPortal.jsx";
import BookAppointment from "./pages/patient/BookAppointment.jsx";
import AppointmentDetail from "./pages/patient/AppointmentDetail.jsx";
import MyAppointments from "./pages/patient/MyAppointments.jsx";
import DoctorLogin from "./pages/doctor/DoctorLogin.jsx";
import DoctorPortal from "./pages/doctor/DoctorPortal.jsx";
import SignatureGate from "./pages/doctor/SignatureGate.jsx";
import ConsultationsList from "./pages/doctor/ConsultationsList.jsx";
import ConsultationView from "./pages/doctor/ConsultationView.jsx";
import NotFound from "./pages/NotFound.jsx";
import PharmacyApp from "./pages/pharmacy/PharmacyApp.jsx";
import { usePatientAuth } from "./auth/PatientAuth.jsx";
import { useDoctorAuth } from "./auth/DoctorAuth.jsx";

/**
 * Application routes.
 *
 *   /                            landing (profile selector)
 *   /patient/login               phone + password sign in / registration
 *   /patient                     patient portal (requires login)
 *   /patient/book-appointment    symptom intake (default)
 *   /patient/my-appointments     appointments list
 */
function RequirePatient({ children }) {
  const { isAuthenticated } = usePatientAuth();
  if (!isAuthenticated) {
    return <Navigate to="/patient/login" replace />;
  }
  return children;
}

function RequireDoctor({ children, requireSignature = false }) {
  const { isAuthenticated, doctor } = useDoctorAuth();
  if (!isAuthenticated) {
    return <Navigate to="/doctor/login" replace />;
  }
  // Consultation screens need a signature on file first.
  if (requireSignature && !doctor?.has_signature) {
    return <Navigate to="/doctor/signature" replace />;
  }
  return children;
}

export default function App() {
  const { pathname } = useLocation();
  useEffect(() => {
    const main = document.querySelector("main");
    if (main) { main.setAttribute("tabindex", "-1"); main.focus({ preventScroll: true }); }
    window.scrollTo(0, 0);
    const section = pathname.includes("my-appointments") ? "My appointments" : pathname.includes("book-appointment") ? "Book an appointment" : pathname.includes("consultations") ? "Consultations" : pathname.includes("signature") || pathname.includes("profile") ? "Digital signature" : pathname.includes("login") ? "Sign in" : "Welcome";
    document.title = `${pathname === '/pharmacist/stock' ? 'Medicine stock' : section} | Sahayog Care`;
  }, [pathname]);
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/pharmacist/*" element={<PharmacyApp />} />
      <Route path="/patient/login" element={<PatientLogin />} />

      <Route
        path="/patient"
        element={
          <RequirePatient>
            <PatientPortal />
          </RequirePatient>
        }
      >
        <Route index element={<Navigate to="book-appointment" replace />} />
        <Route path="book-appointment" element={<BookAppointment />} />
        <Route path="my-appointments" element={<MyAppointments />} />
        <Route path="my-appointments/:appointmentId" element={<AppointmentDetail />} />
      </Route>

      {/* Doctor */}
      <Route path="/doctor/login" element={<DoctorLogin />} />
      <Route
        path="/doctor/signature"
        element={
          <RequireDoctor>
            <DoctorPortal />
          </RequireDoctor>
        }
      >
        <Route index element={<SignatureGate />} />
      </Route>
      <Route
        path="/doctor"
        element={
          <RequireDoctor requireSignature>
            <DoctorPortal />
          </RequireDoctor>
        }
      >
        <Route index element={<Navigate to="consultations" replace />} />
        <Route path="consultations" element={<ConsultationsList />} />
        <Route path="consultations/:consultationId" element={<ConsultationView />} />
        <Route path="profile" element={<SignatureGate />} />
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
