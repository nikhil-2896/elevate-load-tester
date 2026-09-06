import { useState, useEffect } from "react";
import Section, { btnStyle, inputStyle } from "./components/Section";
import AnalyzeSummary from "./components/AnalyzeSummary";
import JobResultSummary from "./components/JobResultSummary";
import CompareView from "./components/CompareView";
import WebsiteLoadTestSection from "./components/WebsiteLoadTestSection";
import LoadTestConfig from "./components/LoadTestConfig";
import { colors, font, space } from "./theme";

const BASE = "https://pig-way-gamecube-shared.trycloudflare.com";

export default function App() {
  const [url, setUrl] = useState("https://httpbin.org/post");
  const [analyzeResult, setAnalyzeResult] = useState(null);
  const [isApi, setIsApi] = useState(false);
  const [isWebsite, setIsWebsite] = useState(false);
  const [sitemapRaw, setSitemapRaw] = useState(null);
  const [showRawAnalyze, setShowRawAnalyze] = useState(false);

  const [sampleInputText, setSampleInputText] = useState(
    '{"username": "john_doe", "age": 25}'
  );
  const [sampleInput, setSampleInput] = useState(null);
  const [cases, setCases] = useState([]);
  const [selected, setSelected] = useState({});

  const [testUsers, setTestUsers] = useState(3);
  const [testSpawnRate, setTestSpawnRate] = useState(1);
  const [testDuration, setTestDuration] = useState(10);

  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [jobResult, setJobResult] = useState(null);
  const [showRawJob, setShowRawJob] = useState(false);
  const [websitePathsUsed, setWebsitePathsUsed] = useState(null);

  const [jobHistory, setJobHistory] = useState([]);
  const [compareIdA, setCompareIdA] = useState("");
  const [compareIdB, setCompareIdB] = useState("");
  const [compareResult, setCompareResult] = useState(null);

  const [error, setError] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [startingWebsiteTest, setStartingWebsiteTest] = useState(false);

  useEffect(() => {
    refreshJobHistory();
  }, []);

  async function refreshJobHistory() {
    try {
      const resp = await fetch(`${BASE}/api/jobs`);
      const data = await resp.json();
      setJobHistory(data.jobs || []);
    } catch {
      // silent — history is a nice-to-have, don't block the main flow on it
    }
  }

  async function analyzeUrl() {
    setError(null);
    setAnalyzing(true);
    setAnalyzeResult(null);
    setSitemapRaw(null);
    try {
      const resp = await fetch(`${BASE}/api/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const data = await resp.json();
      setAnalyzeResult(data);

      const classification = data.type_detection?.classification;
      setIsApi(resp.ok && classification === "api");
      setIsWebsite(resp.ok && classification === "website");
      if (data.sitemap?.raw) {
        setSitemapRaw(data.sitemap.raw);
      }

      if (!resp.ok) {
        setError(data.error || "Could not reach or analyze that URL");
      }
    } catch (err) {
      setError(`${err.message} (Is the Flask server running on port 5000?)`);
    } finally {
      setAnalyzing(false);
    }
  }

  async function generateEdgeCases() {
    setError(null);
    let parsed;
    try {
      parsed = JSON.parse(sampleInputText);
    } catch {
      setError("Sample input must be valid JSON");
      return;
    }
    setSampleInput(parsed);

    const resp = await fetch(`${BASE}/api/generate-edge-cases`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_input: parsed }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      setError(JSON.stringify(data));
      return;
    }
    setCases(data.cases);
    const defaults = {};
    data.cases.forEach((c) => (defaults[c.label] = true));
    setSelected(defaults);
  }

  function toggleCase(label) {
    setSelected((prev) => ({ ...prev, [label]: !prev[label] }));
  }

  async function confirmAndStart() {
    setError(null);
    const selectedLabels = Object.keys(selected).filter((l) => selected[l]);
    if (selectedLabels.length === 0) {
      setError("Select at least one edge case");
      return;
    }

    const confirmResp = await fetch(`${BASE}/api/confirm-selection`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_input: sampleInput, selected_labels: selectedLabels }),
    });
    const confirmData = await confirmResp.json();
    if (!confirmResp.ok) {
      setError(JSON.stringify(confirmData));
      return;
    }

    const startResp = await fetch(`${BASE}/api/start-load-test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        confirmed_cases: confirmData.confirmed_cases,
        users: testUsers,
        spawn_rate: testSpawnRate,
        duration_seconds: testDuration,
      }),
    });
    const startData = await startResp.json();
    if (!startResp.ok) {
      setError(JSON.stringify(startData));
      return;
    }

    setWebsitePathsUsed(null);
    setJobId(startData.job_id);
    setJobStatus("queued");
    setJobResult(null);
    pollStatus(startData.job_id);
  }

  async function startWebsiteLoadTest() {
    setError(null);
    setStartingWebsiteTest(true);
    try {
      const resp = await fetch(`${BASE}/api/start-website-load-test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          sitemap_raw: sitemapRaw,
          users: testUsers,
          spawn_rate: testSpawnRate,
          duration_seconds: testDuration,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setError(data.error || "Could not start website load test");
        return;
      }

      setWebsitePathsUsed(data.paths_used || []);
      setJobId(data.job_id);
      setJobStatus("queued");
      setJobResult(null);
      pollStatus(data.job_id);
    } finally {
      setStartingWebsiteTest(false);
    }
  }

  function pollStatus(id) {
    const poll = async () => {
      const resp = await fetch(`${BASE}/api/load-test-status/${id}`);
      const data = await resp.json();
      setJobStatus(data.status);

      if (["completed", "failed", "timeout"].includes(data.status)) {
        setJobResult(data);
        refreshJobHistory();
        return;
      }
      setTimeout(poll, 2000);
    };
    poll();
  }

  async function runComparison() {
    setError(null);
    setCompareResult(null);
    if (!compareIdA || !compareIdB) {
      setError("Pick two runs to compare");
      return;
    }
    const resp = await fetch(`${BASE}/api/compare-jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id_a: compareIdA, job_id_b: compareIdB }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      setError(data.error || "Could not compare those runs");
      return;
    }
    setCompareResult(data);
  }

  const statusColors = {
    queued: colors.textMuted,
    running: colors.warning,
    completed: colors.success,
    failed: colors.danger,
    timeout: colors.danger,
  };
  const statusColor = statusColors[jobStatus] || colors.textMuted;

  return (
    <div
      style={{
        fontFamily: font.sans,
        maxWidth: 720,
        margin: "0 auto",
        padding: `${space.xxl}px ${space.xl}px`,
        color: colors.text,
      }}
    >
      <h1 style={{ fontSize: 28, fontWeight: 700, letterSpacing: "-0.02em", marginBottom: space.xs }}>
        Elevate Load Tester
      </h1>
      <p style={{ color: colors.textMuted, fontSize: 14, marginTop: 0, marginBottom: space.xl }}>
        Analyze a target, generate edge cases or crawl its pages, then run an async load test.
      </p>

      {error && (
        <div
          style={{
            background: "rgba(248, 81, 73, 0.1)",
            border: `1px solid ${colors.danger}`,
            color: colors.danger,
            padding: space.md,
            borderRadius: 8,
            marginBottom: space.lg,
            fontSize: 13.5,
          }}
        >
          {error}
        </div>
      )}

      <Section title="1. Enter target">
        <input
          style={inputStyle}
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com/api/endpoint"
        />
        <button onClick={analyzeUrl} style={btnStyle} disabled={analyzing}>
          {analyzing ? "Analyzing…" : "Analyze"}
        </button>

        {analyzeResult && (
          <AnalyzeSummary
            data={analyzeResult}
            showRaw={showRawAnalyze}
            onToggleRaw={() => setShowRawAnalyze((v) => !v)}
          />
        )}

        {isWebsite && (
          <>
            <LoadTestConfig
              users={testUsers}
              spawnRate={testSpawnRate}
              duration={testDuration}
              onUsersChange={setTestUsers}
              onSpawnRateChange={setTestSpawnRate}
              onDurationChange={setTestDuration}
            />
            <WebsiteLoadTestSection
              sitemapRaw={sitemapRaw}
              onStart={startWebsiteLoadTest}
              starting={startingWebsiteTest}
            />
          </>
        )}
      </Section>

      {isApi && (
        <Section title="2. Sample input for API targets">
          <p style={{ color: colors.textMuted, fontSize: 13.5, marginTop: 0 }}>
            Paste a sample JSON body this API expects
          </p>
          <textarea
            rows={4}
            style={{ ...inputStyle, resize: "vertical" }}
            value={sampleInputText}
            onChange={(e) => setSampleInputText(e.target.value)}
          />
          <button onClick={generateEdgeCases} style={btnStyle}>Generate edge cases</button>
        </Section>
      )}

      {cases.length > 0 && (
        <Section title="3. Select edge cases">
          <div
            style={{
              maxHeight: 300,
              overflowY: "auto",
              border: `1px solid ${colors.border}`,
              borderRadius: 8,
              padding: space.md,
              background: colors.bg,
            }}
          >
            {cases.map((c) => (
              <label
                key={c.label}
                style={{ display: "block", padding: "6px 4px", fontSize: 13.5, cursor: "pointer" }}
              >
                <input
                  type="checkbox"
                  checked={!!selected[c.label]}
                  onChange={() => toggleCase(c.label)}
                  style={{ marginRight: 8 }}
                />
                <span style={{ color: colors.accent, fontFamily: font.mono, fontSize: 11.5 }}>
                  [{c.category}]
                </span>{" "}
                <span style={{ color: colors.text }}>{c.description}</span>
              </label>
            ))}
          </div>

          <LoadTestConfig
            users={testUsers}
            spawnRate={testSpawnRate}
            duration={testDuration}
            onUsersChange={setTestUsers}
            onSpawnRateChange={setTestSpawnRate}
            onDurationChange={setTestDuration}
          />

          <button onClick={confirmAndStart} style={btnStyle}>
            Confirm selection and start load test
          </button>
        </Section>
      )}

      {jobId && (
        <Section title="4. Load test status">
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5, marginBottom: space.sm }}>
            <span style={{ color: colors.textMuted }}>
              Job <span style={{ fontFamily: font.mono, color: colors.text }}>{jobId}</span>
            </span>
            <span style={{ color: statusColor, fontWeight: 600, textTransform: "capitalize" }}>
              {jobStatus}
            </span>
          </div>
          {websitePathsUsed && (
            <p style={{ fontSize: 12.5, color: colors.textMuted, fontFamily: font.mono }}>
              Pages tested: {websitePathsUsed.join(", ")}
            </p>
          )}

          {jobResult && (
            <JobResultSummary
              data={jobResult}
              showRaw={showRawJob}
              onToggleRaw={() => setShowRawJob((v) => !v)}
            />
          )}
        </Section>
      )}

      <Section title="5. Compare past runs">
        {jobHistory.length === 0 ? (
          <p style={{ color: colors.textMuted, fontSize: 13.5 }}>
            No completed runs yet — run a load test above first.
          </p>
        ) : (
          <>
            <div style={{ display: "flex", gap: space.sm, marginBottom: space.md }}>
              <select
                style={{ ...inputStyle, flex: 1, fontFamily: font.sans }}
                value={compareIdA}
                onChange={(e) => setCompareIdA(e.target.value)}
              >
                <option value="">— Run A —</option>
                {jobHistory.map((j) => (
                  <option key={j.job_id} value={j.job_id}>
                    {j.target_url} · {j.users}u · {j.status} · {j.created_at}
                  </option>
                ))}
              </select>
              <select
                style={{ ...inputStyle, flex: 1, fontFamily: font.sans }}
                value={compareIdB}
                onChange={(e) => setCompareIdB(e.target.value)}
              >
                <option value="">— Run B —</option>
                {jobHistory.map((j) => (
                  <option key={j.job_id} value={j.job_id}>
                    {j.target_url} · {j.users}u · {j.status} · {j.created_at}
                  </option>
                ))}
              </select>
            </div>
            <button onClick={runComparison} style={btnStyle}>Compare</button>
            <button
              onClick={refreshJobHistory}
              style={{ ...btnStyle, background: "transparent", color: colors.accent, marginLeft: space.sm, boxShadow: "none" }}
            >
              Refresh list
            </button>

            {compareResult && <CompareView jobA={compareResult.job_a} jobB={compareResult.job_b} />}
          </>
        )}
      </Section>
    </div>
  );
}