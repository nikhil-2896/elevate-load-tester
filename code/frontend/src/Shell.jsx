import { useState } from "react";
import App from "./App";
import TestPlatform from "./components/TestPlatform";
import { BASE, getApiKey, setApiKey } from "./config";
import { colors, font, space } from "./theme";

const TABS = [
  { id: "platform", label: "Test Platform" },
  { id: "load", label: "Load Tester" },
];

export default function Shell() {
  const [tab, setTab] = useState("platform");
  const [key, setKey] = useState(getApiKey());
  const [keyVersion, setKeyVersion] = useState(0);

  function applyKey() {
    setApiKey(key.trim());
    setKeyVersion((v) => v + 1); // makes the Test Platform tab reload with the new key
  }

  return (
    <div style={{ fontFamily: font.sans, color: colors.text }}>
      <nav
        style={{
          display: "flex",
          gap: space.sm,
          justifyContent: "center",
          alignItems: "center",
          flexWrap: "wrap",
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
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && applyKey()}
          placeholder="API key (if the server needs one)"
          style={{
            marginLeft: space.md,
            padding: "8px 12px",
            borderRadius: 7,
            border: `1px solid ${colors.border}`,
            background: colors.surface,
            color: colors.text,
            fontSize: 13,
            width: 230,
          }}
        />
        <button
          onClick={applyKey}
          style={{
            padding: "8px 14px",
            borderRadius: 7,
            border: `1px solid ${colors.border}`,
            background: colors.surface,
            color: colors.text,
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          Set key
        </button>
      </nav>
      {tab === "platform" ? <TestPlatform base={BASE} keyVersion={keyVersion} /> : <App />}
    </div>
  );
}