"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, money } from "../../../api";

const COLORS: Record<string, string> = { provider: "#2563eb", claimant_id: "#d97706", bank_account: "#dc2626", policy_id: "#7c3aed" };

function Cluster({ p, onClaim }: { p: any; onClaim: (c: string) => void }) {
  const W = 300, H = 230, cx = W / 2, cy = H / 2, R = 85;
  const n = p.claim_ids.length;
  const color = COLORS[p.dimension] ?? "#475569";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxHeight: 230 }}>
      {p.claim_ids.map((c: string, i: number) => {
        const a = (2 * Math.PI * i) / n - Math.PI / 2;
        const x = cx + R * Math.cos(a), y = cy + R * Math.sin(a);
        return (
          <g key={c} style={{ cursor: "pointer" }} onClick={() => onClaim(c)}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke={color} strokeWidth={1.5} opacity={0.6} />
            <circle cx={x} cy={y} r={9} fill="#fff" stroke={color} strokeWidth={2} />
            <text x={x} y={y + (y > cy ? 22 : -14)} fontSize={9} textAnchor="middle" fill="#475569">{c}</text>
          </g>
        );
      })}
      <circle cx={cx} cy={cy} r={26} fill={color} />
      <text x={cx} y={cy + 4} fontSize={10} textAnchor="middle" fill="#fff">{String(p.key).slice(0, 10)}</text>
    </svg>
  );
}

export default function Patterns() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api(`/sessions/${id}/fingerprints`).then(setD).catch((e) => setErr(e.message)); }, [id]);
  if (err) return <div className="note err">{err}</div>;
  if (!d) return <div className="muted">Loading...</div>;
  const pf = d.portfolio;

  return (
    <>
      <div className="muted"><Link href={`/s/${id}`}>← Report</Link></div>
      <h1>Cross-claim leakage fingerprints</h1>
      <div className="sub">
        Recurring problems across providers, claimants, bank accounts and policies. These are review leads, not proof of wrongdoing.
      </div>
      <div className="grid g4" style={{ marginBottom: 16 }}>
        <div className="card kpi"><div className="l">Claims analysed</div><div className="v">{pf.claims}</div></div>
        <div className="card kpi"><div className="l">Claims with findings</div><div className="v">{pf.flagged_claims}</div><div className="n">{(pf.flag_rate * 100).toFixed(0)}% of portfolio</div></div>
        <div className="card kpi"><div className="l">Recurring patterns</div><div className="v">{pf.patterns}</div></div>
        <div className="card kpi"><div className="l">Exposure in patterns</div><div className="v red">{money(pf.pattern_exposure)}</div><div className="n">patterns can overlap</div></div>
      </div>

      {!d.patterns.length && <div className="note">No recurring cross-claim patterns found in this portfolio.</div>}
      <div className="grid g2">
        {d.patterns.map((p: any) => (
          <div key={p.id} className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div><span className="badge">{p.dimension_label}</span> <b>{p.key}</b> <span className="mono muted">{p.id}</span></div>
              <div className="red"><b>{money(p.exposure)}</b></div>
            </div>
            <div style={{ margin: "6px 0" }}>{p.fingerprint}</div>
            <div className="muted">
              {p.flagged_claims} of {p.claims_total} claims flagged ({(p.flag_rate * 100).toFixed(0)}%) · {p.lift}x the portfolio rate
            </div>
            <Cluster p={p} onClaim={(c) => router.push(`/s/${id}/c/${c}`)} />
            {p.more > 0 && <div className="muted">+ {p.more} more claim(s)</div>}
            <div className="muted">Rules: {p.rules.map((r: any) => `${r.rule_id} ×${r.count}`).join(", ")}</div>
          </div>
        ))}
      </div>

      <div className="card">
        <h2>Most widespread issues</h2>
        <table>
          <tbody>
            {d.rule_spread.map((r: any) => <tr key={r.rule_id}><td className="mono">{r.rule_id}</td><td>{r.name}</td><td className="num">{r.claims} claims</td></tr>)}
          </tbody>
        </table>
      </div>
    </>
  );
}
