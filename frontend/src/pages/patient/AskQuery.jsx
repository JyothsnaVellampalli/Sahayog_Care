import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { askQuery, fetchChatHistory } from "../../api.js";
import { usePatientAuth } from "../../auth/PatientAuth.jsx";
import "./AskQuery.css";

const REFERENCE_LABELS = { symptom: "Symptoms", soap: "Visit summary", report: "Report" };

function ReferenceChip({ reference }) {
  const label = REFERENCE_LABELS[reference.chunk_type] || "Record";
  const detail = reference.section ? `${label} · ${reference.section}` : label;
  if (!reference.appointment_id) return <span className="askq__chip">{detail}</span>;
  return (
    <Link className="askq__chip askq__chip--link" to={`/patient/my-appointments/${reference.appointment_id}`}>
      {detail}
    </Link>
  );
}

function Turn({ turn }) {
  const isPatient = turn.role === "patient";
  return (
    <li>
      <div className={"askq__row" + (isPatient ? " askq__row--patient" : " askq__row--assistant")}>
        <div className="askq__row-top">
          <span className="askq__row-speaker">{isPatient ? "You" : "Assistant"}</span>
        </div>
        {isPatient ? (
          <p className="askq__row-text">{turn.content}</p>
        ) : (
          <div className="askq__row-text askq__markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.content}</ReactMarkdown>
          </div>
        )}
        {turn.references?.length > 0 && (
          <div className="askq__chips">
            {turn.references.map((r) => (
              <ReferenceChip key={r.chunk_id} reference={r} />
            ))}
          </div>
        )}
      </div>
    </li>
  );
}

export default function AskQuery() {
  const { patient, accessToken } = usePatientAuth();
  const [turns, setTurns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState(null);
  const listEndRef = useRef(null);

  useEffect(() => {
    let active = true;
    fetchChatHistory(patient.id, accessToken)
      .then((data) => {
        if (active) setTurns((data.history || []).map((t) => ({ ...t })));
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
  }, [patient.id, accessToken]);

  useEffect(() => {
    listEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [turns, sending]);

  async function handleSubmit(event) {
    event.preventDefault();
    const text = message.trim();
    if (!text || sending) return;
    setSendError(null);
    setTurns((prev) => [...prev, { role: "patient", content: text }]);
    setMessage("");
    setSending(true);
    try {
      const result = await askQuery(patient.id, text, accessToken);
      setTurns((prev) => [...prev, { role: "assistant", content: result.reply, references: result.references }]);
    } catch (err) {
      setSendError(err.message);
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="askq">
      <div className="askq__header">
        <h1 className="askq__heading">Ask your query</h1>
        <p className="askq__intro">
          Ask about your past visits, symptoms or reports. Answers are based only on your own records.
        </p>
      </div>

      {loading && <p role="status">Loading your conversation...</p>}
      {loadError && (
        <div role="alert">
          <p>{loadError}</p>
        </div>
      )}

      {!loading && (
        <div className="askq__panel">
          <ol className="askq__rows" aria-live="polite">
            {turns.length === 0 && !sending && (
              <li className="askq__empty">
                Ask something like "What did the doctor say at my last visit?"
              </li>
            )}
            {turns.map((turn, index) => (
              <Turn key={index} turn={turn} />
            ))}
            {sending && (
              <li>
                <div className="askq__row askq__row--assistant">
                  <p className="askq__row-text" role="status">
                    Thinking...
                  </p>
                </div>
              </li>
            )}
            <li aria-hidden="true" ref={listEndRef} />
          </ol>

          {sendError && (
            <div role="alert" className="askq__error">
              <p>{sendError}</p>
            </div>
          )}

          <form className="askq__composer" onSubmit={handleSubmit}>
            <label className="sr-only" htmlFor="askq-input">
              Type your question
            </label>
            <input
              id="askq-input"
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Type your question..."
              maxLength={1000}
              disabled={sending}
            />
            <button className="btn btn--primary" type="submit" disabled={sending || !message.trim()}>
              {sending ? "Sending..." : "Send"}
            </button>
          </form>
        </div>
      )}
    </section>
  );
}
