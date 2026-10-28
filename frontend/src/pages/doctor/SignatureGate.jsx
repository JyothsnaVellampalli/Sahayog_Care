import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { uploadDoctorSignature } from "../../api.js";
import { useDoctorAuth } from "../../auth/DoctorAuth.jsx";
import "./SignatureGate.css";

/**
 * Digital signature gate (Phase 2.1, design screen 1).
 *
 * A doctor must have a signature on file before opening a consultation. Accepts
 * a PNG/JPG under 500 KB, shows a preview, uploads to the backend (S3/local).
 */
const MAX_BYTES = 500 * 1024;

export default function SignatureGate() {
  const navigate = useNavigate();
  const { doctor, setHasSignature } = useDoctorAuth();
  const inputRef = useRef(null);

  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  function pickFile(f) {
    setError(null);
    if (!f) return;
    if (!["image/png", "image/jpeg"].includes(f.type)) {
      setError("Please choose a PNG or JPG image.");
      return;
    }
    if (f.size > MAX_BYTES) {
      setError("Image must be under 500 KB.");
      return;
    }
    setFile(f);
    setPreviewUrl(URL.createObjectURL(f));
  }

  async function handleSave() {
    if (!file || !doctor?.id) return;
    setBusy(true);
    setError(null);
    try {
      const res = await uploadDoctorSignature(doctor.id, file);
      if (res?.error) {
        setError(res.error);
        return;
      }
      setHasSignature(true);
      navigate("/doctor/consultations");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="siggate" aria-labelledby="siggate-title">
      <p className="siggate__flag">Action needed before your first consultation</p>
      <h1 className="siggate__title" id="siggate-title">
        Add your digital signature
      </h1>
      <p className="siggate__intro">
        Your signature is applied to every consultation note you finalize. You
        can't open a consultation until one is on file.
      </p>

      <div
        className={"siggate__drop" + (previewUrl ? " siggate__drop--has" : "")}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          pickFile(e.dataTransfer.files?.[0]);
        }}
      >
        <p className="siggate__drop-title">Drop a PNG or JPG here</p>
        <p className="siggate__drop-sub">
          or{" "}
          <button
            type="button"
            className="siggate__browse"
            onClick={() => inputRef.current?.click()}
          >
            browse files
          </button>{" "}
          · max 500 KB
        </p>
        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg"
          className="sr-only"
          onChange={(e) => pickFile(e.target.files?.[0])}
        />
      </div>

      <div className="siggate__grid">
        <div className="siggate__preview">
          <span className="siggate__preview-label">PREVIEW</span>
          {previewUrl ? (
            <img src={previewUrl} alt="Signature preview" />
          ) : (
            <span className="siggate__preview-empty">
              Your signature will appear here
            </span>
          )}
        </div>
        <div className="siggate__req">
          <p className="siggate__req-title">Requirements</p>
          <ul>
            <li>PNG or JPG</li>
            <li>Under 500 KB</li>
            <li>Dark ink on a white or transparent background</li>
            <li>Replacing it keeps past notes signed with the old one</li>
          </ul>
        </div>
      </div>

      {error && (
        <p className="siggate__error" role="alert">
          {error}
        </p>
      )}

      <div className="siggate__actions">
        <button
          className="btn btn--secondary"
          type="button"
          onClick={() => navigate("/")}
        >
          Cancel
        </button>
        <button
          className="btn btn--primary"
          type="button"
          onClick={handleSave}
          disabled={!file || busy}
        >
          {busy ? "Saving…" : "Save signature"}
        </button>
      </div>
    </section>
  );
}
