export const money = (n: number | null | undefined) =>
  n == null ? "-" : Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const txt = (x: any): string => {
  if (x == null) return "";
  if (typeof x === "string") return x;
  if (typeof x === "object") {
    const t = x.text ?? x.message ?? x.reason ?? x.name ?? x.title;
    const f = x.file ?? x.source ?? x.src;
    if (t != null) return typeof t === "string" ? (f && x.reason ? `${f}: ${t}` : t) : JSON.stringify(t);
    return JSON.stringify(x);
  }
  return String(x);
};
export const lvl = (x: any): string => (x && typeof x === "object" && x.level === "info" ? "note info" : "note");

export function getRole(): string {
  if (typeof window === "undefined") return "authorised";
  return localStorage.getItem("cs_role") || "authorised";
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Role": getRole(), ...(init.headers as any) };
  const r = await fetch(`/api${path}`, { ...init, headers });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = j.detail || j.error || JSON.stringify(j);
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export const post = <T = any>(path: string, body?: any) =>
  api<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
