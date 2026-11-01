"""ClaimIQ agent layer: one LLM call per analysis run.

The deterministic engine finds every candidate and computes every amount. The agent then makes ONE
structured LLM call that plays three subagent roles (evidence check, lookalike check, explainer)
and returns JSON for all findings at once. The LLM never changes amounts. If the call cannot be
made, the run keeps the deterministic results and the mode is reported as deterministic.
This keeps free-tier quota usage to a single request per run.
"""
import json
from . import llm

# Bounds prompt size; findings beyond this keep deterministic output only.
MAX_REVIEW = 40
MAX_LOOKALIKES = 20

SYSTEM = (
    "You are ClaimIQ, a claims-leakage agent with three roles. Do not compute or change any amount. "
    "Role 1 evidence_check: for each finding, verdict is confirm (evidence supports it), "
    "needs_review (thin evidence or a legitimate explanation is possible), or dismiss. "
    "Role 2 lookalike_check: for each similar-line group, verdict is legitimate (for example repeated "
    "physiotherapy sessions) or possible_duplicate. "
    "Role 3 explainer: for each finding, write 2-3 plain sentences for a claims handler using only the "
    "facts given, with no new numbers. "
    "Reply with JSON only: {\"findings\": [{\"id\": str, \"verdict\": str, \"reason\": str, \"explanation\": str}], "
    "\"lookalikes\": [{\"id\": str, \"verdict\": str, \"reason\": str}]}."
)

VERDICTS = ("confirm", "needs_review", "dismiss")
LK_VERDICTS = ("legitimate", "possible_duplicate")


def _facts(f):
    return {k: f.get(k) for k in ("id", "title", "summary", "evidence", "calc", "clause", "legit", "klass", "amount")}


def _payload(findings, lookalikes):
    fs = [_facts(f) for f in list(findings)[:MAX_REVIEW]]
    lks = []
    for i, lk in enumerate(list(lookalikes or [])[:MAX_LOOKALIKES]):
        lk = dict(lk)
        lk["id"] = f"LK-{i + 1:02d}"
        lks.append(lk)
    return {"findings": fs, "lookalikes": lks}


def analyse(findings, lookalikes):
    """Single LLM call for the whole run. Returns (agent_result | None, error_text).
    agent_result = {"findings": {fid: {...}}, "lookalikes": [{"lookalike":..., "verdict":..., "reason":...}]}."""
    payload = _payload(findings, lookalikes)
    if not payload["findings"] and not payload["lookalikes"]:
        return {"findings": {}, "lookalikes": []}, ""
    try:
        raw = llm._chat(SYSTEM, json.dumps(payload, default=str)[:12000], as_json=True)
    except Exception as e:  # network, quota, auth, timeout
        err = f"{type(e).__name__}: {str(e)[:160]}"
        llm.record(False, err)
        return None, err
    try:
        data = json.loads(raw)
    except Exception:
        llm.record(False, "reply was not valid JSON")
        return None, "LLM reply was not valid JSON"
    llm.record(True)

    out_f = {}
    for item in data.get("findings", []) or []:
        fid = item.get("id")
        if fid and item.get("verdict") in VERDICTS:
            out_f[fid] = {"verdict": item["verdict"], "reason": str(item.get("reason", "")),
                          "explanation": str(item.get("explanation", "")).strip()}
    lk_by_id = {lk["id"]: lk for lk in payload["lookalikes"]}
    out_l = []
    for item in data.get("lookalikes", []) or []:
        lk = lk_by_id.get(item.get("id"))
        if lk and item.get("verdict") in LK_VERDICTS:
            out_l.append({"lookalike": {k: v for k, v in lk.items() if k != "id"},
                          "verdict": {"verdict": item["verdict"], "reason": str(item.get("reason", ""))}})
    return {"findings": out_f, "lookalikes": out_l}, ""


def attach(findings, result):
    """Stores each finding's agent verdict and explanation. Only text is added; amounts are untouched."""
    for f in findings:
        f["agent"] = result["findings"].get(f["id"]) if result else None


def explain_finding(finding):
    """Returns the explanation stored during the run; falls back to the deterministic summary."""
    a = finding.get("agent") or {}
    if a.get("explanation"):
        return a["explanation"], "agent"
    return finding.get("summary", ""), "deterministic"


def run_mode(ok, degraded=False):
    """Human-readable mode label shown in the UI and API."""
    if ok and not degraded:
        return "agent"
    if ok:
        return "agent (partial)"
    return "deterministic (LLM unreachable)"


def coordinator_status():
    return {
        "mode": run_mode(llm.available()),
        "provider": "gemini" if llm._gemini() else ("openai" if llm.available() else "none"),
        "model": llm.MODEL,
        "subagents": ["evidence_check", "lookalike_check", "explainer"],
        "llm_calls_per_run": 1,
    }
