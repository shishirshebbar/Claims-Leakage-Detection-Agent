"""Count-once aggregation: findings -> per-line reductions -> claim digital twins -> totals."""
from collections import defaultdict

from . import twin as T

ACTIVE_STATUS = {"open", "confirmed", "corrected"}
SKIP_BY_RULE = {"coverage_limit": "coverage_limit", "settlement": "settlement", "policy_period": "policy_period"}


def finding_is_active(f):
    if f["klass"] == "confirmed":
        return f["status"] in ACTIVE_STATUS
    if f["klass"] == "suspicious":
        return f["status"] in ("confirmed", "corrected")
    return False


def finding_is_pending_suspicious(f):
    return f["klass"] == "suspicious" and f["status"] == "open"


def effective_units(f):
    units = f.get("units") or {}
    if f["status"] == "corrected" and f.get("corrected_amount") is not None:
        tot = sum(units.values())
        if tot > 0:
            k = max(0.0, float(f["corrected_amount"])) / tot
            return {u: a * k for u, a in units.items()}
    return units


def compute_state(ctx, findings):
    """ctx: dict(claims_amount, claim_lines{cid:[(uid,amount)]}, proposed{cid}, eff{cid}, period{cid:bool})"""
    line_red = defaultdict(float)
    claim_red = defaultdict(lambda: defaultdict(float))
    global_red = {}
    pend_line = defaultdict(float)
    pend_claim = defaultdict(lambda: defaultdict(float))
    pend_global = {}
    skip = defaultdict(set)
    fids = defaultdict(list)
    for f in findings:
        for c in f.get("claim_ids", []):
            fids[c].append(f["id"])
        if f["status"] == "dismissed":
            continue
        if f["rule_type"] in SKIP_BY_RULE and f["klass"] != "clarification":
            pass
        active, pending = finding_is_active(f), finding_is_pending_suspicious(f)
        if not (active or pending):
            continue
        for key, amt in effective_units(f).items():
            kind = key[:2]
            if kind == "L:":
                tgt = line_red if active else pend_line
                tgt[key[2:]] = max(tgt[key[2:]], amt)
            elif kind == "C:":
                _, cid, tag = key.split(":", 2)
                tgt = claim_red if active else pend_claim
                tgt[cid][tag] = max(tgt[cid][tag], amt)
            elif kind == "X:":
                tgt = global_red if active else pend_global
                tgt[key] = max(tgt.get(key, 0.0), amt)
    for f in findings:
        if f["status"] == "dismissed" and f["rule_type"] in SKIP_BY_RULE:
            for c in f.get("claim_ids", []):
                skip[c].add(SKIP_BY_RULE[f["rule_type"]])

    claims = {}
    total_conf = total_pot = 0.0
    for cid, lines in ctx["claim_lines"].items():
        billed = sum(a for _, a in lines)
        lr = sum(min(line_red.get(u, 0.0), a) for u, a in lines)
        cr = min(sum(claim_red[cid].values()), max(billed - lr, 0)) if cid in claim_red else 0.0
        eff = ctx["eff"].get(cid, {})
        sk = frozenset(skip.get(cid, set()))
        period = bool(ctx["period"].get(cid)) and "policy_period" not in sk
        proposed = ctx["proposed"].get(cid)
        tw = T.compute(billed, proposed, eff, lr, cr, period, sk)
        basis = tw["has_policy_terms"] or period
        if basis and proposed is not None:
            leak = max(0.0, proposed - tw["expected"])
        elif basis:
            leak = max(0.0, (tw["formula_only"] if tw["formula_only"] is not None else billed) - tw["expected"])
        else:
            leak = lr + cr
            if proposed is not None and billed > 0:
                leak = min(leak * min(1.0, proposed / billed), proposed)
        pot = sum(min(max(0.0, pend_line.get(u, 0.0) - line_red.get(u, 0.0)), a) for u, a in lines)
        pot += sum(max(0.0, v - claim_red[cid].get(t, 0.0)) for t, v in pend_claim.get(cid, {}).items()) if cid in pend_claim else 0.0
        if proposed is not None and not basis and billed > 0:
            pot *= min(1.0, proposed / billed)
        claims[cid] = {"twin": tw, "leakage": round(leak, 2), "potential": round(pot, 2), "finding_ids": fids.get(cid, []),
                       "line_reductions": {u: round(min(line_red.get(u, 0.0), a), 2) for u, a in lines if line_red.get(u)}}
        total_conf += leak
        total_pot += pot
    x_conf = sum(global_red.values())
    x_pot = sum(v for k, v in pend_global.items() if k not in global_red)
    at_risk = 0.0
    under = 0.0
    for f in findings:
        if f["status"] == "dismissed":
            continue
        if f["klass"] == "clarification" and f.get("at_risk"):
            at_risk += f["at_risk"]
        if f["klass"] == "under" and f.get("amount"):
            under += f["amount"]
    return {"claims": claims,
            "totals": {"confirmed_leakage": round(total_conf + x_conf, 2), "potential_leakage": round(total_pot + x_pot, 2),
                       "at_risk_pending_clarification": round(at_risk, 2), "under_settlement": round(under, 2)}}
