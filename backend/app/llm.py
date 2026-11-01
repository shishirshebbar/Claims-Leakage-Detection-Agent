"""Optional OpenAI helpers. Everything has a deterministic fallback; the LLM never does arithmetic."""
import hashlib
import json
import os
import time

_client = None


def _load_env():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "..", ".env"), os.path.join(here, "..", "..", ".env")):
        if os.path.isfile(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def _gemini():
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def available():
    return bool(_gemini() or os.environ.get("OPENAI_API_KEY"))


def _get():
    global _client
    if _client is None:
        from openai import OpenAI
        if _gemini():
            _client = OpenAI(api_key=_gemini(), base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
        else:
            _client = OpenAI()
    return _client


MODEL = os.environ.get("CLAIMIQ_MODEL") or ("gemini-2.5-flash" if _gemini() else "gpt-4o-mini")


def _chat(system, user, as_json=False):
    kwargs = {"response_format": {"type": "json_object"}} if as_json else {}
    r = _get().chat.completions.create(
        model=MODEL, temperature=0, timeout=25,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kwargs)
    return r.choices[0].message.content


_probe = {"t": 0.0, "ok": False, "err": ""}


def record(ok, err=""):
    """Stores the outcome of the last real LLM call so status checks need no extra request."""
    _probe.update(t=time.time(), ok=ok, err=err)


def reachable(force=False):
    """(ok, reason) from the last real call. Makes no request, so it costs no quota."""
    if not available():
        return False, "no LLM API key set"
    if _probe["t"] == 0.0:
        return True, "key set; not yet called this session"
    return _probe["ok"], _probe["err"]


def translate_rule(text):
    """Natural-language rule -> list of typed rule dicts, or None."""
    if not available():
        return None
    sys = ("Convert an insurance claims rule into JSON {\"rules\":[{\"type\":one of [duplicate_invoice,duplicate_line,near_duplicate,duplicate_payment,"
           "coverage_limit,sub_limit,room_limit,exclusion,copay,deductible,waiting_period,required_document,threshold],\"klass\":\"confirmed|suspicious|clarification\","
           "\"params\":{...}}]}. Params: exclusion{terms:[..]}, sub_limit{category,cap}, room_limit{per_day}, copay{pct}, deductible{amount}, coverage_limit{limit}, "
           "waiting_period{days}, required_document{required:[..]}, near_duplicate{date_window_days,amount_tolerance_pct}, threshold{field:'amount',op:'>',value}. "
           "Return {\"rules\":[]} if not expressible. Do not invent numbers.")
    data = json.loads(_chat(sys, text, True))
    out = []
    for i, r in enumerate(data.get("rules", []), 1):
        if r.get("type"):
            out.append({"id": f"JL-{int(hashlib.md5(text.encode()).hexdigest()[:6], 16) % 9999}-{i}", "type": r["type"], "name": text[:90], "klass": r.get("klass", "confirmed"),
                        "params": r.get("params", {}), "source": "judge+llm", "text": text})
    return out or None


def explain(finding):
    """Plain-English explanation grounded only in the finding's own facts. Returns None if no key."""
    if not available():
        return None
    facts = {k: finding.get(k) for k in ("title", "summary", "evidence", "calc", "clause", "legit", "amount", "klass")}
    sys = ("You are a claims analyst. Explain in 3-4 plain sentences why this claim was flagged, using ONLY the facts supplied. "
           "Do not compute or alter any number. Mention the clause and one legitimate explanation. Do not allege fraud.")
    return _chat(sys, json.dumps(facts, default=str))


def suggest_mapping(table_name, columns, sample):
    if not available():
        return None
    sys = ("Map CSV columns to canonical claim fields. Return JSON {\"entity\":\"claims|policies|lines|payments|documents\",\"mapping\":{column:field}}. "
           "Fields claims:claim_id,policy_id,claimant_id,provider,claim_type,loss_date,claim_date,claimed_amount,proposed_settlement,invoice_no; "
           "policies:policy_id,coverage_limit,deductible,copay_pct,start_date,end_date,room_limit_per_day,exclusions,sub_limits; "
           "lines:claim_id,invoice_no,vendor,service_date,description,category,quantity,unit_price,amount; payments:claim_id,invoice_no,amount,payment_date,reference; documents:claim_id,doc_type.")
    return json.loads(_chat(sys, json.dumps({"table": table_name, "columns": columns, "sample": sample[:3]}, default=str), True))
