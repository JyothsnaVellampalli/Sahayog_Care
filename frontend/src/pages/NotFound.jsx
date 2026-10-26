import { Link } from "react-router-dom";

/** Simple, accessible 404 page for unknown routes. */
export default function NotFound() {
  return (
    <main
      id="main-content"
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "12px",
        padding: "24px",
        textAlign: "center",
      }}
    >
      <h1 style={{ margin: 0, fontWeight: 400 }}>Page not found</h1>
      <p style={{ color: "#5f6368", margin: 0 }}>
        The page you are looking for does not exist.
      </p>
      <Link to="/">Go to the start page</Link>
    </main>
  );
}
