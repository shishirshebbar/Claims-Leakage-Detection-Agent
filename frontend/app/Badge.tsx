export const KLASS: Record<string, string> = {
  all: "All", confirmed: "Confirmed", suspicious: "Suspicious", clarification: "Needs clarification", under: "Under-settlement",
};

export function Badge({ k }: { k: string }) {
  return <span className={`badge b-${k}`}>{KLASS[k] ?? k}</span>;
}
