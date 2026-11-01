"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const NAV = [{ label: "New analysis", href: "/" }];

export default function Header() {
  const path = usePathname() || "/";
  const [role, setRole] = useState("authorised");
  useEffect(() => setRole(localStorage.getItem("cs_role") || "authorised"), []);
  const sid = path.match(/^\/s\/([^/]+)/)?.[1];
  const nav = sid
    ? [
        ...NAV,
        { label: "Leakage report", href: `/s/${sid}` },
        { label: "Cross-claim patterns", href: `/s/${sid}/patterns` },
        { label: "Audit trail", href: `/s/${sid}/audit` },
      ]
    : NAV;
  return (
    <aside className="side">
      <Link href="/" className="brand" style={{ color: "inherit" }}>
        Claim<span>IQ</span>
      </Link>
      <div className="tagline muted">Claims leakage detection</div>
      <nav>
        {nav.map((n) => (
          <Link key={n.label} href={n.href} className={"navlink" + (path === n.href ? " on" : "")}>
            {n.label}
          </Link>
        ))}
      </nav>
      
      
    </aside>
  );
}
