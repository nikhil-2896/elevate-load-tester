import { useEffect, useRef, useState } from "react";
import Section, { btnStyle, inputStyle, preStyle } from "./Section";
import { colors, font, space } from "../theme";

const STATUS_COLOR = {
  pass: colors.success,
  warn: colors.warning,
  fail: colors.danger,
  error: "#A371F7",
  skipped: colors.textMuted,
};
const ORDER = { error: 0, fail: 1, warn: 2, pass: 3, skipped: 4 };

const EXAMPLE_OPTIONS = `{
  "error_handling": {
    "endpoints": [
      { "method": "POST", "path": "/items", "body": { "name": "widget" } }
    ]
  },
  "rate_limiting": { "endpoint": { "method": "GET", "path": "/" } }
}`;

function Badge({ status }) {
  return (
    <span
      style={{
        background: STATUS_COLOR[status] || colors.textMuted,
        color: "#0F1419",
        borderRadius: 4,
        padding: "1px 8px",
        fontSize: 11.5,
        fontWeight: 700,
        textTransform: "uppercase",
        marginRight: space.sm,
      }}
    >
      {status}
    </span>
  );
}

function Finding({ f }) {
  const [open, setOpen] = useState(false);
  const hasMore = f.fix_hint || (f.evidence && Object.keys(f.evidence).length > 0);
  return (
    <div style={{ borderTop: `1px solid ${colors.borderSubtle}`, padding: `${space.sm}px 0` }}>
      <div style={{ display: "flex", alignItems: "baseline", flexWrap: "wrap" }}>
        <Badge status={f.status} />
        <code style={{ color: colors.textMuted, fontSize: 12, marginRight: space.sm }}>{f.check_id}</code>
        <strong style={{ fontSize: 13.5 }}>{f.title}</strong>
        {hasMore && (
          <button
            onClick={() => setOpen((v) => !v)}
            style={{ marginLeft: "auto", background: "none", border: "none", color: colors.accent, cursor: "pointer", fontSize: 12.5 }}
          >
            {open ? "hide" : "details"}
          </button>
        )}
      </div>
      <div style={{ color: colors.textMuted, fontSize: 13, marginTop: 2 }}>{f.detail}</div>
      {open && (
        <>
          {f.fix_hint && <div style={{ color: colors.success, fontSize: 13, marginTop: 4 }}>Fix: {f.fix_hint}</div>}
          {f.evidence && Object.keys(f.evidence).length > 0 && (
            <pre style={preStyle}>{JSON.stringify(f.evidence, null, 2)}</pre>
          )}
        </>
      )}
    </div>
  );
}

function Results({ run, base }) {
  const counts = {};
  run.results.forEach((r) => r.findings.forEach((f) => (counts[f.status] = (counts[f.status] || 0) + 1)));
  const verdict = run.verdict || (run.status === "failed" ? "error" : null);
  return (
    <>
      <div
        style={{
          background: verdict ? STATUS_COLOR[verdict] : colors.surfaceRaised,
          color: verdict ? "#0F1419" : colors.text,
          borderRadius: 8,
          padding: space.lg,
          marginBottom: space.md,
          fontWeight: 600,
        }}
      >
        {verdict ? `Overall verdict: ${verdict.toUpperCase()}` : `Running… ${run.results.length} module(s) finished`}
        <span style={{ fontWeight: 400, marginLeft: space.md, fontSize: 13 }}>
          {Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(" · ")}
        </span>
      </div>
      {run.results.map((r) => (
        <div key={r.module} style={{ border: `1px solid ${colors.border}`, borderRadius: 8, padding: space.md, marginBottom: space.md }}>
          <div style={{ display: "flex", alignItems: "center" }}>
            <Badge status={r.status} />
            <strong>{r.module}</strong>
            <span style={{ marginLeft: "auto", color: colors.textMuted, fontSize: 12 }}>{r.duration_s.toFixed(1)}s</span>
          </div>
          {Object.keys(r.metrics || {}).length > 0 && (
            <div style={{ color: colors.textMuted, fontSize: 12, fontFamily: font.mono, margin: `${space.xs}px 0` }}>
              {Object.entries(r.metrics).map(([k, v]) => `${k}=${v}`).join("  ")}
            </div>
          )}
          {[...r.findings].sort((a, b) => ORDER[a.status] - ORDER[b.status]).map((f) => (
            <Finding key={f.check_id + f.title} f={f} />
          ))}
        </div>
      ))}
      {run.status === "done" && (
        <a href={`${base}/api/v2/runs/${run.run_id}/report.html`} target="_blank" rel="noreferrer" style={{ color: colors.accent, fontSize: 14 }}>
          Open printable report ↗
        </a>
      )}
    </>
  );
}

