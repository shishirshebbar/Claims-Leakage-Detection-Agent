"""Cross-claim leakage fingerprinting: recurring problems across providers, claimants, bank accounts and policies.

Purely deterministic. It reuses the run's findings and per-claim twin state, so it adds no LLM calls
and never changes amounts. Exposure is taken from the claim-level state, so it is counted once.
"""
from collections import Counter, defaultdict

DIMENSIONS = (("provider", "Provider"), ("claimant_id", "Claimant"), ("bank_account", "Bank account"), ("policy_id", "Policy / workflow"))
MAX_CLAIMS_SHOWN = 12


def _active(f):
    return f["status"] != "dismissed" and f["klass"] in ("confirmed", "suspicious")


def compute(S):
    claims = S["ds"].claims
    state = S["state"]["claims"]
    names = {r["id"]: r["name"] for r in S["rules"]}

    rules_by_claim = defaultdict(Counter)
    for f in S["findings"]:
        if _active(f):
            for c in f["claim_ids"]:
                rules_by_claim[c][f["rule_id"]] += 1

    total = len(claims)
    flagged_all = {c for c, v in rules_by_claim.items() if v}
    base_rate = len(flagged_all) / total if total else 0.0

    patterns = []
    for col, label in DIMENSIONS:
        if col not in claims.columns:
            continue
        sub = claims[claims[col].astype(str).str.strip().ne("")]
        for key, g in sub.groupby(col):
            ids = list(g["claim_id"])
            flagged = [c for c in ids if c in flagged_all]
            if len(flagged) < 2:
                continue
            rate = len(flagged) / len(ids)
            lift = rate / base_rate if base_rate else 0.0
            if col in ("provider", "policy_id") and lift < 1.2:
                continue
            if col == "bank_account" and g["claimant_id"].nunique() < 2:
                continue
            rules = Counter()
            for c in flagged:
                rules.update(rules_by_claim[c])
            top, top_n = rules.most_common(1)[0]
            exposure = sum(state.get(c, {}).get("leakage", 0) + state.get(c, {}).get("potential", 0) for c in flagged)
            if col == "bank_account":
                text = f"{g['claimant_id'].nunique()} different claimants are paid to the same bank account"
            else:
                text = f"Recurring '{names.get(top, top)}' ({top_n} hit(s) across {len(flagged)} of {len(ids)} claims)"
            patterns.append({
                "dimension": col, "dimension_label": label, "key": str(key), "claims_total": len(ids), "flagged_claims": len(flagged),
                "flag_rate": round(rate, 3), "lift": round(lift, 2), "exposure": round(exposure, 2), "fingerprint": text,
                "rules": [{"rule_id": r, "name": names.get(r, r), "count": n} for r, n in rules.most_common()],
                "claim_ids": flagged[:MAX_CLAIMS_SHOWN], "more": max(0, len(flagged) - MAX_CLAIMS_SHOWN),
            })

    patterns.sort(key=lambda p: -p["exposure"])
    for i, p in enumerate(patterns, 1):
        p["id"] = f"FP-{i:03d}"
    rule_totals = Counter()
    for c in flagged_all:
        rule_totals.update(rules_by_claim[c].keys())
    return {
        "portfolio": {"claims": total, "flagged_claims": len(flagged_all), "flag_rate": round(base_rate, 3),
                      "patterns": len(patterns), "pattern_exposure": round(sum(p["exposure"] for p in patterns), 2)},
        "patterns": patterns,
        "rule_spread": [{"rule_id": r, "name": names.get(r, r), "claims": n} for r, n in rule_totals.most_common()],
    }
