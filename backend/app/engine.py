"""Detection engine: rules -> findings (confirmed / suspicious / clarification / lookalike / under)."""
import re
from collections import defaultdict

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from . import aggregate as AG
from . import twin as T
from .ingest import Dataset, norm_text
from .rules_dsl import globals_from_rules

KLASS_RANK = {"confirmed": 0, "suspicious": 1, "clarification": 2, "under": 3, "lookalike": 4}
GENERIC_DESC = {"", "claim no line detail", "claim", "outpatient", "inpatient"}


def _f(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def fd(ts):
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%d")


def money(x):
    return f"{x:,.2f}"


class Engine:
    def __init__(self, ds: Dataset, rules: list):
        self.ds = ds
        self.rules = [r for r in rules if r.get("enabled", True)]
        self.by_type = defaultdict(list)
        for r in self.rules:
            self.by_type[r["type"]].append(r)
        self.G = globals_from_rules(self.rules)
        self.findings = []
        self.lookalikes = []
        self.lines = ds.lines
        self.L = {u: i for i, u in enumerate(self.lines["uid"])}
        self.pol = ds.policies.set_index("policy_id") if len(ds.policies) else None
        self.claims = ds.claims.set_index("claim_id", drop=False)
        self.claim_lines = {c: list(v) for c, v in self.lines.groupby("claim_id", sort=False).indices.items()}
        self.eff = {}
        self.not_run = []
        self.covered_copies = {}

    # ------------------------------------------------------------ helpers
    def snap(self, i):
        r = self.lines.iloc[i] if not isinstance(i, pd.Series) else i
        return {"claim_id": r["claim_id"], "invoice_no": r["invoice_no"], "vendor": r["vendor"], "date": fd(r["date"]),
                "description": r["description"], "quantity": _f(r["quantity"]), "amount": _f(r["amount"]), "source": r["_src"], "uid": r["uid"]}

    def add(self, rule, klass, title, claims, uids, units, summary, evidence=None, calc=None, clause=None, legit=None,
            confidence=0.9, amount=None, at_risk=None, extra=None):
        f = {"rule_id": rule["id"], "rule_type": rule["type"], "rule_name": rule["name"], "rule_source": rule.get("source", "default"),
             "klass": klass, "title": title, "claim_ids": sorted(set(claims)), "uids": uids, "units": units,
             "amount": round(amount if amount is not None else sum(units.values()), 2) if (units or amount is not None) else None,
             "summary": summary, "evidence": evidence or [], "calc": calc or [], "clause": clause, "legit": legit,
             "confidence": confidence, "status": "open", "at_risk": at_risk, "also_matched": [], "missing": [], "next_step": None}
        if extra:
            f.update(extra)
        self.findings.append(f)
        return f

    def rule_klass(self, rule, default):
        return rule.get("klass") or default

    def eff_for(self, cid):
        if cid in self.eff:
            return self.eff[cid]
        G = self.G
        row = self.claims.loc[cid] if cid in self.claims.index else None
        pol = None
        if row is not None and self.pol is not None and row["policy_id"] in self.pol.index:
            pol = self.pol.loc[row["policy_id"]]

        def pick(field, gval, mode="min"):
            v = _f(pol[field]) if pol is not None and field in pol.index else None
            if v is None:
                return gval
            if gval is None:
                return v
            return min(v, gval) if mode == "min" else v

        subs = dict(pol["sub_limits_d"]) if pol is not None and isinstance(pol.get("sub_limits_d"), dict) else {}
        for k, v in G["sub_limits"].items():
            subs[k] = min(v, subs.get(k, v))
        excl = list(pol["exclusions_l"]) if pol is not None and isinstance(pol.get("exclusions_l"), list) else []
        excl = sorted(set(excl + G["exclusions"]))
        docs = list(pol["required_docs_l"]) if pol is not None and isinstance(pol.get("required_docs_l"), list) else []
        eff = {"policy_found": pol is not None, "policy_id": row["policy_id"] if row is not None else "",
               "coverage_limit": pick("coverage_limit", G["coverage_limit"]), "deductible": pick("deductible", G["deductible"], "pol"),
               "copay_pct": pick("copay_pct", G["copay_pct"], "pol"), "room_limit": pick("room_limit_per_day", G["room_limit"]),
               "waiting_days": pick("waiting_days", G["waiting_days"], "pol"), "sub_limits": subs, "exclusions": excl,
               "required_docs": sorted(set(docs + G["required_docs"])),
               "start": pol["start_date"] if pol is not None and "start_date" in pol.index else pd.NaT,
               "end": pol["end_date"] if pol is not None and "end_date" in pol.index else pd.NaT}
        self.eff[cid] = eff
        return eff

    def prio(self, f):
        return (KLASS_RANK[f["klass"]], -(f["amount"] or 0))

    # ------------------------------------------------------------ DUP-01 duplicate invoice
    def dup_invoice(self, rule):
        L = self.lines
        sub = L[L["inv_norm"].ne("")]
        if sub.empty:
            return
        tol = rule["params"].get("amount_tolerance_pct", 1.0) / 100
        key = sub["vendor_norm"] + "|" + sub["inv_norm"]
        multi = sub.groupby(key)["claim_id"].nunique()
        for k in multi[multi > 1].index:
            grp = sub[key == k]
            order = grp.sort_values(["date"], na_position="last", kind="stable")
            claims = list(dict.fromkeys(order["claim_id"]))
            orig = claims[0]
            orig_lines = list(grp[grp["claim_id"] == orig].index)
            for dc in claims[1:]:
                dl = list(grp[grp["claim_id"] == dc].index)
                avail = orig_lines[:]
                matched, unmatched = [], []
                for i in dl:
                    a = L.at[i, "amount"]
                    hit = None
                    for j in avail:
                        b = L.at[j, "amount"]
                        if abs(a - b) <= max(0.01, tol * max(abs(a), abs(b))) and (
                                L.at[i, "synthetic"] or fuzz.token_set_ratio(L.at[i, "desc_norm"], L.at[j, "desc_norm"]) >= 80):
                            hit = j
                            break
                    if hit is not None:
                        avail.remove(hit)
                        matched.append((i, hit))
                    else:
                        unmatched.append(i)
                inv = L.at[dl[0], "invoice_no"]
                vendor = L.at[dl[0], "vendor"]
                if matched:
                    units = {f"L:{L.at[i, 'uid']}": float(L.at[i, "amount"]) for i, _ in matched}
                    ev = []
                    for i, j in matched:
                        ev += [dict(self.snap(j), role="original"), dict(self.snap(i), role="duplicate")]
                    amt = sum(units.values())
                    self.add(rule, self.rule_klass(rule, "confirmed"), f"Invoice {inv} already claimed under {orig}",
                             [orig, dc], [L.at[i, "uid"] for i, _ in matched], units,
                             f"Invoice {inv} from {vendor or 'the same provider'} was submitted under claim {orig} and again under claim {dc}. "
                             f"{len(matched)} matching line(s) totalling {money(amt)} are paid twice; the potential overpayment is counted once.",
                             ev, [{"label": "Overpayment (counted once)", "value": round(amt, 2)}],
                             clause="Policy condition: each invoice/charge may be reimbursed only once.",
                             legit="Legitimate only if the invoice was part-paid under the first claim and the balance is resubmitted; verify payments on " + orig + ".",
                             confidence=0.97, extra={"cluster": f"INV:{k}"})
                if unmatched:
                    units = {f"L:{L.at[i, 'uid']}": float(L.at[i, "amount"]) for i in unmatched}
                    self.add(rule, "suspicious", f"Invoice number {inv} reused under {dc} with different lines",
                             [orig, dc], [L.at[i, "uid"] for i in unmatched], units,
                             f"Invoice number {inv} appears in claims {orig} and {dc}, but {len(unmatched)} line(s) in {dc} do not match the original. "
                             "Could be a typo in the reference or a genuinely different bill; human review required.",
                             [dict(self.snap(i), role="suspect line") for i in unmatched[:6]] + [dict(self.snap(j), role="original line") for j in orig_lines[:6]],
                             clause="Policy condition: each invoice may be reimbursed only once.",
                             legit="A reused/typo'd invoice number on a different treatment.", confidence=0.6, extra={"cluster": f"INV:{k}"})

    # ------------------------------------------------------------ DUP-02/03 + lookalikes
    def dup_lines(self, rule02, rule03, rule_lk):
        L = self.lines
        p3 = (rule03 or {"params": {}})["params"]
        window = p3.get("date_window_days", 3)
        tol = p3.get("amount_tolerance_pct", 2.0) / 100
        simthr = p3.get("similarity", 85)
        recurring = (rule_lk or {"params": {"recurring_terms": []}})["params"].get("recurring_terms", [])
        keycols = L["c_claimant_id"].fillna("").astype(str) + "|" + L["vendor_norm"]
        dupmask = keycols.duplicated(keep=False)
        if not dupmask.any():
            return
        best = {}
        lk_groups = {}
        idx_all = np.flatnonzero(dupmask.to_numpy())
        dates = L["date"].to_numpy()
        amounts = L["amount"].to_numpy()
        descs = L["desc_norm"].to_numpy()
        claims = L["claim_id"].to_numpy()
        invs = L["inv_norm"].to_numpy()
        synth = L["synthetic"].to_numpy()
        groups = pd.Series(idx_all).groupby(keycols.to_numpy()[idx_all])
        for _, gi in groups:
            ids = list(gi.to_numpy())
            ids.sort(key=lambda i: (pd.isna(dates[i]), dates[i] if not pd.isna(dates[i]) else 0, i))
            n = len(ids)
            for a in range(n):
                i = ids[a]
                for b in range(a + 1, min(n, a + 80)):
                    j = ids[b]
                    if not pd.isna(dates[i]) and not pd.isna(dates[j]):
                        dd = abs((dates[j] - dates[i]) / np.timedelta64(1, "D"))
                        if dd > 60:
                            break
                    else:
                        dd = None
                    ai, aj = amounts[i], amounts[j]
                    mx = max(abs(ai), abs(aj), 0.01)
                    exact_amt = abs(ai - aj) < 0.005
                    near_amt = abs(ai - aj) <= tol * mx
                    if not near_amt:
                        continue
                    both_generic = descs[i] in GENERIC_DESC and descs[j] in GENERIC_DESC
                    sim = 100 if both_generic else fuzz.token_set_ratio(descs[i], descs[j])
                    if sim < simthr:
                        continue
                    same_claim = claims[i] == claims[j]
                    same_inv = invs[i] != "" and invs[i] == invs[j]
                    if same_inv and not same_claim:
                        continue  # covered by DUP-01
                    diff_inv = invs[i] != "" and invs[j] != "" and invs[i] != invs[j]
                    rec = any(t in descs[i] for t in recurring) if recurring else False
                    generic = both_generic or (synth[i] and synth[j])
                    if dd is not None and dd >= 1 and exact_amt and sim >= 95 and (rec or dd > window):
                        if not generic and dd <= 60:
                            lk_groups.setdefault((keycols.iat[i], descs[i], round(float(ai), 2)), set()).update([i, j])
                        continue
                    if dd is not None and dd > window:
                        continue
                    if dd is None and not (exact_amt and sim >= 98):
                        continue
                    exact = exact_amt and sim >= 98 and dd == 0
                    if exact and rule02:
                        klass = "confirmed" if (same_claim or same_inv or (not diff_inv and not generic)) else "suspicious"
                        if rec and same_claim:
                            klass = "suspicious"
                        r = rule02
                        score = 3 if klass == "confirmed" else 2
                    elif rule03:
                        klass, r, score = "suspicious", rule03, 1
                    else:
                        continue
                    klass = self.rule_klass(r, klass) if r["klass"] != klass and r.get("source") == "judge" else klass
                    cand = (score, -(dd or 0), 1.0 if exact else sim / 100)
                    # original = earlier row, copy = later
                    o, c = (i, j)
                    if cand > best.get(c, ((-1,),))[0]:
                        best[c] = (cand, o, klass, r, dd, exact, same_claim, same_inv, diff_inv, sim)
        grouped = {}
        for c, tup in best.items():
            o, klass, r = tup[1], tup[2], tup[3]
            grouped.setdefault((L.at[o, "claim_id"], L.at[c, "claim_id"], klass, r["id"]), []).append((c, tup))
        for (oc, cc, klass, _rid), items in grouped.items():
            r = items[0][1][3]
            same_claim = oc == cc
            units, ev, uids, notes, calc = {}, [], [], [], []
            exact_all = all(t[5] for _, t in items)
            for c, (cand, o, kl, rr, dd, exact, sc, si, diff_inv, sim) in items:
                a = float(L.at[c, "amount"])
                units[f"L:{L.at[c, 'uid']}"] = a
                uids += [L.at[o, "uid"], L.at[c, "uid"]]
                ev += [dict(self.snap(o), role="original"), dict(self.snap(c), role="duplicate")]
                if not exact:
                    d = []
                    if abs(L.at[o, "amount"] - a) > 0.005:
                        d.append(f"amount {money(L.at[o, 'amount'])} vs {money(a)}")
                    if dd:
                        d.append(f"{int(dd)} day(s) apart")
                    if diff_inv:
                        d.append(f"different reference ({L.at[o, 'invoice_no']} vs {L.at[c, 'invoice_no']})")
                    if sim < 100:
                        d.append(f"description similarity {sim:.0f}%")
                    notes.append(f"'{L.at[c, 'description'] or 'line'}': " + "; ".join(d))
                calc.append({"label": f"Repeated charge: {L.at[c, 'description'] or 'line'}", "value": round(a, 2)})
            tot = sum(units.values())
            where = f"within claim {cc}" if same_claim else f"across claims {oc} and {cc}"
            n = len(items)
            if exact_all:
                title = f"Exact duplicate charge{'s' if n > 1 else ''} {where}"
                summ = f"{n} identical charge(s) from the same provider appear twice {where} (total {money(tot)}); the overpayment is counted once."
            else:
                title = f"Near-duplicate charge{'s' if n > 1 else ''} {where}"
                summ = f"{n} charge(s) near-identical to earlier ones {where} ({' | '.join(notes)}). Minor drift in date/amount/reference is a common resubmission pattern."
            calc.append({"label": "Potential overpayment (counted once)", "value": round(tot, 2)})
            self.add(r, klass, title, [oc, cc], list(dict.fromkeys(uids)), units, summ, ev, calc,
                     clause="Policy condition: the same expense cannot be reimbursed twice.",
                     legit="Could be genuine, separate services with identical pricing (e.g. repeat session); confirm with treatment notes.",
                     confidence=0.95 if klass == "confirmed" else 0.65, extra={"cluster": f"LN:{oc}:{cc}"})
        if rule_lk:
            for (k, d, a), members in list(lk_groups.items())[:150]:
                ms = sorted(members, key=lambda x: (str(L.at[x, "date"]), x))
                self.lookalikes.append({
                    "rule_id": rule_lk["id"], "title": f"Recurring '{L.at[ms[0], 'description'] or 'service'}' on {len(ms)} different dates: not flagged",
                    "claim_ids": sorted({L.at[m, "claim_id"] for m in ms}), "amount_each": a,
                    "evidence": [self.snap(m) for m in ms[:8]],
                    "reason": "Same service and price on distinct dates is consistent with a legitimate repeated treatment (e.g. physiotherapy). Not rejected; each date is a separate incident."})

    # ------------------------------------------------------------ DUP-04 payments
    def dup_payments(self, rule):
        P = self.ds.payments
        if not len(P):
            self.not_run.append("DUP-04: no payments/settlement file supplied")
            return
        key = np.where(P["inv_norm"] != "", "I:" + P["inv_norm"], "C:" + P["claim_id"]) + "|" + P["amount"].round(2).astype(str)
        dup_inv_claims = {f["claim_ids"][-1] for f in self.findings if f["rule_type"] == "duplicate_invoice" and f["klass"] == "confirmed"}
        for k, g in P.groupby(key):
            if len(g) < 2:
                continue
            g = g.sort_values("payment_date", na_position="last", kind="stable")
            first = g.iloc[0]
            for _, r in g.iloc[1:].iterrows():
                if r["claim_id"] != first["claim_id"] and r["claim_id"] in dup_inv_claims:
                    continue  # the same overpayment is already counted by the duplicate-invoice finding
                same_ref = (r["ref_norm"] != "" and r["ref_norm"] == first["ref_norm"]) or (r["payment_id"] != "" and r["payment_id"] == first["payment_id"])
                klass = "confirmed" if same_ref or r["claim_id"] == first["claim_id"] and r["inv_norm"] != "" else "suspicious"
                amt = float(r["amount"])
                self.add(rule, klass, f"Payment of {money(amt)} made twice" + (f" for invoice {r['invoice_no']}" if r["invoice_no"] else ""),
                         [first["claim_id"], r["claim_id"]], [], {f"X:pay:{r['_src']}": amt},
                         f"The same amount was paid for the same {'invoice' if r['inv_norm'] else 'claim'} on {fd(first['payment_date']) or 'n/a'} and {fd(r['payment_date']) or 'n/a'} "
                         f"({first['method'] or 'method n/a'} / {r['method'] or 'method n/a'}).",
                         [{"claim_id": first["claim_id"], "invoice_no": first["invoice_no"], "date": fd(first["payment_date"]), "amount": float(first["amount"]), "description": f"ref {first['reference']}", "source": first["_src"], "role": "original payment"},
                          {"claim_id": r["claim_id"], "invoice_no": r["invoice_no"], "date": fd(r["payment_date"]), "amount": amt, "description": f"ref {r['reference']}", "source": r["_src"], "role": "repeat payment"}],
                         clause="Settlement condition: one payment per approved amount.",
                         legit="Instalment or supplementary payment: check the approved settlement schedule.", confidence=0.9 if klass == "confirmed" else 0.6)

    # ------------------------------------------------------------ DUP-05 duplicate claims
    def dup_claims(self, rule):
        C = self.ds.claims
        tol = rule["params"].get("amount_tolerance_pct", 1.0) / 100
        dr = self.ds.dup_claim_rows
        if len(dr):
            for _, r in dr.iterrows():
                orig = C[C["claim_id"] == r["claim_id"]].iloc[0]
                amt = _f(r["claimed_amount"]) or _f(r["proposed_settlement"]) or 0.0
                if amt <= 0:
                    continue
                same = abs((amt) - (_f(orig["claimed_amount"]) or 0)) <= max(0.01, tol * amt)
                self.add(rule, "confirmed" if same else "suspicious", f"Claim ID {r['claim_id']} submitted twice",
                         [r["claim_id"]], [], {f"X:claimrow:{r['_src']}": amt},
                         f"Claim {r['claim_id']} appears again at {r['_src']} " + ("with the same amount." if same else "with a different amount.") + " A repeated claim record can be paid twice.",
                         [{"claim_id": r["claim_id"], "amount": amt, "source": r["_src"], "role": "repeated record", "description": str(r.get("claim_type", "")), "date": fd(r.get("loss_date"))},
                          {"claim_id": orig["claim_id"], "amount": _f(orig["claimed_amount"]), "source": orig["_src"], "role": "first record", "description": str(orig.get("claim_type", "")), "date": fd(orig.get("loss_date"))}],
                         clause="Each claim reference may be settled once.", legit="Corrected resubmission after rejection; check claim status history.",
                         confidence=0.9 if same else 0.6)
        ok = C[C["loss_date"].notna() & C["claimant_id"].ne("") & C["claimed_amount"].notna()]
        if ok.empty:
            return
        key = ok["claimant_id"] + "|" + ok["provider"].map(norm_text) + "|" + ok["loss_date"].dt.strftime("%Y-%m-%d")
        d = key.duplicated(keep=False)
        for _, g in ok[d].groupby(key[d]):
            g = g.sort_values("claim_date", na_position="last", kind="stable")
            o = g.iloc[0]
            for _, c in g.iloc[1:].iterrows():
                if abs(c["claimed_amount"] - o["claimed_amount"]) > max(0.01, tol * max(c["claimed_amount"], o["claimed_amount"])):
                    continue
                uids = [L for L in (self.lines.loc[self.claim_lines.get(c["claim_id"], []), "uid"] if c["claim_id"] in self.claim_lines else [])]
                free = [u for u in uids if u not in self.covered_copies]
                if not free:
                    continue
                units = {f"L:{u}": float(self.lines.at[self.L[u], "amount"]) for u in free}
                self.add(rule, self.rule_klass(rule, "suspicious"), f"Same incident claimed twice: {o['claim_id']} and {c['claim_id']}",
                         [o["claim_id"], c["claim_id"]], free, units,
                         f"Claims {o['claim_id']} and {c['claim_id']} share claimant, provider, loss date ({fd(o['loss_date'])}) and amount ({money(c['claimed_amount'])}) but have different reference numbers.",
                         [{"claim_id": x["claim_id"], "amount": float(x["claimed_amount"]), "date": fd(x["loss_date"]), "description": f"{x['provider']} / {x['claim_type']}", "invoice_no": x["invoice_no"], "source": x["_src"], "role": r} for x, r in ((o, "earlier claim"), (c, "later claim"))],
                         clause="Policy condition: one indemnity per incident.", legit="Two distinct incidents on the same day at the same provider (rare); verify documents.",
                         confidence=0.7, extra={"cluster": f"CL:{o['claim_id']}"})

    # ------------------------------------------------------------ exclusions / limits
    def line_rules(self):
        L = self.lines
        excl_rule = next(iter(self.by_type.get("exclusion", [])), None)
        sub_rule = next(iter(self.by_type.get("sub_limit", [])), None)
        room_rule = next(iter(self.by_type.get("room_limit", [])), None)
        if not any((excl_rule, sub_rule, room_rule)):
            return
        if not self.ds.has["policies"] and not (self.G["exclusions"] or self.G["sub_limits"] or self.G["room_limit"]):
            self.not_run.append("EXC-01/LIM-02/LIM-03: no policy terms supplied (upload a policy file or supply the rules)")
            return
        excl_rule2 = {**excl_rule, "id": excl_rule["id"]} if excl_rule else None
        cache_terms = {}
        for cid, idxs in self.claim_lines.items():
            if cid == "UNLINKED" and not len(idxs):
                continue
            eff = self.eff_for(cid)
            sub_amt = defaultdict(list)
            for i in idxs:
                text = (L.at[i, "desc_norm"] + " | " + L.at[i, "cat_norm"]).strip()
                amt = float(L.at[i, "amount"])
                if excl_rule:
                    for t in eff["exclusions"]:
                        tn = cache_terms.setdefault(t, re.compile(r"(?<![a-z0-9])" + re.escape(norm_text(t)) + r"s?(?![a-z0-9])"))
                        if norm_text(t) and tn.search(text):
                            self.add(excl_rule, "confirmed", f"Excluded item '{t}' ({money(amt)})", [cid], [L.at[i, "uid"]], {f"L:{L.at[i, 'uid']}": amt},
                                     f"Line '{L.at[i, 'description']}' matches the policy exclusion '{t}' and is not payable.",
                                     [dict(self.snap(i), role="excluded line")],
                                     [{"label": "Billed", "value": round(amt, 2)}, {"label": "Payable", "value": 0}, {"label": "Overpayment", "value": round(amt, 2)}],
                                     clause=f"Exclusion '{t}' (policy {eff['policy_id'] or 'rules'}, {excl_rule['id']}).",
                                     legit="The item may be a medically necessary exception or a different item with similar wording.", confidence=0.9)
                            break
                if sub_rule:
                    for k in eff["sub_limits"]:
                        if norm_text(k) and norm_text(k) in text:
                            sub_amt[k].append(i)
                            break
                if room_rule and eff["room_limit"] and re.search(r"\broom\b", text):
                    up = _f(L.at[i, "unit_price"])
                    qty = L.at[i, "quantity"] if L.at[i, "quantity_given"] else None
                    if up is None and qty:
                        up = amt / qty
                    if up and qty and up > eff["room_limit"] + 0.005:
                        ex = (up - eff["room_limit"]) * qty
                        self.add(room_rule, "confirmed", f"Room rent above daily limit ({money(up)} vs {money(eff['room_limit'])})", [cid], [L.at[i, "uid"]],
                                 {f"L:{L.at[i, 'uid']}": ex},
                                 f"Room charge {money(up)}/day for {qty:g} day(s) exceeds the daily room limit {money(eff['room_limit'])}.",
                                 [dict(self.snap(i), role="room line")],
                                 [{"label": "Daily rate", "value": round(up, 2)}, {"label": "Allowed per day", "value": round(eff["room_limit"], 2)},
                                  {"label": f"Excess x {qty:g} day(s)", "value": round(ex, 2)}],
                                 clause=f"Room rent limit {money(eff['room_limit'])}/day ({room_rule['id']}).", legit="Upgrade accepted by insurer / proportionate deduction clause.", confidence=0.9)
            for k, ids in sub_amt.items():
                cap = eff["sub_limits"][k]
                run, units, ev = 0.0, {}, []
                for i in ids:
                    a = float(L.at[i, "amount"])
                    over = max(0.0, run + a - max(cap, run)) if run + a > cap else 0.0
                    if over > 0:
                        units[f"L:{L.at[i, 'uid']}"] = over
                        ev.append(dict(self.snap(i), role="over cap"))
                    run += a
                if units:
                    tot = sum(units.values())
                    self.add(sub_rule, "confirmed", f"Sub-limit for '{k}' exceeded by {money(tot)}", [cid], list(u[2:] for u in units), units,
                             f"Claimed '{k}' charges total {money(run)} against a sub-limit of {money(cap)}.", ev,
                             [{"label": f"Total claimed for '{k}'", "value": round(run, 2)}, {"label": "Sub-limit", "value": round(cap, 2)}, {"label": "Excess", "value": round(tot, 2)}],
                             clause=f"Sub-limit '{k}' = {money(cap)} (policy {eff['policy_id'] or 'rules'}, {sub_rule['id']}).", legit="Sub-limit may be per-event vs per-year; check the schedule.", confidence=0.9)

    # ------------------------------------------------------------ amount mismatch
    def amount_mismatch(self, rule):
        L = self.lines
        p = rule["params"]
        tp, ta = p.get("tolerance_pct", 0.5) / 100, p.get("tolerance_abs", 1.0)
        has_up = L["unit_price"].notna() & L["quantity_given"]
        calc = L["quantity"] * L["unit_price"]
        diff = L["amount"] - calc
        bad = has_up & (diff.abs() > np.maximum(ta, tp * calc.abs()))
        for i in np.flatnonzero(bad.to_numpy())[:500]:
            d = float(diff.iat[i])
            cid = L.at[i, "claim_id"]
            if d > 0:
                self.add(rule, "confirmed", f"Line total exceeds qty x unit price by {money(d)}", [cid], [L.at[i, "uid"]], {f"L:{L.at[i, 'uid']}": d},
                         f"{L.at[i, 'quantity']:g} x {money(L.at[i, 'unit_price'])} = {money(calc.iat[i])}, but the line is billed at {money(L.at[i, 'amount'])}.",
                         [dict(self.snap(i), role="line")], [{"label": "Qty x unit price", "value": round(float(calc.iat[i]), 2)}, {"label": "Billed", "value": round(float(L.at[i, 'amount']), 2)}, {"label": "Excess", "value": round(d, 2)}],
                         clause="Charges payable at agreed unit rate x quantity.", legit="A surcharge or tax not itemised.", confidence=0.85)
            else:
                self.add(rule, "under", f"Line billed below qty x unit price by {money(-d)}", [cid], [L.at[i, "uid"]], {}, f"Line under-billed vs quantity x rate.",
                         [dict(self.snap(i), role="line")], amount=-d, confidence=0.7)
        # invoice total vs line sum
        sub = L[L["invoice_total"].notna() & L["inv_norm"].ne("")]
        for (cid, inv), g in sub.groupby(["claim_id", "inv_norm"]):
            tot = float(g["invoice_total"].iloc[0])
            s = float(g["amount"].sum())
            if abs(s - tot) > max(ta, tp * tot):
                over = s - tot
                if over > 0:
                    self.add(rule, "suspicious", f"Invoice {g['invoice_no'].iloc[0]} lines exceed the stated invoice total by {money(over)}", [cid], list(g["uid"]),
                             {f"C:{cid}:invtotal:{inv}": over}, f"Lines sum to {money(s)} but the invoice total is {money(tot)}.",
                             [dict(self.snap(i), role="line") for i in g.index[:8]], [{"label": "Sum of lines", "value": round(s, 2)}, {"label": "Invoice total", "value": round(tot, 2)}, {"label": "Difference", "value": round(over, 2)}],
                             clause="Claimed amount must reconcile to the invoice.", legit="Discount or round-off applied at invoice level.", confidence=0.7)
        if self.ds.has["real_lines"]:
            C = self.ds.claims
            sums = L.groupby("claim_id")["amount"].sum()
            for _, c in C[C["claimed_amount"].notna()].iterrows():
                s = sums.get(c["claim_id"])
                if s is not None and abs(s - c["claimed_amount"]) > max(ta, tp * c["claimed_amount"]):
                    self.add(rule, "suspicious", f"Claim {c['claim_id']}: claimed total differs from invoice lines by {money(c['claimed_amount'] - s)}", [c["claim_id"]], [], {},
                             f"Claim header says {money(c['claimed_amount'])}; supporting lines total {money(s)}.", [],
                             [{"label": "Claimed", "value": round(float(c['claimed_amount']), 2)}, {"label": "Lines total", "value": round(float(s), 2)}],
                             clause="Claimed amount must be supported by invoice lines.", legit="Lines missing from the bundle.", confidence=0.7,
                             amount=max(0.0, float(c["claimed_amount"] - s)) or None)

    # ------------------------------------------------------------ settlement / limit / period (twin-level)
    def twin_level(self, rset):
        by = self.by_type
        if not (by.get("settlement") or by.get("coverage_limit") or by.get("policy_period")):
            return
        C = self.claims
        sets, lims, pers = (by.get("settlement") or [None])[0], (by.get("coverage_limit") or [None])[0], (by.get("policy_period") or [None])[0]
        for cid, idxs in self.claim_lines.items():
            if cid not in C.index:
                continue
            eff = self.eff_for(cid)
            billed = float(self.lines.iloc[idxs]["amount"].sum())
            P = _f(C.at[cid, "proposed_settlement"])
            loss = C.at[cid, "loss_date"]
            if pd.isna(loss):
                d = self.lines.iloc[idxs]["date"].dropna()
                loss = d.min() if len(d) else pd.NaT
            # period
            if pers and eff["policy_found"]:
                st, en = eff["start"], eff["end"]
                viol = None
                if pd.notna(loss):
                    if pd.notna(st) and loss < st:
                        viol = f"loss date {fd(loss)} is before policy start {fd(st)}"
                    elif pd.notna(en) and loss > en:
                        viol = f"loss date {fd(loss)} is after policy end {fd(en)}"
                    elif pd.notna(st) and eff["waiting_days"] and (loss - st).days < eff["waiting_days"]:
                        viol = f"loss date {fd(loss)} falls within the {int(eff['waiting_days'])}-day waiting period from {fd(st)}"
                elif pd.notna(st) or pd.notna(en):
                    self.add(self.by_type["incomplete_evidence"][0] if by.get("incomplete_evidence") else pers, "clarification", f"Claim {cid}: loss date missing, policy period cannot be verified", [cid], [], {},
                             "No loss/service date is available, so coverage period and waiting period cannot be checked. No leakage amount is asserted.", [],
                             at_risk=P if P is not None else billed, confidence=0.5, extra={"missing": ["loss date"], "next_step": "Request the date of loss/treatment from the claimant or provider."})
                if viol:
                    amt = P if P is not None else T.formula(billed, eff)[0]
                    self.add(pers, self.rule_klass(pers, "confirmed"), f"Claim {cid} outside cover: {viol}", [cid], [], {f"T:{cid}": amt},
                             f"Policy {eff['policy_id']}: {viol}. The claim is not payable under the policy period conditions.", [],
                             [{"label": "Policy period", "value": f"{fd(st)} to {fd(en)}"}, {"label": "Loss date", "value": fd(loss)}, {"label": "Payable", "value": 0}, {"label": "Overpayment", "value": round(amt, 2)}],
                             clause=f"Policy {eff['policy_id']} period/waiting-period condition ({pers['id']}).",
                             legit="Continuous renewal not reflected in the supplied policy dates.", confidence=0.9, amount=amt,
                             extra={"skip_key": "policy_period"})
                    continue
            if not T.has_terms(eff):
                continue
            nocap, steps = T.formula(billed, eff, frozenset({"coverage_limit"}))
            lim = eff["coverage_limit"]
            if P is not None and sets:
                tol = max(sets["params"].get("tolerance_abs", 1.0), sets["params"].get("tolerance_pct", 0.5) / 100 * max(nocap, 1))
                capped = min(nocap, lim) if lim else nocap
                if P > nocap + tol:
                    d = P - nocap
                    self.add(sets, self.rule_klass(sets, "confirmed"), f"Settlement miscalculated: paid {money(P)}, policy terms give {money(nocap)}", [cid], [], {f"T:{cid}": d},
                             f"Recalculating billed {money(billed)} with the policy deductible/co-payment gives {money(nocap)}, but the proposed settlement is {money(P)}.", [],
                             [{"label": s["label"], "value": s["value"]} for s in steps] + [{"label": "Proposed settlement", "value": round(P, 2)}, {"label": "Overpayment", "value": round(d, 2)}],
                             clause=f"Deductible {money(eff['deductible'] or 0)} and co-payment {eff['copay_pct'] or 0:g}% (policy {eff['policy_id'] or 'rules'}, {sets['id']}).",
                             legit="A benefit rider or insurer-approved exception.", confidence=0.9, amount=d, extra={"skip_key": "settlement"})
                elif P < min(nocap, lim or nocap) - tol:
                    d = min(nocap, lim or nocap) - P
                    self.add(sets, "under", f"Under-settlement: paid {money(P)}, policy terms give {money(capped)}", [cid], [], {}, f"Proposed settlement is below the policy entitlement by {money(d)}. Not leakage, but a customer-fairness risk.", [],
                             [{"label": s["label"], "value": s["value"]} for s in steps] + [{"label": "Proposed", "value": round(P, 2)}], clause=sets["name"], confidence=0.8, amount=d)
            if lims and lim:
                base = min(P, nocap) if P is not None else nocap
                if base > lim + 0.01 and (P is None or P > lim + 0.01):
                    ex = base - lim
                    self.add(lims, self.rule_klass(lims, "confirmed"), f"Coverage limit {money(lim)} exceeded by {money(ex)}", [cid], [], {f"T:{cid}": ex},
                             f"Payable amount {money(base)} exceeds the policy coverage limit {money(lim)}.", [],
                             [{"label": "Payable before cap", "value": round(base, 2)}, {"label": "Coverage limit", "value": round(lim, 2)}, {"label": "Excess", "value": round(ex, 2)}],
                             clause=f"Coverage limit {money(lim)} (policy {eff['policy_id'] or 'rules'}, {lims['id']}).", legit="Restoration/top-up benefit not shown in the policy file.", confidence=0.9, amount=ex,
                             extra={"skip_key": "coverage_limit"})

    # ------------------------------------------------------------ documents / clarification
    def documents(self, rule):
        D = self.ds.documents
        if not self.ds.has["documents"]:
            self.not_run.append("DOC-01: no document inventory supplied")
            return
        have = D.groupby("claim_id")["doc_type"].apply(set).to_dict()
        for cid in self.claims.index:
            req = list(rule["params"].get("required") or []) + self.eff_for(cid)["required_docs"]
            req = sorted(set(norm_text(r) for r in req if r))
            if not req:
                continue
            got = have.get(cid, set())
            miss = [r for r in req if not any(norm_text(g).replace(" ", "") in r.replace(" ", "") or r.replace(" ", "") in norm_text(g).replace(" ", "") for g in got)]
            if miss:
                P = _f(self.claims.at[cid, "proposed_settlement"]) or _f(self.claims.at[cid, "claimed_amount"])
                self.add(rule, "clarification", f"Claim {cid}: missing {', '.join(miss)}", [cid], [], {},
                         f"Required document(s) not found in the bundle: {', '.join(miss)}. The claim cannot be reliably assessed; no finding is invented.", [],
                         [{"label": "Required", "value": ", ".join(req)}, {"label": "Present", "value": ", ".join(sorted(got)) or "none"}],
                         clause="Claims documentation requirement.", at_risk=P, confidence=0.5,
                         extra={"missing": miss, "next_step": f"Request {', '.join(miss)} from the claimant/provider before settlement."})

    def incomplete(self, rule):
        if self.pol is not None:
            for cid, row in self.claims.iterrows():
                if row["policy_id"] and row["policy_id"] not in self.pol.index:
                    P = _f(row["proposed_settlement"]) or _f(row["claimed_amount"])
                    self.add(rule, "clarification", f"Claim {cid}: policy {row['policy_id']} not supplied", [cid], [], {},
                             "The referenced policy is not in the uploaded coverage data, so limits, exclusions and settlement cannot be assessed. No amount is asserted.", [],
                             at_risk=P, confidence=0.4, extra={"missing": ["policy record"], "next_step": "Provide the policy schedule for " + row["policy_id"]})
        L = self.lines
        sub = L[L["claim_id"] == "UNLINKED"]
        if len(sub):
            self.add(rule, "clarification", f"{len(sub)} invoice line(s) not linked to any claim", [], list(sub["uid"][:50]), {},
                     "These lines have no claim reference, so they cannot be tied to a policy or checked for duplicates reliably.", [dict(self.snap(i), role="unlinked") for i in sub.index[:6]], confidence=0.4,
                     extra={"next_step": "Supply claim IDs for these lines."})

    # ------------------------------------------------------------ timeline
    def timeline(self, rule):
        C = self.ds.claims
        out = 0
        for _, c in C.iterrows():
            issues = []
            if pd.notna(c["claim_date"]) and pd.notna(c["loss_date"]) and c["claim_date"] < c["loss_date"] and (c["loss_date"] - c["claim_date"]).days > 0:
                issues.append(f"claim filed ({fd(c['claim_date'])}) before the loss ({fd(c['loss_date'])})")
            if pd.notna(c["admission_date"]) and pd.notna(c["discharge_date"]) and c["admission_date"] > c["discharge_date"]:
                issues.append(f"admission ({fd(c['admission_date'])}) after discharge ({fd(c['discharge_date'])})")
            if issues and out < 300:
                out += 1
                self.add(rule, self.rule_klass(rule, "suspicious"), f"Claim {c['claim_id']}: timeline inconsistency", [c["claim_id"]], [], {}, "; ".join(issues).capitalize() + ".", [],
                         clause="Chronology of loss, admission, discharge and claim must be consistent.", legit="Data entry swap of dd/mm.", confidence=0.6,
                         extra={"next_step": "Verify the dates against source documents."})
        L = self.lines
        ok = L["invoice_date"].notna() & L["service_date"].notna() & (L["invoice_date"] < L["service_date"] - pd.Timedelta(days=1))
        for i in np.flatnonzero(ok.to_numpy())[:100]:
            self.add(rule, "suspicious", f"Invoice dated before the service ({L.at[i, 'claim_id']})", [L.at[i, "claim_id"]], [L.at[i, "uid"]], {},
                     f"Invoice dated {fd(L.at[i, 'invoice_date'])} precedes the service date {fd(L.at[i, 'service_date'])}.", [dict(self.snap(i), role="line")], confidence=0.55, clause="Invoice should post-date the service.")

    # ------------------------------------------------------------ thresholds (judge supplied)
    def thresholds(self):
        L = self.lines
        for r in self.G["thresholds"]:
            p = r["params"]
            v = p.get("value")
            if v is None:
                continue
            op = str(p.get("op", ">"))
            m = L["amount"] > v if ">" in op else L["amount"] < v
            for i in np.flatnonzero(m.to_numpy())[:200]:
                ex = float(L.at[i, "amount"] - v) if ">" in op else 0.0
                self.add(r, self.rule_klass(r, "suspicious"), f"Line above threshold {money(v)} ({r['id']})", [L.at[i, "claim_id"]], [L.at[i, "uid"]],
                         {f"L:{L.at[i, 'uid']}": ex} if ex else {}, f"Line amount {money(L.at[i, 'amount'])} breaches the rule: {r.get('text') or r['name']}", [dict(self.snap(i), role="line")],
                         clause=r.get("text") or r["name"], confidence=0.7)

    # ------------------------------------------------------------ provider outlier
    def provider_outlier(self, rule):
        L = self.lines
        p = rule["params"]
        seg = np.where(L["synthetic"], L["c_claim_type"].map(norm_text), L["desc_norm"])
        df = pd.DataFrame({"seg": seg, "vendor": L["vendor_norm"], "amount": L["amount"], "claim": L["claim_id"]})
        df = df[(df["vendor"] != "") & (df["seg"] != "")]
        if df.empty:
            return
        stats = df.groupby(["seg", "vendor"])["amount"].agg(["median", "count", "sum"]).reset_index()
        seg_med = stats[stats["count"] >= 3].groupby("seg")["median"].median()
        seg_n = stats.groupby("seg")["vendor"].nunique()
        found = []
        for _, r in stats.iterrows():
            if r["count"] < p.get("min_lines", 8) or seg_n.get(r["seg"], 0) < 4:
                continue
            m = seg_med.get(r["seg"])
            if m and m > 0 and r["median"] / m >= p.get("ratio", 2.5):
                found.append((r["median"] / m, r))
        for ratio, r in sorted(found, key=lambda x: -x[0])[:25]:
            vend = df[(df["seg"] == r["seg"]) & (df["vendor"] == r["vendor"])]
            self.add(rule, "suspicious", f"Provider {r['vendor']}: charges {ratio:.1f}x peer median for '{r['seg'] or 'service'}'", sorted(set(vend["claim"]))[:30], [], {},
                     f"Median charge {money(r['median'])} across {int(r['count'])} lines vs peer median {money(seg_med[r['seg']])}. Flagged for review; this does not imply fraud (specialist centres charge more).",
                     [], [{"label": "Provider median", "value": round(float(r['median']), 2)}, {"label": "Peer median", "value": round(float(seg_med[r['seg']]), 2)}, {"label": "Ratio", "value": round(float(ratio), 2)}],
                     clause="Reasonable and customary charge benchmark (derived from this portfolio).", legit="Specialist or tertiary provider, complex case mix.", confidence=0.5,
                     extra={"next_step": "Review provider's tariff/contract; sample the highest claims."})

    # ------------------------------------------------------------ related party
    def related_party(self, rule):
        C = self.ds.claims
        n = 0
        for col, label in (("bank_account", "bank account"), ("phone", "phone number"), ("address", "address")):
            if col not in C.columns:
                continue
            s = C[C[col].astype(str).str.strip().ne("")]
            for k, g in s.groupby(s[col].astype(str).str.lower().str.replace(r"\s+", "", regex=True)):
                if g["claimant_id"].nunique() >= 2 and n < 50:
                    n += 1
                    self.add(rule, "suspicious", f"{g['claimant_id'].nunique()} different claimants share the same {label}", list(g["claim_id"])[:20], [], {},
                             f"Claims {', '.join(list(g['claim_id'])[:6])} from different claimants use the same {label} ({str(g[col].iloc[0])[:20]}). Could be family members or a broker; review only.", [
                                 {"claim_id": r["claim_id"], "description": f"{label}: {r[col]}", "amount": _f(r["claimed_amount"]), "source": r["_src"], "role": r["claimant_id"]} for _, r in g.head(6).iterrows()],
                             clause="Related-party pattern (not an automatic finding).", legit="Family policy or shared household.", confidence=0.5, extra={"next_step": "Check relationship and policy linkage."})
        mf = rule["params"].get("min_frequency", 8)
        s = C[C["claimant_id"].ne("") & C["provider"].ne("")]
        if len(s) and len(s) < 300000:
            cnt = s.groupby(["claimant_id", "provider"]).size()
            tot = s.groupby("claimant_id").size()
            for (cl, pr), v in cnt[cnt >= mf].sort_values(ascending=False).head(20).items():
                if v / tot[cl] >= 0.8 and n < 50:
                    n += 1
                    g = s[(s["claimant_id"] == cl) & (s["provider"] == pr)]
                    self.add(rule, "suspicious", f"Claimant {cl} repeatedly claims at provider {pr} ({v} claims)", list(g["claim_id"])[:20], [], {},
                             f"{v} of the claimant's claims ({v / tot[cl]:.0%}) go to a single provider: an unusual claimant-provider concentration.", [],
                             clause="Related-party / concentration pattern (review only).", legit="Chronic condition with a regular treating provider.", confidence=0.45,
                             extra={"next_step": "Review treatment plan and provider relationship."})

    # ------------------------------------------------------------ run
    def run(self):
        if not len(self.lines):
            return self._finish()
        r1 = lambda t: (self.by_type.get(t) or [None])[0]
        if r1("duplicate_invoice"):
            self.dup_invoice(r1("duplicate_invoice"))
        if r1("duplicate_line") or r1("near_duplicate"):
            self.dup_lines(r1("duplicate_line"), r1("near_duplicate"), r1("lookalike_guard"))
        self.merge_dups()
        if r1("duplicate_claim"):
            for f in self.findings:
                for u in f["units"]:
                    if u.startswith("L:"):
                        self.covered_copies[u[2:]] = True
            self.dup_claims(r1("duplicate_claim"))
        if r1("duplicate_payment"):
            self.dup_payments(r1("duplicate_payment"))
        self.line_rules()
        if r1("amount_mismatch"):
            self.amount_mismatch(r1("amount_mismatch"))
        self.twin_level(self.rules)
        if r1("missing_document"):
            self.documents(r1("missing_document"))
        if r1("incomplete_evidence"):
            self.incomplete(r1("incomplete_evidence"))
        if r1("date_order"):
            self.timeline(r1("date_order"))
        self.thresholds()
        if r1("provider_outlier"):
            self.provider_outlier(r1("provider_outlier"))
        if r1("related_party"):
            self.related_party(r1("related_party"))
        return self._finish()

    def merge_dups(self):
        """A copy line caught by several duplicate rules is reported once; extra rules are recorded as corroboration."""
        keep, seen = [], {}
        fam = ("duplicate_invoice", "duplicate_line", "near_duplicate")
        order = sorted(range(len(self.findings)), key=lambda k: (self.findings[k]["rule_type"] != "duplicate_invoice", KLASS_RANK[self.findings[k]["klass"]], k))
        drop = set()
        for k in order:
            f = self.findings[k]
            if f["rule_type"] not in fam:
                continue
            us = list(f["units"])
            if f["rule_type"] != "duplicate_invoice" and us and all(u in seen for u in us):
                host = self.findings[seen[us[0]]]
                if f["rule_id"] not in host["also_matched"] and f["rule_id"] != host["rule_id"]:
                    host["also_matched"].append(f["rule_id"])
                drop.add(k)
            else:
                for u in us:
                    seen.setdefault(u, k)
        self.findings = [f for k, f in enumerate(self.findings) if k not in drop]

    def _finish(self):
        self.findings.sort(key=lambda f: (KLASS_RANK[f["klass"]], -(f["amount"] or 0) if f["klass"] != "clarification" else -(f["at_risk"] or 0)))
        for n, f in enumerate(self.findings, 1):
            f["id"] = f"F-{n:04d}"
        return self.findings

    def context(self):
        C = self.claims
        cl = {c: [(self.lines.at[i, "uid"], float(self.lines.at[i, "amount"])) for i in idxs] for c, idxs in self.claim_lines.items() if c in C.index}
        return {"claim_lines": cl, "proposed": {c: _f(C.at[c, "proposed_settlement"]) for c in cl},
                "eff": {c: self.eff_for(c) for c in cl},
                "period": {f["claim_ids"][0]: True for f in self.findings if f["rule_type"] == "policy_period" and f["klass"] != "clarification"}}
