import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import { PatientAuthProvider } from "./auth/PatientAuth.jsx";
import { DoctorAuthProvider } from "./auth/DoctorAuth.jsx";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <PatientAuthProvider>
        <DoctorAuthProvider>
          <App />
        </DoctorAuthProvider>
      </PatientAuthProvider>
    </BrowserRouter>
  </StrictMode>
);
