"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, post, txt, lvl } from "./api";

const ROLES = ["claims", "policies", "lines", "payments", "documents"];
const FIELDS = [
  "", "claim_id", "claimed_amount", "proposed_settlement", "policy_id", "claimant_id", "provider", "claim_type", "loss_date", "claim_date",
  "invoice_no", "bank_account", "status", "description", "amount", "quantity", "unit_price", "vendor", "service_date", "category",
  "payment_id", "payment_date", "reference", "method", "doc_type", "policy_start", "policy_end", "sum_insured", "deductible", "copay_pct",
  "waiting_days", "room_limit", "exclusions", "sublimits",
];

export default function Home() {
  const router = useRouter();
  const [files, setFiles] = useState<File[]>([]);
  const [ruleFiles, setRuleFiles] = useState<File[]>([]);
  const [rulesText, setRulesText] = useState("");
  const [mode, setMode] = useState("augment");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [map, setMap] = useState<any>(null);
  const [overrides, setOverrides] = useState<any>({});
  const [drag, setDrag] = useState(false);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [tab, setTab] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);
  const ruleRef = useRef<HTMLInputElement>(null);

  async function sample(kind: string) {
    setBusy("Loading sample and analysing...");
    setErr("");
    try {
      const r = await post(`/samples/${kind}`);
      router.push(`/s/${r.session}`);
    } catch (e: any) {
      setErr(e.message);
      setBusy("");
    }
  }

  async function upload() {
    setBusy("Reading and mapping files...");
    setErr("");
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      ruleFiles.forEach((f) => fd.append("rule_files", f));
      fd.append("rules_text", rulesText);
      const r = await api("/sessions", { method: "POST", body: fd });
      setMap(r);
      setOverrides({});
      setTab(0);
      setStep(2);
    } catch (e: any) {
      setErr(e.message);
    }
    setBusy("");
  }

  async function run() {
    setBusy("Analysing claims...");
    setErr("");
    try {
      await post(`/sessions/${map.id}/run`, { overrides, mode });
      router.push(`/s/${map.id}`);
    } catch (e: any) {
      setErr(e.message);
      setBusy("");
    }
  }

  function setRoles(t: any, role: string, on: boolean) {
    const cur: string[] = overrides[t.table]?.roles ?? t.roles;
    const roles = on ? Array.from(new Set([...cur, role])) : cur.filter((r) => r !== role);
    setOverrides({ ...overrides, [t.table]: { ...overrides[t.table], roles } });
  }
  function setField(t: any, role: string, col: string, field: string) {
    const base = overrides[t.table]?.mapping?.[role] ?? t.available_mappings?.[role] ?? {};
    const m = { ...base };
    delete m[col];
    if (field) m[col] = field;
    setOverrides({ ...overrides, [t.table]: { ...overrides[t.table], mapping: { ...overrides[t.table]?.mapping, [role]: m } } });
  }

  function addFiles(list: FileList | null, rules = false) {
    if (!list) return;
    const arr = Array.from(list);
    rules ? setRuleFiles((p) => [...p, ...arr]) : setFiles((p) => [...p, ...arr]);
  }

  return (
    <>
      <h1>Find the leakage before you pay</h1>
      <div className="sub">
        ClaimIQ checks insurance claims for money that should not be paid: duplicate invoices, charges above policy limits, excluded items, wrong settlement maths and missing documents.
      </div>
      <div className="stepper">
        {[
          ["Add data", "Upload claim files (CSV, Excel, JSON, PDF). Column names can be anything."],
          ["Check understanding", "Confirm what each file is and which column means what. Add your own rules."],
          ["Review rules", "Check the rules that will run before analysis."],
          ["Review results", "See the money at risk and Confirm, Correct or Dismiss each finding."],
        ].map(([t, d], i) => (
          <div key={i} className={`stp ${step === i + 1 ? "on" : step > i + 1 ? "done" : ""}`}>
            <span className="num">{i + 1}</span>
            <div><b>{t}</b><div className="muted">{d}</div></div>
          </div>
        ))}
      </div>
      {!map && (
        <div className="note info">
          <b>Which files?</b> Best results with: <span className="mono">claims</span> (one row per claim), <span className="mono">policies</span> (limits, deductible, co-pay),{" "}
          <span className="mono">invoice lines</span> (each charge), <span className="mono">payments</span> and <span className="mono">documents</span>. Only some of them? That works too — checks that
          need missing data are skipped and listed. No files at hand? Use a sample button below.
        </div>
      )}

      {!map && (
        <div className="grid g2">
          <div className="card">
            <h2>1. Claims data</h2>
            <div className="muted" style={{ marginBottom: 8 }}>Add one or many files at once. Nothing is analysed until you press the button below.</div>
            <div
              className={`drop ${drag ? "on" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
              onClick={() => fileRef.current?.click()}
              style={{ cursor: "pointer" }}
            >
              Drop CSV / Excel / JSON / XML / PDF / ZIP files here, or click to browse
              <input ref={fileRef} type="file" multiple hidden onChange={(e) => addFiles(e.target.files)} />
            </div>
            {files.map((f, i) => (
              <div key={i} className="row" style={{ marginTop: 6 }}>
                <span className="mono">{f.name}</span>
                <span className="muted">{(f.size / 1024).toFixed(0)} KB</span>
                <a onClick={() => setFiles(files.filter((_, j) => j !== i))} style={{ cursor: "pointer" }}>remove</a>
              </div>
            ))}
          </div>

          <div className="card">
            <h2>2. Your rules (optional)</h2>
            <div className="muted" style={{ marginBottom: 8 }}>Write rules in plain English, one per line, or attach a rules file. They are applied on top of the policy data.</div>
            <textarea
              placeholder={"Plain language or a rules file, e.g.\nRoom rent is capped at 5,000 per day\nCosmetic procedures are excluded\nCo-pay is 10%"}
              value={rulesText}
              onChange={(e) => setRulesText(e.target.value)}
            />
            <div className="row" style={{ marginTop: 8 }}>
              <button className="sec" onClick={() => ruleRef.current?.click()}>Attach rules file</button>
              <input ref={ruleRef} type="file" multiple hidden onChange={(e) => addFiles(e.target.files, true)} />
              {ruleFiles.map((f, i) => <span key={i} className="mono">{f.name}</span>)}
              <select style={{ width: 220 }} value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="augment">My rules + default checks</option>
                <option value="judge_only">My rules only</option>
              </select>
            </div>
          </div>
        </div>
      )}

      {err && <div className="note err">{err}</div>}
      {busy && <div className="note info">{busy}</div>}

      {!map && (
        <div className="row">
          <button disabled={!!busy || (!files.length && !ruleFiles.length && !rulesText.trim())} onClick={upload}>Next: check what was understood</button>
          <span className="muted">or try it instantly:</span>
          <button className="sec" disabled={!!busy} onClick={() => sample("with_rules")}>Load sample (with my rules)</button>
          <button className="sec" disabled={!!busy} onClick={() => sample("default")}>Load sample (default rules)</button>
        </div>
      )}

      {map && (
        <>
          {map.failed?.length > 0 && map.failed.map((f: any, i: number) => (
            <div key={i} className="note err">Could not read <b>{f.file ?? f.name ?? JSON.stringify(f)}</b>: {f.reason ?? f.error ?? ""}</div>
          ))}

          {step === 2 && map.tables[tab] && (() => {
            const t: any = map.tables[tab];
            const roles: string[] = overrides[t.table]?.roles ?? t.roles;
            return (
              <>
                <div className="note info">
                  <b>Check what ClaimIQ understood.</b> Each file is a tab. Pick what the file contains, then check that each column is matched to the right claim field.
                  Change a dropdown only where a column was matched wrongly.
                </div>
                <div className="tabs">
                  {map.tables.map((x: any, i: number) => (
                    <button key={x.table} className={`tab ${i === tab ? "on" : ""}`} onClick={() => setTab(i)}>{x.table}</button>
                  ))}
                </div>
                <div className="card">
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <h2>{t.table} <span className="muted">· {t.rows} rows</span></h2>
                    <div className="row">
                      <span className="muted">Treat as:</span>
                      {ROLES.map((r) => (
                        <label key={r} className="row" style={{ gap: 4 }}>
                          <input type="checkbox" checked={roles.includes(r)} onChange={(e) => setRoles(t, r, e.target.checked)} /> {r}
                        </label>
                      ))}
                    </div>
                  </div>
                  {roles.map((role) => {
                    const m: Record<string, string> = overrides[t.table]?.mapping?.[role] ?? t.available_mappings?.[role] ?? {};
                    return (
                      <details key={role} open={roles.length === 1} style={{ marginBottom: 8 }}>
                        <summary style={{ cursor: "pointer" }}><b>{role}</b> <span className="muted">{Object.keys(m).length} of {t.columns.length} columns mapped</span></summary>
                        <table>
                          <thead><tr><th>Source column</th><th>Maps to</th></tr></thead>
                          <tbody>
                            {t.columns.map((c: string) => (
                              <tr key={c}>
                                <td className="mono">{c}</td>
                                <td>
                                  <select value={m[c] ?? ""} onChange={(e) => setField(t, role, c, e.target.value)}>
                                    {Array.from(new Set([...FIELDS, m[c] ?? ""])).map((f) => <option key={f} value={f}>{f || "(ignore)"}</option>)}
                                  </select>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </details>
                    );
                  })}
                </div>
                <div className="row">
                  <button className="sec" onClick={() => { setMap(null); setStep(1); }}>Back</button>
                  <button onClick={() => setStep(3)}>Next: Review rules</button>
                </div>
              </>
            );
          })()}

          {step === 3 && (
          <>
          <div className="card">
            <h2>Your rules, as understood</h2>
            <div className="muted" style={{ marginBottom: 8 }}>These are the checks created from your text/file. Anything we could not turn into a check is flagged so nothing is silently ignored.</div>
            {map.rules?.length ? (
              <table>
                <thead><tr><th>Rule</th><th>Type</th><th>Parameters</th><th>Status</th></tr></thead>
                <tbody>
                  {map.rules.map((r: any, i: number) => (
                                    <tr key={i}><td>{r.name ?? r.id}</td><td><span className="badge">{r.type}</span></td><td className="mono">{r.params && Object.keys(r.params).length ? JSON.stringify(r.params) : r.text}</td><td><span className={`badge ${r.type === "custom" ? "b-open" : "b-confirmed"}`}>{r.type === "custom" ? "Needs review" : "Active"}</span></td></tr>
                  ))}
                </tbody>
              </table>
            ) : <div className="muted">No custom rules supplied; default checks will run.</div>}
            {map.unparsed_rules?.map((u: any, i: number) => (
              <div key={i} className="note">Not executable (shown, not silently dropped): {txt(u)}</div>
            ))}
            {map.rule_notes?.map((n: any, i: number) => <div key={i} className={lvl(n) + (lvl(n) === "note" ? " info" : "")}>{txt(n)}</div>)}
            <div className="row" style={{ marginTop: 8 }}>
              <select style={{ width: 240 }} value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="augment">My rules + default checks</option>
                <option value="judge_only">My rules only</option>
              </select>
            </div>
          </div>

          <div className="row">
            <button disabled={!!busy} onClick={run}>Run analysis (find leakage)</button>
            <button className="sec" onClick={() => setStep(2)}>Back</button>
          </div>
          </>
          )}
        </>
      )}
    </>
  );
}


