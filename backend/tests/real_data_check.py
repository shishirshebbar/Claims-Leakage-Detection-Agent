"""Real-data check: inject duplicates into the Kaggle healthcare provider fraud outpatient data and measure recall.
Run: python tests/real_data_check.py [path_to_outpatient_csv] [rows]
"""
import sys, time, os, random
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import pipeline as P

DEFAULT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "Healthcare Provider Fraud Detection Analysis dataset", "Train_Outpatientdata-1542865627584.csv")


def main(path=DEFAULT, rows=30000, k=40):
    rnd = random.Random(7)
    df = pd.read_csv(path).head(rows)
    df = df[["BeneID", "ClaimID", "ClaimStartDt", "ClaimEndDt", "Provider", "InscClaimAmtReimbursed", "DeductibleAmtPaid"]].copy()
    picks = df.sample(3 * k, random_state=7)
    exact, near, rep = picks.iloc[:k].copy(), picks.iloc[k:2 * k].copy(), picks.iloc[2 * k:].copy()
    exact["ClaimID"] = [f"DUPX{i}" for i in range(k)]
    near["ClaimID"] = [f"DUPN{i}" for i in range(k)]
    near["ClaimStartDt"] = (pd.to_datetime(near["ClaimStartDt"]) + pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    near["InscClaimAmtReimbursed"] = (near["InscClaimAmtReimbursed"] * 1.01).round(2)
    full = pd.concat([df, exact, near]).sample(frac=1, random_state=3)
    t0 = time.time()
    S = P.create_session([("outpatient.csv", full.to_csv(index=False).encode())], [], "")
    P.run_session(S)
    dt = time.time() - t0
    touched = {}
    for f in S["findings"]:
        for c in f["claim_ids"]:
            touched.setdefault(c, set()).add(f["rule_id"])
    ex = sum(1 for i in range(k) if f"DUPX{i}" in touched)
    nr = sum(1 for i in range(k) if f"DUPN{i}" in touched)
    fp = len([c for c in touched if not c.startswith("DUP")])
    print(f"rows={len(full)} runtime={dt:.1f}s findings={len(S['findings'])}")
    print(f"exact duplicates found {ex}/{k}; near duplicates found {nr}/{k}; other claims flagged (originals/natural) {fp}")
    print("totals", S["state"]["totals"] if "totals" in S["state"] else list(S["state"].keys()))
    return ex, nr


if __name__ == "__main__":
    main(*(sys.argv[1:2] or [DEFAULT]), *(int(a) for a in sys.argv[2:3]))
