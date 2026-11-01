from helpers import load_sample, PL, by


def test_sample_catches_all_planted():
    S, truth = load_sample()
    F = S["findings"]
    for t in truth:
        cs = set(t["claims"])
        hits = [f for f in F if cs & set(f["claim_ids"])]
        if t["type"] == "lookalike":
            assert not [f for f in hits if f["klass"] in ("confirmed", "suspicious")], "lookalike wrongly flagged"
            assert S["lookalikes"]
        else:
            assert hits, f"missed {t['type']}"


def test_duplicate_invoice_counted_once():
    S, _ = load_sample()
    inv = [f for f in S["findings"] if f["rule_id"] == "DUP-01"]
    assert len(inv) == 1
    # one overpayment: the duplicate payment finding must not add it again
    assert not [f for f in S["findings"] if f["rule_id"] == "DUP-04" and "CL-1031" in f["claim_ids"]]
    assert S["state"]["claims"]["CL-1032"]["leakage"] == S["state"]["claims"]["CL-1032"]["twin"]["proposed"]


def test_totals_equal_sum_of_claims_and_global():
    S, _ = load_sample()
    st = S["state"]
    per_claim = sum(c["leakage"] for c in st["claims"].values())
    x = sum(f["amount"] for f in S["findings"] if f["rule_id"] == "DUP-04")
    assert abs(st["totals"]["confirmed_leakage"] - per_claim - x) < 0.02


def test_unreachable_llm_uses_deterministic_mode(monkeypatch):
    from app import llm, agent
    monkeypatch.setattr(llm, "reachable", lambda force=False: (False, "no LLM API key set"))
    S, _ = load_sample()
    assert S["agent_mode"].startswith("deterministic")
    assert all(f.get("agent") is None for f in S["findings"])
    assert agent.run_mode(False) == "deterministic (LLM unreachable)"


def test_one_llm_call_per_run_and_amounts_unchanged(monkeypatch):
    from app import llm
    base, _ = load_sample()
    base_total = base["state"]["totals"]["confirmed_leakage"]
    calls = []

    def fake(system, user, as_json=False):
        calls.append(1)
        return {"findings": [], "lookalikes": []}
    monkeypatch.setattr(llm, "reachable", lambda force=False: (True, "ok"))
    monkeypatch.setattr(llm, "_chat", fake)
    # rule translation is a separate per-line step; stub it so only the analysis call is counted
    monkeypatch.setattr(llm, "translate_rule", lambda text: None)
    S, _ = load_sample()
    assert len(calls) == 1
    assert S["state"]["totals"]["confirmed_leakage"] == base_total


def test_midrun_failure_degrades_without_changing_amounts(monkeypatch):
    from app import llm, agent
    base, _ = load_sample()
    base_total = base["state"]["totals"]["confirmed_leakage"]

    def boom(*a, **k):
        raise ConnectionError("down")
    monkeypatch.setattr(llm, "reachable", lambda force=False: (True, "ok"))
    monkeypatch.setattr(llm, "_chat", boom)
    S, _ = load_sample()
    assert S["state"]["totals"]["confirmed_leakage"] == base_total
    assert agent.run_mode(True, degraded=True).startswith("agent (partial")


def test_dismiss_recalculates():
    S, _ = load_sample()
    before = S["state"]["totals"]["confirmed_leakage"]
    f = by(S, rule_id="LIM-03")[0]
    PL.decide(S, f["id"], "dismiss", "tester", "approved upgrade")
    after = S["state"]["totals"]["confirmed_leakage"]
    assert after < before
    PL.decide(S, f["id"], "confirm", "tester")
    assert S["state"]["totals"]["confirmed_leakage"] == before
    assert any(a["action"] == "dismiss" for a in S["audit"])


def test_dismiss_needs_reason():
    S, _ = load_sample()
    try:
        PL.decide(S, S["findings"][0]["id"], "dismiss", "t", "")
        assert False
    except ValueError:
        pass


def test_missing_docs_is_clarification_without_amount():
    S, _ = load_sample()
    f = by(S, rule_id="DOC-01")[0]
    assert f["klass"] == "clarification" and f["amount"] is None and f["at_risk"]


def test_settlement_recalc():
    S, _ = load_sample()
    f = by(S, rule_id="SET-01")[0]
    assert abs(f["amount"] - 5500.0) < 0.01  # 46000 paid vs (46000-1000)*0.9=40500


def test_no_policy_runs_with_warning():
    from helpers import PL as P, SM
    b, _ = SM.build()
    files = [("lines.csv", b["invoice_lines"].to_csv(index=False).encode())]
    S = P.create_session(files, [], "")
    P.run_session(S)
    assert any("policy" in n["text"].lower() for n in S["ds"].notes)


def test_messy_formats():
    from helpers import PL as P
    csv = "Claim No;Inv No;Vendor;Date of Service;Item;Qty;Rate;Amount\nA1;INV-001;Acme;31/01/2024;Scan;1;1.234,50;1.234,50\nA2;inv001;Acme Ltd;31/01/2024;Scan;1;1.234,50;1.234,50\n"
    S = P.create_session([("x.csv", csv.encode())], [], "")
    P.run_session(S)
    assert any(f["rule_id"] == "DUP-01" for f in S["findings"])
    assert S["findings"][0]["amount"] == 1234.5