export default function TestPlatform({ base }) {
  const [url, setUrl] = useState("");
  const [openapiUrl, setOpenapiUrl] = useState("");
  const [token, setToken] = useState("");
  const [criteriaList, setCriteriaList] = useState([]);
  const [chosen, setChosen] = useState({});
  const [optionsText, setOptionsText] = useState("");
  const [plan, setPlan] = useState(null);
  const [ownership, setOwnership] = useState(null);
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);

  useEffect(() => {
    fetch(`${base}/api/v2/criteria`)
      .then((r) => r.json())
      .then(setCriteriaList)
      .catch(() => setError("Could not reach the backend. Is it running, and is VITE_API_BASE correct?"));
    return () => clearTimeout(timer.current);
  }, [base]);

  const selectedCriteria = Object.keys(chosen).filter((k) => chosen[k]);

  function body() {
    let options = {};
    if (optionsText.trim()) options = JSON.parse(optionsText);
    return JSON.stringify({
      url: url.trim(),
      openapi_url: openapiUrl.trim(),
      auth_token: token,
      criteria: selectedCriteria,
      options,
    });
  }

  async function post(path, payload) {
    const resp = await fetch(`${base}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || `Request failed (${resp.status})`);
    return data;
  }

  async function guarded(fn) {
    setError(null);
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof SyntaxError ? "The options box is not valid JSON." : e.message);
    } finally {
      setBusy(false);
    }
  }

  const previewPlan = () => guarded(async () => setPlan(await post("/api/v2/plan", body())));

  const getToken = () =>
    guarded(async () => setOwnership({ ...(await post("/api/v2/ownership/token", JSON.stringify({ url: url.trim() }))), verified: null }));

  const checkOwnership = () =>
    guarded(async () => {
      const r = await post("/api/v2/ownership/verify", JSON.stringify({ url: url.trim() }));
      setOwnership((o) => ({ ...o, verified: r.verified }));
      if (r.verified) setPlan(await post("/api/v2/plan", body()));
    });

  const startRun = () =>
    guarded(async () => {
      clearTimeout(timer.current);
      setRun(null);
      const started = await post("/api/v2/runs", body());
      setPlan({ ownership_verified: plan?.ownership_verified, selected: started.selected, skipped: started.skipped });
      const poll = async () => {
        const data = await (await fetch(`${base}/api/v2/runs/${started.run_id}`)).json();
        setRun(data);
        if (data.status !== "done" && data.status !== "failed") timer.current = setTimeout(poll, 1500);
      };
      poll();
    });

  const needsOwnership = plan?.skipped?.some((s) => s.reason.includes("ownership"));
  const canRun = url.trim() && selectedCriteria.length > 0 && !busy;
  const running = run && run.status !== "done" && run.status !== "failed";

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: `${space.xl}px ${space.xl}px ${space.xxl}px` }}>
      <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-0.02em", marginBottom: space.xs }}>
        Elevate Test Platform
      </h1>
      <p style={{ color: colors.textMuted, fontSize: 14, marginTop: 0 }}>
        Choose what you want checked. The platform picks the right tests, runs them and reports the results.
      </p>

      {error && (
        <div style={{ background: "rgba(248, 81, 73, 0.1)", border: `1px solid ${colors.danger}`, color: colors.danger, padding: space.md, borderRadius: 8, fontSize: 13.5 }}>
          {error}
        </div>
      )}

      <Section title="1. Target">
        <input style={inputStyle} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://your-api.example.com" />
        <input style={{ ...inputStyle, marginTop: space.sm }} value={openapiUrl} onChange={(e) => setOpenapiUrl(e.target.value)} placeholder="OpenAPI JSON URL (optional, enables contract tests)" />
        <input style={{ ...inputStyle, marginTop: space.sm }} type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Bearer token (optional, enables auth checks; never stored)" />
      </Section>

      <Section title="2. What do you want to test?">
        {criteriaList.map((c) => (
          <label key={c.id} style={{ display: "flex", gap: space.sm, padding: `${space.xs}px 0`, cursor: "pointer", fontSize: 14 }}>
            <input type="checkbox" checked={!!chosen[c.id]} onChange={(e) => setChosen({ ...chosen, [c.id]: e.target.checked })} />
            <span>
              <strong>{c.id}</strong> <span style={{ color: colors.textMuted }}>- {c.label}</span>
            </span>
          </label>
        ))}
        <details style={{ marginTop: space.md }}>
          <summary style={{ cursor: "pointer", color: colors.accent, fontSize: 13.5 }}>Advanced: options per module (JSON)</summary>
          <textarea rows={8} style={{ ...inputStyle, marginTop: space.sm, resize: "vertical" }} value={optionsText} onChange={(e) => setOptionsText(e.target.value)} placeholder={EXAMPLE_OPTIONS} />
        </details>
        <button style={btnStyle} onClick={previewPlan} disabled={!canRun}>Preview plan</button>
      </Section>

      {plan && (
        <Section title="3. Plan">
          {plan.selected.length === 0 && <p style={{ color: colors.warning, marginTop: 0 }}>No test applies yet. See why below.</p>}
          {plan.selected.map((s) => (
            <div key={s.module_id} style={{ padding: `${space.xs}px 0`, fontSize: 14 }}>
              <Badge status="pass" />
              <strong>{s.module_id}</strong>
              <span style={{ color: colors.textMuted }}> - covers {s.matched_criteria.join(", ")}{s.intrusive ? " (sends bursts of requests)" : ""}</span>
            </div>
          ))}
          {plan.skipped.map((s) => (
            <div key={s.module_id} style={{ padding: `${space.xs}px 0`, fontSize: 14 }}>
              <Badge status="skipped" />
              <strong>{s.module_id}</strong>
              <span style={{ color: colors.textMuted }}> - {s.reason}</span>
            </div>
          ))}

          {needsOwnership && (
            <div style={{ marginTop: space.md, padding: space.md, border: `1px solid ${colors.border}`, borderRadius: 8, fontSize: 13.5 }}>
              <strong>Prove you own this target to unlock the load and rate-limit tests.</strong>
              {!ownership && (
                <div>
                  <button style={btnStyle} onClick={getToken} disabled={busy}>Get verification token</button>
                </div>
              )}
              {ownership && (
                <div style={{ marginTop: space.sm }}>
                  Serve this exact text at <code>{ownership.path}</code> on your site:
                  <pre style={preStyle}>{ownership.token}</pre>
                  <button style={btnStyle} onClick={checkOwnership} disabled={busy}>Check now</button>
                  {ownership.verified === false && <span style={{ color: colors.danger, marginLeft: space.md }}>Not found yet.</span>}
                  {ownership.verified === true && <span style={{ color: colors.success, marginLeft: space.md }}>Verified.</span>}
                </div>
              )}
            </div>
          )}
          <button style={btnStyle} onClick={startRun} disabled={!canRun || plan.selected.length === 0 || running}>
            {running ? "Running…" : "Run tests"}
          </button>
        </Section>
      )}

      {run && (
        <Section title="4. Results">
          <Results run={run} base={base} />
        </Section>
      )}
    </div>
  );
}