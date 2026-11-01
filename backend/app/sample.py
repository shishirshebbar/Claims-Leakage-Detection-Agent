"""Synthetic bundles with planted leakage + ground truth. Run: python -m app.sample"""
import json
import random
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[2] / "sample_data"

POLICIES = [
    dict(policy_id="P-100", policy_type="Health Gold", coverage_limit=200000, deductible=1000, copay_pct=10, room_limit_per_day=5000,
         start_date="2024-01-01", end_date="2024-12-31", exclusions="cosmetic; vitamins; gloves", sub_limits="ambulance:3000",
         required_documents="invoice; discharge summary", waiting_days=0),
    dict(policy_id="P-200", policy_type="Health Basic", coverage_limit=50000, deductible=2000, copay_pct=0, room_limit_per_day=3000,
         start_date="2024-03-01", end_date="2025-02-28", exclusions="cosmetic; dental whitening", sub_limits="",
         required_documents="invoice", waiting_days=30),
]
PROVIDERS = ["City General Hospital", "Sunrise Clinic", "Apollo Care", "Metro Diagnostics", "Green Valley Hospital"]
SERVICES = [("Consultation", "consult", 800), ("Blood test CBC", "diagnostics", 600), ("X-ray chest", "diagnostics", 1200),
            ("Medication", "pharmacy", 2500), ("Surgery fee", "surgery", 30000), ("ECG", "diagnostics", 900), ("Nursing charges", "nursing", 1500)]


def formula(billed, pol):
    cur = max(billed - pol["deductible"], 0)
    cur *= 1 - pol["copay_pct"] / 100
    return min(cur, pol["coverage_limit"])


