"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../../../api";

export default function Audit() {
  const { id } = useParams<{ id: string }>();
  const [a, setA] = useState<any[]>([]);
  useEffect(() => { api(`/sessions/${id}/audit`).then(setA); }, [id]);
  return (
    <>
      <div className="muted"><Link href={`/s/${id}`}>← Report</Link></div>
      <h1>Audit trail</h1>
      <div className="card">
        <table>
          <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Finding</th><th>Detail</th></tr></thead>
          <tbody>
            {[...a].reverse().map((x, i) => (
              <tr key={i}><td className="mono">{x.ts}</td><td>{x.user}</td><td>{x.action}</td><td>{x.finding ? <Link href={`/s/${id}/f/${x.finding}`}>{x.finding}</Link> : ""}</td><td>{x.detail}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
