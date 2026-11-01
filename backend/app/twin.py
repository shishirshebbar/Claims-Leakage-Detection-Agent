"""Claim Digital Twin: recompute what should have been paid from policy terms and active findings."""
import math


def _isnum(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def formula(billed, eff, skip=frozenset()):
    """Apply deductible -> copay -> cap. Returns (expected, steps)."""
    steps = [{"label": "Eligible billed amount", "value": round(billed, 2)}]
    cur = billed
    if "settlement" not in skip:
        ded = eff.get("deductible")
        if _isnum(ded) and ded > 0:
            d = min(ded, max(cur, 0))
            cur -= d
            steps.append({"label": f"Less deductible ({ded:,.2f})", "value": round(-d, 2), "running": round(cur, 2)})
        cp = eff.get("copay_pct")
        if _isnum(cp) and cp > 0:
            c = cur * cp / 100.0
            cur -= c
            steps.append({"label": f"Less co-payment ({cp:g}%)", "value": round(-c, 2), "running": round(cur, 2)})
    lim = eff.get("coverage_limit")
    if "coverage_limit" not in skip and _isnum(lim) and lim > 0 and cur > lim:
        steps.append({"label": f"Capped at coverage limit ({lim:,.2f})", "value": round(lim - cur, 2), "running": round(lim, 2)})
        cur = lim
    return max(cur, 0.0), steps


def has_terms(eff):
    return any(_isnum(eff.get(k)) and eff.get(k) for k in ("deductible", "copay_pct", "coverage_limit"))


def compute(billed, proposed, eff, line_red_total, claim_red, period_violation, skip=frozenset()):
    """Return twin dict for one claim.
    billed: sum of line amounts; line_red_total: sum of per-line reductions already capped; claim_red: claim-level reductions."""
    eligible = max(billed - line_red_total - claim_red, 0.0)
    terms = has_terms(eff)
    steps = [{"label": "Billed (as invoiced)", "value": round(billed, 2)}]
    if line_red_total:
        steps.append({"label": "Less duplicate / excluded / over-limit lines", "value": round(-line_red_total, 2), "running": round(billed - line_red_total, 2)})
    if claim_red:
        steps.append({"label": "Less claim-level amount inconsistencies", "value": round(-claim_red, 2), "running": round(eligible, 2)})
    if period_violation and "policy_period" not in skip:
        expected, calc = 0.0, [{"label": "Loss outside policy period / waiting period: not payable", "value": round(-eligible, 2), "running": 0.0}]
    else:
        expected, calc = formula(eligible, eff, skip) if terms else (eligible, [])
        calc = calc[1:]
    steps += calc
    base_expected = None
    if terms or period_violation:
        base_expected, _ = formula(billed, eff, skip) if terms else (billed, [])
        if period_violation and "policy_period" not in skip:
            base_expected = 0.0
    out = {"billed": round(billed, 2), "expected": round(expected, 2), "steps": steps, "has_policy_terms": terms,
           "proposed": round(proposed, 2) if _isnum(proposed) else None, "formula_only": None}
    # formula_only: what a correct application of the formula to the *billed* figure pays (isolates calc mistakes)
    out["formula_only"] = round(base_expected, 2) if base_expected is not None else None
    return out