def build(seed=7):
    rnd = random.Random(seed)
    pol = {p["policy_id"]: p for p in POLICIES}
    claims, lines, pays, docs, truth = [], [], [], [], []
    n = [1000]

    def claim(policy, claimant, provider, loss, items, proposed=None, invoice=None, filed_days=3, claim_id=None, docs_have=("invoice", "discharge summary"), bank=None):
        n[0] += 1
        cid = claim_id or f"CL-{n[0]}"
        inv = invoice or f"INV-{rnd.randint(10000, 99999)}"
        billed = sum(q * p for _, _, q, p in items)
        prop = formula(billed, pol[policy]) if proposed is None else proposed
        d = pd.Timestamp(loss)
        claims.append(dict(claim_id=cid, policy_id=policy, claimant_id=claimant, provider=provider, claim_type="Health", loss_date=d.strftime("%d/%m/%Y"),
                           claim_date=(d + pd.Timedelta(days=filed_days)).strftime("%d/%m/%Y"), claimed_amount=billed, proposed_settlement=round(prop, 2),
                           invoice_no=inv, bank_account=bank or f"ACC{rnd.randint(10**8, 10**9)}"))
        for k, (desc, cat, q, p) in enumerate(items, 1):
            lines.append(dict(claim_id=cid, line_no=k, invoice_no=inv, vendor=provider, service_date=d.strftime("%d/%m/%Y"), description=desc,
                              category=cat, quantity=q, unit_price=p, amount=q * p))
        for dt in docs_have:
            docs.append(dict(claim_id=cid, doc_type=dt))
        pays.append(dict(payment_id=f"PAY-{cid}", claim_id=cid, invoice_no=inv, amount=round(prop, 2), payment_date=(d + pd.Timedelta(days=15)).strftime("%d/%m/%Y"),
                         method="NEFT", reference=f"UTR{rnd.randint(10**9, 10**10)}"))
        return cid, billed, prop

    def clean_items():
        k = rnd.sample(SERVICES, rnd.randint(2, 4))
        return [(s, c, 1, p + rnd.randint(-50, 50)) for s, c, p in k]

    # ---- clean claims
    for i in range(30):
        pid = "P-100" if i % 3 else "P-200"
        loss = pd.Timestamp("2024-06-01") + pd.Timedelta(days=rnd.randint(0, 150))
        claim(pid, f"M{rnd.randint(1000, 9999)}", rnd.choice(PROVIDERS), loss, clean_items())

    # ---- planted
    items = [("Surgery fee", "surgery", 1, 30000), ("Anaesthesia", "surgery", 1, 6000), ("Medication", "pharmacy", 1, 2500)]
    a, ba, pa = claim("P-100", "M2001", "City General Hospital", "2024-05-10", items, invoice="INV-7781")
    b, bb, pb = claim("P-100", "M2001", "City General Hospital", "2024-05-10", items, invoice="inv 7781", filed_days=20)
    truth.append(dict(type="duplicate_invoice", claims=[a, b], leakage=round(pb, 2), note="Same invoice paid in two claims; overpayment = full second payment, counted once"))

    c, bc, pc = claim("P-100", "M2002", "Metro Diagnostics", "2024-07-02", [("MRI brain", "diagnostics", 1, 9000), ("MRI brain", "diagnostics", 1, 9000), ("Consultation", "consult", 1, 800)])
    truth.append(dict(type="duplicate_line", claims=[c], note="Same MRI line twice in one invoice (9000 line duplicated)"))

    d, bd, pd_ = claim("P-100", "M2003", "Green Valley Hospital", "2024-08-01", [("Room rent", "room", 3, 8000), ("Medication", "pharmacy", 1, 4000)])
    truth.append(dict(type="room_limit", claims=[d], excess=9000, note="Room 8000/day vs 5000 limit x3 days"))

    e, be, pe = claim("P-100", "M2004", "Apollo Care", "2024-04-15", [("Consultation", "consult", 1, 1000), ("Vitamins course", "pharmacy", 1, 3500), ("Blood test", "diagnostics", 1, 700)])
    truth.append(dict(type="exclusion", claims=[e], excess=3500, note="Vitamins excluded"))

    f_items = [("Surgery fee", "surgery", 1, 40000), ("Medication", "pharmacy", 1, 6000)]
    f_, bf, pf = claim("P-100", "M2005", "Sunrise Clinic", "2024-09-09", f_items, proposed=46000)
    truth.append(dict(type="settlement", claims=[f_], expected=formula(bf, pol["P-100"]), proposed=46000, note="Deductible and copay not applied"))

    g, bg, pg = claim("P-100", "M2006", "Apollo Care", "2024-10-03", [("Cardiology consult", "consult", 1, 1500), ("ECG", "diagnostics", 1, 900)], invoice="AP-5501")
    h, bh, ph = claim("P-100", "M2006", "Apollo Care", "2024-10-04", [("Cardiology consult", "consult", 1, 1515), ("ECG", "diagnostics", 1, 900)], invoice="AP-5502", filed_days=8)
    truth.append(dict(type="near_duplicate", claims=[g, h], note="Date +1, amount +1%, different reference; should be suspicious"))

    ph_items = []
    for dt in ("2024-06-03", "2024-06-10", "2024-06-17", "2024-06-24"):
        cid, _, _ = claim("P-100", "M2007", "Sunrise Clinic", dt, [("Physiotherapy session", "therapy", 1, 1200)])
    truth.append(dict(type="lookalike", claims=[cid], note="Weekly physiotherapy: legitimate; must NOT be flagged as duplicate"))

    i_, bi, pi = claim("P-100", "M2008", "City General Hospital", "2024-06-20", [("Surgery fee", "surgery", 1, 25000)], docs_have=("invoice",))
    truth.append(dict(type="missing_document", claims=[i_], note="Discharge summary missing"))

    j, bj, pj = claim("P-200", "M2009", "Sunrise Clinic", "2024-03-10", [("Consultation", "consult", 1, 1500), ("Medication", "pharmacy", 1, 2500)])
    truth.append(dict(type="waiting_period", claims=[j], note="Loss 9 days after policy start; 30-day waiting period"))

    k, bk, pk = claim("P-100", "M2010", "Sunrise Clinic", "2025-02-14", [("Consultation", "consult", 1, 1500)])
    truth.append(dict(type="policy_period", claims=[k], note="Loss after policy end 2024-12-31"))

    l_, bl, pl = claim("P-200", "M2011", "Green Valley Hospital", "2024-07-22", [("Surgery fee", "surgery", 1, 70000), ("Medication", "pharmacy", 1, 10000)], proposed=80000)
    truth.append(dict(type="coverage_limit", claims=[l_], note="Policy limit 50000 but 80000 proposed"))

    m, bm, pm = claim("P-100", "M2012", "Apollo Care", "2024-08-20", [("Ambulance", "ambulance", 1, 5000), ("Consultation", "consult", 1, 1000)])
    truth.append(dict(type="sub_limit", claims=[m], excess=2000, note="Ambulance sub-limit 3000"))

    n_, bn, pn = claim("P-100", "M2013", "City General Hospital", "2024-09-30", [("Surgery fee", "surgery", 1, 20000)])
    pays.append(dict(pays[-1]) | {"payment_id": f"PAY-{n_}-B", "payment_date": "20/10/2024"})
    truth.append(dict(type="duplicate_payment", claims=[n_], leakage=round(pn, 2), note="Same payment issued twice"))

    o, bo, po = claim("P-100", "M2014", "Sunrise Clinic", "2024-10-10", [("Consultation", "consult", 1, 1000)], bank="ACC555000111")
    p_, bp, pp = claim("P-100", "M2015", "Apollo Care", "2024-10-11", [("Consultation", "consult", 1, 1100)], bank="ACC555000111")
    truth.append(dict(type="related_party", claims=[o, p_], note="Different claimants share a bank account"))

    return dict(claims=pd.DataFrame(claims), policies=pd.DataFrame(POLICIES), invoice_lines=pd.DataFrame(lines), payments=pd.DataFrame(pays),
                documents=pd.DataFrame(docs)), truth


JUDGE_RULES = """# Custom rules (free text)
1. Room rent is limited to 5000 per day.
2. Excluded items: cosmetic, vitamins, gloves
3. Near duplicate invoices within 3 days and 2% amount tolerance must be reviewed
4. Sub-limit for ambulance is 3000
5. Required documents: invoice, discharge summary
"""


def write():
    OUT.mkdir(parents=True, exist_ok=True)
    bundle, truth = build()
    for k, df in bundle.items():
        df.to_csv(OUT / f"{k}.csv", index=False)
    (OUT / "my_rules.txt").write_text(JUDGE_RULES, encoding="utf-8")
    (OUT / "ground_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    return bundle, truth


if __name__ == "__main__":
    b, t = write()
    print({k: len(v) for k, v in b.items()}, len(t), "planted")
