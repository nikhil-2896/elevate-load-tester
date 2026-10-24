import { useState } from "react";
import App from "./App";
import TestPlatform from "./components/TestPlatform";
import { BASE } from "./config";
import { colors, font, space } from "./theme";

const TABS = [
  { id: "platform", label: "Test Platform" },
  { id: "load", label: "Load Tester" },
];

export default function Shell() {
  const [tab, setTab] = useState("platform");
  return (
    <div style={{ fontFamily: font.sans, color: colors.text }}>
      <nav
        style={{
          display: "flex",
          gap: space.sm,
          justifyContent: "center",
          padding: `${space.lg}px ${space.lg}px 0`,
        }}
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: "8px 18px",
              borderRadius: 7,
              border: `1px solid ${tab === t.id ? colors.accent : colors.border}`,
              background: tab === t.id ? colors.accent : colors.surface,
              color: tab === t.id ? colors.bg : colors.text,
              fontWeight: 600,
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>
      {tab === "platform" ? <TestPlatform base={BASE} /> : <App />}
    </div>
  );
}