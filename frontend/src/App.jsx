import { Navigate, Route, Routes } from "react-router-dom";
import LandingPage from "./pages/LandingPage.jsx";
import PatientLogin from "./pages/patient/PatientLogin.jsx";
import PatientPortal from "./pages/patient/PatientPortal.jsx";
import BookAppointment from "./pages/patient/BookAppointment.jsx";
import MyAppointments from "./pages/patient/MyAppointments.jsx";
import NotFound from "./pages/NotFound.jsx";
import { usePatientAuth } from "./auth/PatientAuth.jsx";

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

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
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
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
