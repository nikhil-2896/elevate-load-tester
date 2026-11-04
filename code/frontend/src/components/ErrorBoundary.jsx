import { Component } from "react";

// Shows a message instead of a blank page if something unexpected breaks while drawing.
export default class ErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div style={{ maxWidth: 560, margin: "80px auto", padding: 24, textAlign: "center", color: "#E6EDF3" }}>
        <h2>Something went wrong showing this page</h2>
        <p style={{ color: "#8B949E" }}>Your test may still be running on the server. Reload the page and try again.</p>
        <button onClick={() => window.location.reload()} style={{ padding: "8px 18px", cursor: "pointer" }}>
          Reload
        </button>
      </div>
    );
  }
}