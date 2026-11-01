"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, money, txt, lvl } from "../../api";
import { Badge, KLASS } from "../../Badge";

export default function Results() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [sum, setSum] = useState<any>(null);
  const [fs, setFs] = useState<any[]>([]);
  const [looks, setLooks] = useState<any[]>([]);
  const [tab, setTab] = useState("all");
  const [status, setStatus] = useState("");
  const [rule, setRule] = useState("");
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      setSum(await api(`/sessions/${id}/summary`));
      setLooks(await api(`/sessions/${id}/lookalikes`));
    } catch (e: any) {
      setErr(e.message);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const p = new URLSearchParams();
    if (tab !== "all") p.set("klass", tab);
    if (status) p.set("status", status);
    if (rule) p.set("rule", rule);
    if (q) p.set("q", q);
    api(`/sessions/${id}/findings?${p}`).then(setFs).catch((e) => setErr(e.message));
  }, [id, tab, status, rule, q, sum]);

  if (err) return <div className="note err">{err}</div>;
  if (!sum) return <div className="muted">Loading...</div>;
  const t = sum.totals;
  const c = sum.counts;
  const share = sum.proposed_total ? Math.min(100, (t.confirmed_leakage / sum.proposed_total) * 100) : 0;

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h1>Leakage report</h1>
          <div className="sub">
            {sum.dataset.claims} claims · {sum.dataset.lines} invoice lines · {sum.dataset.policies} policies · {sum.dataset.payments} payments · analysed in {sum.runtime_s}s
          </div>
        </div>
        <div className="row">
          <Link className="btn sec" href={`/s/${id}/dashboard`}>Dashboard</Link>
          <a className="btn sec" href={`/api/sessions/${id}/export.csv`}>Export CSV</a>
          <button className="sec" onClick={() => window.print()}>Export PDF</button>
          <Link className="btn sec" href={`/s/${id}/patterns`}>Cross-claim patterns</Link>
          <Link className="btn sec" href={`/s/${id}/audit`}>Audit trail ({sum.audit_count})</Link>
        </div>
      </div>

      <div className="note info">
        <b>How to read this page.</b> The four boxes are money totals. <span className="red">Confirmed</span> = clear rule breaks (counted once even if several rules hit the same charge).{" "}
        <span className="amber">Potential</span> = suspicious but could be legitimate, so a person must decide. <span className="violet">At risk</span> = we cannot judge because evidence is missing.
        Click any row in the table to see the proof and decide.
      </div>
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <div className="card kpi"><div className="l">Confirmed leakage</div><div className="v red">{money(t.confirmed_leakage)}</div><div className="n">money that should not be paid · counted once · {c.confirmed} findings · {share.toFixed(1)}% of proposed payout</div></div>
        <div className="card kpi"><div className="l">Potential (suspicious)</div><div className="v amber">{money(t.potential_leakage)}</div><div className="n">{c.suspicious} patterns need a human decision</div></div>
        <div className="card kpi"><div className="l">At risk · evidence missing</div><div className="v violet">{money(t.at_risk_pending_clarification)}</div><div className="n">{c.clarification} claims: ask for the missing document/info</div></div>
        <div className="card kpi"><div className="l">Under-settlement</div><div className="v">{money(t.under_settlement)}</div><div className="n">{c.lookalike} similar-looking claims judged legitimate (not flagged)</div></div>
      </div>

      {(sum.notes ?? []).map((n: any, i: number) => <div key={i} className={lvl(n)}>{txt(n)}</div>)}
      {(sum.failed_files ?? []).map((f: any, i: number) => <div key={`f${i}`} className="note err">Could not read {f.file ?? f.name ?? ""}: {f.reason ?? f.error ?? txt(f)}</div>)}
      {sum.not_run?.length > 0 && sum.not_run.map((n: any, i: number) => <div key={`n${i}`} className="note">Check not run: {txt(n)}</div>)}
      {sum.quarantine_count > 0 && (
        <details className="card">
          <summary>{sum.quarantine_count} row(s) quarantined (excluded from analysis, not silently dropped)</summary>
          <table><tbody>
            {sum.quarantine.slice(0, 50).map((r: any, i: number) => <tr key={i}><td className="mono">{txt(r.source ?? r.src ?? "")}</td><td>{txt(r.reason)}</td></tr>)}
          </tbody></table>
        </details>
      )}

      <div className="grid" style={{ gridTemplateColumns: "2fr 1fr" }}>
        <div className="card">
          <h2>Findings</h2>
          <div className="muted" style={{ marginBottom: 8 }}>Each row is one issue found. Filter by type, status or rule, then click a row to open the evidence and decide.</div>
          <div className="tabs">
            {Object.keys(KLASS).map((k) => <div key={k} className={`tab ${tab === k ? "on" : ""}`} onClick={() => setTab(k)}>{KLASS[k]}</div>)}
          </div>
          <div className="row" style={{ marginBottom: 10 }}>
            <input type="text" placeholder="Search claim, invoice, text..." value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 280 }} />
            <select style={{ width: 150 }} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Any status</option><option value="open">Open</option><option value="confirmed">Confirmed</option><option value="corrected">Corrected</option><option value="dismissed">Dismissed</option>
            </select>
            <select style={{ width: 200 }} value={rule} onChange={(e) => setRule(e.target.value)}>
              <option value="">All rules</option>
              {sum.rules.filter((r: any) => r.hits > 0).map((r: any) => <option key={r.id} value={r.id}>{r.id} · {r.name}</option>)}
            </select>
          </div>
          <table>
            <thead><tr><th>ID</th><th>Finding</th><th>Class</th><th>Status</th><th className="num">Amount</th><th></th></tr></thead>
            <tbody>
              {fs.map((f) => (
                <tr key={f.id} className="click" onClick={() => router.push(`/s/${id}/f/${f.id}`)}>
                  <td className="mono">{f.id}</td>
                  <td><b>{f.rule_id}</b> {f.title}<div className="muted">{(f.claim_ids ?? []).join(", ")}</div></td>
                  <td><Badge k={f.klass} /></td>
                  <td><span className={`badge b-${f.status}`}>{f.status}</span></td>
                  <td className="num">{f.klass === "clarification" ? <span className="violet">{money(f.at_risk)}</span> : money(f.impact ?? f.amount)}</td>
                  <td><button className="sec" onClick={(e) => { e.stopPropagation(); router.push(`/s/${id}/f/${f.id}`); }}>View</button></td>
                </tr>
              ))}
              {!fs.length && <tr><td colSpan={6} className="muted">No findings match.</td></tr>}
            </tbody>
          </table>
        </div>

        <div>
          <div className="card">
            <h2>Rules that fired</h2>
            <div className="muted">Which checks found something, how many times, and the amount.</div>
            <table>
              <tbody>
                {sum.rules.filter((r: any) => r.hits > 0).map((r: any) => (
                  <tr key={r.id}><td><b>{r.id}</b> <span className="muted">{r.source === "default" ? "" : "· custom"}</span><div className="muted">{r.name}</div></td><td className="num">{r.hits}<div className="muted">{money(r.amount)}</div></td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card">
            <h2>Top claims by leakage</h2>
            <div className="muted">Click a claim to see what it should have paid.</div>
            <table>
              <tbody>
                {sum.top_claims.slice(0, 8).map((c: any) => (
                  <tr key={c.claim_id} className="click" onClick={() => router.push(`/s/${id}/c/${c.claim_id}`)}>
                    <td>{c.claim_id}</td><td className="num red">{money(c.leakage)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {looks.length > 0 && (
        <div className="card">
          <h2>Legitimate lookalikes (not flagged)</h2>
          {looks.map((l: any, i: number) => (
            <div key={i} className="note info">
              {l.title} — claims {(l.claim_ids ?? []).join(", ")}, {money(l.amount_each)} each. Distinct dates and sessions suggest separate valid services.
            </div>
          ))}
        </div>
      )}
    </>
  );
}
