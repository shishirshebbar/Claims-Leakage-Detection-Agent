"""Session orchestration: upload -> mapping/rules proposal -> run -> decisions (with audit)."""
import json
import math
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import agent as AGT
from . import aggregate as AG
from . import ingest as IN
from . import llm
from . import rules_dsl as RD
from .engine import Engine

SESSIONS = {}
DATA = Path(__file__).resolve().parent.parent / "data" / "runs"


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return None if math.isnan(o) or math.isinf(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return None if pd.isna(o) else o.strftime("%Y-%m-%d")
    if o is pd.NaT:
        return None
    return o


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_session(files, rule_files, rules_text):
    sid = uuid.uuid4().hex[:10]
    tables, failed = IN.read_tables(files)
    proposals = [IN.propose(t) for t in tables]
    rp = RD.parse_rules(rule_files, rules_text, llm_translate=llm.translate_rule if llm.available() else None)
    S = {"id": sid, "created": now(), "tables": tables, "proposals": proposals, "failed": failed, "rule_parse": rp,
         "audit": [], "ran": False, "file_names": [n for n, _ in files]}
    SESSIONS[sid] = S
    audit(S, "system", "session_created", f"{len(tables)} table(s), {len(rp['rules'])} custom rule(s)")
    return S


def mapping_view(S):
    return clean({"id": S["id"], "failed": S["failed"],
                  "tables": [{k: v for k, v in p.items() if k != "all_mappings"} | {"available_mappings": p["all_mappings"]} for p in S["proposals"]],
                  "rules": S["rule_parse"]["rules"], "unparsed_rules": S["rule_parse"]["unparsed"], "rule_notes": S["rule_parse"]["notes"],
                  "default_rules": RD.DEFAULT_RULES, "llm": llm.available()})


def audit(S, user, action, detail, finding=None):
    S["audit"].append({"ts": now(), "user": user, "action": action, "finding": finding, "detail": detail})


def _apply_agent(S):
    """One batched LLM call per run covers all subagent roles. Advice only: amounts are never changed.
    If the key is missing or the call fails, the run keeps deterministic results."""
    AGT.attach(S["findings"], None)
    if not llm.available():
        return AGT.run_mode(False)
    result, err = AGT.analyse(S["findings"], S.get("lookalikes"))
    if result is None:
        S["agent_error"] = err
        return AGT.run_mode(False)
    AGT.attach(S["findings"], result)
    S["lookalike_review"] = result["lookalikes"]
    return AGT.run_mode(True)


def run_session(S, overrides=None, judge_rules=None, mode="augment"):
    t0 = time.time()
    ds = IN.build_dataset(S["tables"], S["proposals"], overrides)
    ds.failed_files = S["failed"]
    jr = judge_rules if judge_rules is not None else S["rule_parse"]["rules"]
    rules = RD.merge_rules(jr, mode)
    eng = Engine(ds, rules)
    findings = eng.run()
    S.update(ds=ds, rules=rules, eng=eng, findings=findings, lookalikes=eng.lookalikes, ran=True, mode=mode,
             ctx=eng.context(), runtime=round(time.time() - t0, 2), impact_done=False)
    recompute(S)
    S["agent_mode"] = _apply_agent(S)
    audit(S, "system", "analysis_run", f"{len(findings)} finding(s) in {S['runtime']}s; rules mode={mode}; agent={S['agent_mode']}")
    save(S)
    return S


def standalone_impact(S, f):
    """Payable overpayment this finding drives on its own (after deductible/copay/cap), used as the headline amount."""
    cl = [c for c in f["claim_ids"] if c in S["ctx"]["claim_lines"]]
    if not f["units"] or f["klass"] not in ("confirmed", "suspicious"):
        return f["amount"]
    if all(k.startswith(("T:", "X:")) for k in f["units"]):
        return f["amount"]
    sub = {"claim_lines": {c: S["ctx"]["claim_lines"][c] for c in cl}, "proposed": S["ctx"]["proposed"], "eff": S["ctx"]["eff"], "period": {}}
    g = dict(f, klass="confirmed", status="open")
    t = AG.compute_state(sub, [g])["totals"]["confirmed_leakage"]
    return round(t, 2)


def recompute(S):
    S["state"] = AG.compute_state(S["ctx"], S["findings"])
    if not S.get("impact_done"):
        for f in S["findings"]:
            f["impact"] = standalone_impact(S, f) if len(S["findings"]) < 4000 else f["amount"]
        S["impact_done"] = True
    return S["state"]


def summary(S):
    ds, F, st = S["ds"], S["findings"], S["state"]
    by_klass = Counter(f["klass"] for f in F)
    open_ = Counter(f["klass"] for f in F if f["status"] == "open")
    status = Counter(f["status"] for f in F)
    rule_counts = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for f in F:
        if f["status"] != "dismissed":
            rule_counts[f["rule_id"]]["count"] += 1
            rule_counts[f["rule_id"]]["amount"] += f["amount"] or 0
    names = {r["id"]: r for r in S["rules"]}
    claims = sorted(((c, v) for c, v in st["claims"].items() if v["leakage"] or v["potential"]), key=lambda x: -(x[1]["leakage"] + x[1]["potential"]))
    billed = sum(v["twin"]["billed"] for v in st["claims"].values())
    paid = sum((v["twin"]["proposed"] or 0) for v in st["claims"].values())
    out = {"id": S["id"], "dataset": ds.summary(), "notes": ds.notes, "quarantine": ds.quarantine[:200], "quarantine_count": len(ds.quarantine),
           "failed_files": S["failed"], "not_run": S["eng"].not_run, "runtime_s": S["runtime"], "totals": st["totals"],
           "billed_total": round(billed, 2), "proposed_total": round(paid, 2),
           "counts": {"confirmed": by_klass["confirmed"], "suspicious": by_klass["suspicious"], "clarification": by_klass["clarification"],
                      "under": by_klass["under"], "lookalike": len(S["lookalikes"]), "open": sum(open_.values())},
           "status": dict(status),
           "rules": [{"id": r["id"], "name": r["name"], "type": r["type"], "source": r.get("source", "default"), "enabled": r.get("enabled", True),
                      "klass": r["klass"], "params": r["params"], "text": r.get("text", ""), "hits": rule_counts.get(r["id"], {}).get("count", 0),
                      "amount": round(rule_counts.get(r["id"], {}).get("amount", 0.0), 2)} for r in S["rules"]],
           "top_claims": [{"claim_id": c, "leakage": v["leakage"], "potential": v["potential"], "billed": v["twin"]["billed"], "proposed": v["twin"]["proposed"],
                           "expected": v["twin"]["expected"], "findings": len(v["finding_ids"])} for c, v in claims[:25]],
           "audit_count": len(S["audit"])}
    return clean(out)


def list_findings(S, klass=None, status=None, rule=None, q=None, claim=None):
    out = []
    for f in S["findings"]:
        if klass and f["klass"] != klass:
            continue
        if status and f["status"] != status:
            continue
        if rule and f["rule_id"] != rule:
            continue
        if claim and claim not in f["claim_ids"]:
            continue
        if q and q.lower() not in (f["title"] + f["summary"] + " ".join(f["claim_ids"])).lower():
            continue
        out.append({k: f.get(k) for k in ("id", "rule_id", "rule_name", "klass", "title", "claim_ids", "amount", "impact", "at_risk", "confidence", "status", "also_matched", "summary")})
    return clean(out)


def get_finding(S, fid):
    f = next((x for x in S["findings"] if x["id"] == fid), None)
    if not f:
        return None
    uids = {u[2:] for u in f["units"] if u.startswith("L:")}
    overlap = [g["id"] for g in S["findings"] if g["id"] != fid and g["status"] != "dismissed" and uids & {u[2:] for u in g["units"] if u.startswith("L:")}]
    twins = {c: S["state"]["claims"][c] for c in f["claim_ids"] if c in S["state"]["claims"]}
    d = dict(f)
    d["overlaps"] = overlap
    d["claims"] = twins
    d["counted_note"] = ("Counted once in totals: overlapping findings " + ", ".join(overlap) + " share the same line(s); the larger reduction applies, never the sum."
                         if overlap else "Counted once in totals.") if f["units"] else None
    return clean(d)


def decide(S, fid, action, user, reason="", corrected_amount=None):
    f = next((x for x in S["findings"] if x["id"] == fid), None)
    if not f:
        raise KeyError(fid)
    if action not in ("confirm", "dismiss", "correct", "reopen"):
        raise ValueError("bad action")
    if action in ("dismiss", "correct") and not reason.strip():
        raise ValueError("a reason is required")
    if action == "correct" and corrected_amount is None:
        raise ValueError("corrected amount required")
    before = {"status": f["status"], "amount": f["amount"]}
    if action == "confirm":
        f["status"] = "confirmed"
    elif action == "dismiss":
        f["status"] = "dismissed"
    elif action == "correct":
        f["status"] = "corrected"
        f["corrected_amount"] = float(corrected_amount)
    else:
        f["status"] = "open"
        f["corrected_amount"] = None
    f["decision"] = {"by": user, "action": action, "reason": reason, "at": now()}
    old = S["state"]["totals"]
    new = recompute(S)["totals"]
    audit(S, user, action, f"{reason} | {before['status']}->{f['status']} | confirmed leakage {old['confirmed_leakage']} -> {new['confirmed_leakage']}", fid)
    save(S)
    return f


def save(S):
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        payload = {"id": S["id"], "audit": S["audit"], "findings": [{k: f.get(k) for k in ("id", "rule_id", "klass", "title", "status", "amount", "decision", "corrected_amount")} for f in S.get("findings", [])]}
        (DATA / f"{S['id']}.json").write_text(json.dumps(clean(payload), indent=1), encoding="utf-8")
    except Exception:
        pass


def export_rows(S):
    rows = []
    for f in S["findings"]:
        rows.append({"finding_id": f["id"], "rule": f["rule_id"], "class": f["klass"], "status": f["status"], "claims": ";".join(f["claim_ids"]),
                     "title": f["title"], "potential_leakage": f["amount"] if f["klass"] in ("confirmed", "suspicious") else "",
                     "at_risk_pending_clarification": f["at_risk"] or "", "clause": f["clause"] or "", "explanation": f["summary"],
                     "decided_by": (f.get("decision") or {}).get("by", ""), "decision_reason": (f.get("decision") or {}).get("reason", ""),
                     "corrected_amount": f.get("corrected_amount") or ""})
    return rows
