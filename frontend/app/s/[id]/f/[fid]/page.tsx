"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, money, post } from "../../../../api";
import { Badge } from "../../../../Badge";

export default function FindingPage() {
  const { id, fid } = useParams<{ id: string; fid: string }>();
  const [f, setF] = useState<any>(null);
  const [audit, setAudit] = useState<any[]>([]);
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");
  const [err, setErr] = useState("");
  const [ai, setAi] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setF(await api(`/sessions/${id}/findings/${fid}`));
      const a: any[] = await api(`/sessions/${id}/audit`);
      setAudit(a.filter((x) => x.finding === fid));
    } catch (e: any) {
      setErr(e.message);
    }
  }, [id, fid]);
  useEffect(() => { load(); }, [load]);
  const [ids, setIds] = useState<string[]>([]);
  useEffect(() => {
    api(`/sessions/${id}/findings`).then((l: any[]) => setIds(l.map((x) => x.id))).catch(() => {});
  }, [id]);
  const pos = ids.indexOf(fid);
  const prev = pos > 0 ? ids[pos - 1] : null;
  const next = pos >= 0 && pos < ids.length - 1 ? ids[pos + 1] : null;

  async function decide(action: string) {
    setErr("");
    try {
      await post(`/sessions/${id}/findings/${fid}/decision`, {
        action, reason, corrected_amount: action === "correct" ? Number(amount) : null,
      });
      setReason("");
      await load();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  async function explain() {
    setBusy(true);
    try {
      const r = await post(`/sessions/${id}/findings/${fid}/explain`);
      setAi(r.text ?? r.explanation ?? JSON.stringify(r));
    } catch (e: any) {
      setErr(e.message);
    }
    setBusy(false);
  }

  if (!f) return err ? <div className="note err">{err}</div> : <div className="muted">Loading...</div>;
  const ev: any[] = f.evidence ?? [];

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="muted"><Link href={`/s/${id}`}>Leakage report</Link> / {f.id}</div>
        <div className="row">
          {prev ? <Link href={`/s/${id}/f/${prev}`}><button className="sec">← Previous</button></Link> : <button className="sec" disabled>← Previous</button>}
          {next ? <Link href={`/s/${id}/f/${next}`}><button className="sec">Next →</button></Link> : <button className="sec" disabled>Next →</button>}
        </div>
      </div>
      <div className="row" style={{ margin: "6px 0" }}>
        <Badge k={f.klass} /> <span className={`badge b-${f.status}`}>{f.status}</span> <span className="mono muted">{f.id} · {f.rule_id} · {f.rule_source}</span>
      </div>
      <h1>{f.title}</h1>
      <div className="sub">{f.summary}</div>

      <div className="grid g3">
        <div className="card kpi"><div className="l">Potential leakage</div><div className="v red">{f.klass === "clarification" ? money(f.at_risk) : money(f.impact ?? f.amount)}</div><div className="n">{f.counted_note}</div></div>
        <div className="card kpi"><div className="l">Confidence</div><div className="v">{Math.round((f.confidence ?? 0) * 100)}%</div><div className="bar"><div style={{ width: `${(f.confidence ?? 0) * 100}%` }} /></div></div>
        <div className="card kpi"><div className="l">Claims involved</div><div className="v" style={{ fontSize: 18 }}>
          {(f.claim_ids ?? []).map((c: string) => <span key={c}><Link href={`/s/${id}/c/${c}`}>{c}</Link>{" "}</span>)}
        </div></div>
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Evidence</h2>
          <div className="muted" style={{ marginBottom: 8 }}>The actual records behind this finding. Green = the original; red = the repeat/suspect record.</div>
          {ev.map((e, i) => (
            <div key={i} className={`${/orig|earlier|first/i.test(e.role ?? "") ? "ev-orig" : "ev-dup"}`} style={{ marginBottom: 12 }}>
              <div><span className="badge">{e.role}</span> <b>{e.claim_id}</b> {e.invoice_no && <span className="mono">· {e.invoice_no}</span>}</div>
              <div>{e.description} {e.vendor && <span className="muted">· {e.vendor}</span>}</div>
              <div className="muted">{e.date} · {money(e.amount)} {e.quantity != null && `· qty ${e.quantity}`}</div>
              <div className="mono muted">{e.source}</div>
            </div>
          ))}
          {!ev.length && <div className="muted">No row-level evidence.</div>}
          {f.missing?.length > 0 && (
            <div className="note">Missing evidence: {f.missing.join(", ")}{f.next_step && <div><b>Next step:</b> {f.next_step}</div>}</div>
          )}
        </div>

        <div>
          <div className="card">
          <h2>How the amount was calculated</h2>
          <div className="muted" style={{ marginBottom: 6 }}>Step by step, so you can verify the number.</div>
            {(f.calc ?? []).map((c: any, i: number) => (
              <div key={i} className="step"><span>{c.label}</span><b>{typeof c.value === "number" ? money(c.value) : String(c.value ?? "")}</b></div>
            ))}
          </div>
          <div className="card">
            <h2>Clause &amp; possible legitimate explanation</h2>
            <p><b>Clause:</b> {f.clause}</p>
            <p className="muted"><b>Could be legitimate:</b> {f.legit}</p>
            {f.also_matched?.length > 0 && <p className="muted">Also matched: {f.also_matched.join(", ")}</p>}
            <button className="sec" disabled={busy} onClick={explain}>{busy ? "Writing..." : "Explain in plain language"}</button>
            {ai && <div className="note info" style={{ marginTop: 10 }}>{ai}</div>}
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Your decision</h2>
        <div className="muted" style={{ marginBottom: 8 }}>
          <b>Confirm</b> = yes, this is leakage (counts in totals). <b>Correct</b> = leakage exists but the amount is different (enter amount + reason).{" "}
          <b>Dismiss</b> = false alarm / legitimate (enter reason; removed from totals). <b>Reopen</b> = undo. Every action is logged below.
        </div>
        {err && <div className="note err">{err}</div>}
        <div className="grid g2">
          <input type="text" placeholder="Reason (required to dismiss or correct)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <input type="number" placeholder="Corrected amount (for Correct)" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="danger" onClick={() => decide("confirm")}>Confirm leakage</button>
          <button className="ok" onClick={() => decide("correct")}>Correct amount</button>
          <button className="sec" onClick={() => decide("dismiss")}>Dismiss</button>
          <button className="sec" onClick={() => decide("reopen")}>Reopen</button>
        </div>
        <h2 style={{ marginTop: 16 }}>History</h2>
        {audit.length ? audit.map((a, i) => (
          <div key={i} className="step"><span><b>{a.action}</b> by {a.user} — <span className="muted">{a.detail}</span></span><span className="mono muted">{a.ts}</span></div>
        )) : <div className="muted">No decisions yet.</div>}
      </div>

      {f.claims && Object.keys(f.claims).length > 0 && (
        <div className="card">
          <h2>Claim impact</h2>
          <table>
            <thead><tr><th>Claim</th><th className="num">Billed</th><th className="num">Proposed</th><th className="num">Should pay</th><th className="num">Leakage</th></tr></thead>
            <tbody>
              {Object.entries<any>(f.claims).map(([cid, s]) => (
                <tr key={cid}><td><Link href={`/s/${id}/c/${cid}`}>{cid}</Link></td><td className="num">{money(s.twin?.billed)}</td><td className="num">{money(s.twin?.proposed)}</td><td className="num">{money(s.twin?.expected)}</td><td className="num red">{money(s.leakage)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
