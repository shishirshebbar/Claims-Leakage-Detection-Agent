"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, money } from "../../../../api";
import { Badge } from "../../../../Badge";

export default function ClaimTwin() {
  const { id, cid } = useParams<{ id: string; cid: string }>();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api(`/sessions/${id}/claims/${encodeURIComponent(cid)}`).then(setD).catch((e) => setErr(e.message)); }, [id, cid]);
  if (err) return <div className="note err">{err}</div>;
  if (!d) return <div className="muted">Loading...</div>;
  const tw = d.twin;
  const c = d.claim;

  return (
    <>
      <div className="muted"><Link href={`/s/${id}`}>← Report</Link></div>
      <h1>Claim {c.claim_id} · digital twin</h1>
      <div className="sub">{[c.claim_type, c.provider, c.policy_id, c.claimant_id].filter(Boolean).join(" · ")}<br />This page compares what was paid with what the policy says should be paid for this one claim.</div>

      <div className="grid g3">
        <div className="card kpi"><div className="l">As proposed / paid</div><div className="v">{money(tw.proposed)}</div></div>
        <div className="card kpi"><div className="l">Should pay</div><div className="v green">{money(tw.expected)}</div><div className="n">{tw.has_policy_terms ? "after policy terms" : "no policy terms found — line-level checks only"}</div></div>
        <div className="card kpi"><div className="l">Difference</div><div className="v red">{money(d.leakage)}</div>{d.potential > 0 && <div className="n amber">+ {money(d.potential)} potential</div>}</div>
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Settlement recalculation</h2>
          {tw.steps.map((s: any, i: number) => (
            <div key={i} className="step"><span>{s.label}</span><span><b>{money(s.value)}</b> {s.running != null && <span className="muted">→ {money(s.running)}</span>}</span></div>
          ))}
        </div>
        <div className="card">
          <h2>Timeline</h2>
          <div className="timeline">
            {d.timeline.map((t: any, i: number) => <div key={i} className="t"><b>{t.date}</b> {t.event}</div>)}
          </div>
          <div className="muted">Documents on file: {d.documents?.length ? d.documents.join(", ") : "none"}</div>
        </div>
      </div>

      <div className="card">
        <h2>Invoice lines</h2>
        <table>
          <thead><tr><th>Invoice</th><th>Description</th><th>Date</th><th className="num">Qty</th><th className="num">Amount</th><th className="num">Reduction</th></tr></thead>
          <tbody>
            {d.lines.map((l: any) => (
              <tr key={l.uid}><td className="mono">{l.invoice_no}</td><td>{l.description}</td><td>{l.date}</td><td className="num">{l.quantity}</td><td className="num">{money(l.amount)}</td><td className="num red">{l.reduction ? money(l.reduction) : ""}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Findings on this claim</h2>
        <table>
          <tbody>
            {d.findings.map((f: any) => (
              <tr key={f.id}><td><Link href={`/s/${id}/f/${f.id}`}>{f.id}</Link></td><td><b>{f.rule_id}</b> {f.title}</td><td><Badge k={f.klass} /></td><td className="num">{money(f.impact ?? f.amount)}</td></tr>
            ))}
            {!d.findings.length && <tr><td className="muted">No findings.</td></tr>}
          </tbody>
        </table>
      </div>

      {d.payments?.length > 0 && (
        <div className="card">
          <h2>Payments</h2>
          <table>
            <tbody>
              {d.payments.map((p: any, i: number) => <tr key={i}><td className="mono">{p.payment_id}</td><td>{p.payment_date}</td><td>{p.method}</td><td className="mono">{p.reference}</td><td className="num">{money(p.amount)}</td></tr>)}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
