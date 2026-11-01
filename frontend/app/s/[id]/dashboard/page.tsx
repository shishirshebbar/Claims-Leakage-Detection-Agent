"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, money } from "../../../api";

export default function Dashboard() {
  const { id } = useParams<{ id: string }>();
  const [sum, setSum] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api(`/sessions/${id}/summary`).then(setSum).catch((e) => setErr(e.message));
  }, [id]);

  if (err) return <div className="note err">{err}</div>;
  if (!sum) return <div className="muted">Loading...</div>;

  const t = sum.totals ?? {};
  const rules = (sum.rules ?? []).filter((r: any) => r.hits > 0).sort((a: any, b: any) => b.amount - a.amount);
  const maxAmt = Math.max(1, ...rules.map((r: any) => r.amount || 0));
  const totalAmt = rules.reduce((s: number, r: any) => s + (r.amount || 0), 0) || 1;
  const allTop: any[] = sum.top_claims ?? [];
  const top = allTop.slice(0, 8);
  const maxTop = Math.max(1, ...top.map((c: any) => c.leakage || 0));
  const share = sum.proposed_total ? (t.confirmed_leakage / sum.proposed_total) * 100 : 0;
  const findings = rules.reduce((s: number, r: any) => s + (r.hits || 0), 0);

  return (
    <>
      <div className="muted"><Link href={`/s/${id}`}>Leakage report</Link> / Dashboard</div>
      <h1>Portfolio dashboard</h1>
      <div className="sub">
        {sum.dataset.claims} claims · {sum.dataset.lines} invoice lines · proposed settlements {money(sum.proposed_total)}
      </div>

      <div className="grid g4">
        <div className="card kpi"><div className="l">Confirmed leakage</div><div className="v red">{money(t.confirmed_leakage)}</div><div className="n">{share.toFixed(1)}% of proposed</div></div>
        <div className="card kpi"><div className="l">Rule hits</div><div className="v">{findings}</div><div className="n">across {rules.length} rules</div></div>
        <div className="card kpi"><div className="l">Claims with leakage</div><div className="v">{allTop.length}</div><div className="n">of {sum.dataset.claims}</div></div>
        <div className="card kpi"><div className="l">Analysis time</div><div className="v">{sum.runtime_s}s</div><div className="n">{sum.audit_count} audit entries</div></div>
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Leakage by rule</h2>
          <div className="muted" style={{ marginBottom: 10 }}>Amount attributed to each check (a charge hit by several rules appears under each).</div>
          {rules.map((r: any) => (
            <div key={r.id} style={{ marginBottom: 10 }}>
              <div className="step"><span><b>{r.id}</b> <span className="muted">{r.name}</span></span><b>{money(r.amount)} <span className="muted">({Math.round(((r.amount || 0) / totalAmt) * 100)}%)</span></b></div>
              <div className="bar"><div style={{ width: `${((r.amount || 0) / maxAmt) * 100}%` }} /></div>
            </div>
          ))}
          {!rules.length && <div className="muted">No rules fired.</div>}
        </div>
        <div className="card">
          <h2>Top claims by leakage</h2>
          <div className="muted" style={{ marginBottom: 10 }}>Open a claim to see what it should have paid.</div>
          {top.map((c: any) => (
            <div key={c.claim_id} style={{ marginBottom: 10 }}>
              <div className="step"><span><Link href={`/s/${id}/c/${c.claim_id}`}>{c.claim_id}</Link></span><b className="red">{money(c.leakage)}</b></div>
              <div className="bar"><div style={{ width: `${((c.leakage || 0) / maxTop) * 100}%` }} /></div>
            </div>
          ))}
          {!top.length && <div className="muted">No claims with leakage.</div>}
        </div>
      </div>
    </>
  );
}
