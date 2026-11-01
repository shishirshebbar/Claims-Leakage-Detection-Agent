"""Rules as data: default pack, judge-rule intake (JSON/YAML/CSV/XLSX/text), NL heuristic parser, merge semantics."""
import io
import json
import re

import pandas as pd
import yaml

from .ingest import parse_money, _decode

DEFAULT_RULES = [
    {"id": "DUP-01", "type": "duplicate_invoice", "name": "Same invoice submitted more than once", "klass": "confirmed",
     "params": {"amount_tolerance_pct": 1.0}},
    {"id": "DUP-02", "type": "duplicate_line", "name": "Exact duplicate charge line", "klass": "confirmed", "params": {}},
    {"id": "DUP-03", "type": "near_duplicate", "name": "Near-duplicate charge (minor date/amount/reference drift)", "klass": "suspicious",
     "params": {"date_window_days": 3, "amount_tolerance_pct": 2.0, "similarity": 85}},
    {"id": "DUP-04", "type": "duplicate_payment", "name": "Same payment made twice", "klass": "confirmed", "params": {}},
    {"id": "DUP-05", "type": "duplicate_claim", "name": "Same incident claimed more than once", "klass": "suspicious", "params": {"amount_tolerance_pct": 1.0}},
    {"id": "LIM-01", "type": "coverage_limit", "name": "Overall coverage limit exceeded", "klass": "confirmed", "params": {}},
    {"id": "LIM-02", "type": "sub_limit", "name": "Category sub-limit exceeded", "klass": "confirmed", "params": {}},
    {"id": "LIM-03", "type": "room_limit", "name": "Daily room-rent limit exceeded", "klass": "confirmed", "params": {}},
    {"id": "EXC-01", "type": "exclusion", "name": "Excluded service or item", "klass": "confirmed", "params": {"terms": []}},
    {"id": "SET-01", "type": "settlement", "name": "Settlement calculation differs from policy terms", "klass": "confirmed",
     "params": {"tolerance_pct": 0.5, "tolerance_abs": 1.0}},
    {"id": "AMT-01", "type": "amount_mismatch", "name": "Inconsistent amounts (qty x price, invoice total, claimed total)", "klass": "confirmed",
     "params": {"tolerance_pct": 0.5, "tolerance_abs": 1.0}},
    {"id": "DOC-01", "type": "missing_document", "name": "Required supporting document missing", "klass": "clarification",
     "params": {"required": []}},
    {"id": "POL-01", "type": "policy_period", "name": "Loss outside policy period or within waiting period", "klass": "confirmed", "params": {}},
    {"id": "ANO-01", "type": "provider_outlier", "name": "Unusual provider billing vs comparable claims", "klass": "suspicious",
     "params": {"ratio": 2.5, "min_lines": 8}},
    {"id": "REL-01", "type": "related_party", "name": "Unusual shared claimant / provider / account patterns", "klass": "suspicious",
     "params": {"min_frequency": 8}},
    {"id": "TIM-01", "type": "date_order", "name": "Timeline inconsistency (dates out of logical order)", "klass": "suspicious", "params": {}},
    {"id": "LKL-01", "type": "lookalike_guard", "name": "Legitimate lookalike (recurring service on different dates)", "klass": "lookalike",
     "params": {"recurring_terms": ["physio", "dialysis", "chemo", "radiotherapy", "session", "follow up", "follow-up", "therapy", "injection"]}},
    {"id": "CLR-01", "type": "incomplete_evidence", "name": "Essential information missing: needs clarification", "klass": "clarification", "params": {}},
]

# types that carry judge-supplied policy knowledge rather than detection engines
GLOBAL_TYPES = {"exclusion", "sub_limit", "room_limit", "coverage_limit", "copay", "deductible", "waiting_period",
                "required_document", "threshold"}
ALL_TYPES = {r["type"] for r in DEFAULT_RULES} | GLOBAL_TYPES
TYPE_ALIASES = {
    "duplicate": "duplicate_line", "dup": "duplicate_line", "invoice_duplicate": "duplicate_invoice",
    "limit": "coverage_limit", "coverage": "coverage_limit", "sublimit": "sub_limit", "sub-limit": "sub_limit",
    "room": "room_limit", "room_rent": "room_limit", "exclusions": "exclusion", "excluded": "exclusion",
    "co_pay": "copay", "co-pay": "copay", "copayment": "copay", "excess": "deductible",
    "missing_docs": "required_document", "document": "required_document", "documents": "required_document",
    "missing_doc": "required_document", "waiting": "waiting_period", "calculation": "settlement",
    "settlement_calculation": "settlement", "amount": "amount_mismatch", "inconsistent_amount": "amount_mismatch",
    "outlier": "provider_outlier", "anomaly": "provider_outlier", "period": "policy_period",
}


def _num(v):
    x, _ = parse_money(v)
    return None if x != x else x


def _canon_type(t):
    t = re.sub(r"[\s\-]+", "_", str(t).strip().lower())
    return TYPE_ALIASES.get(t, t)


# ---------------------------------------------------------------- natural language heuristic
def parse_text_rule(text, idx=1):
    """Heuristic NL -> list of typed rules. Returns (rules, unparsed_text|None)."""
    s = text.strip()
    if not s:
        return [], None
    low = s.lower()
    out = []

    def mk(t, params, name=None, klass=None):
        out.append({"id": f"J-{idx}" if not out else f"J-{idx}.{len(out) + 1}", "type": t, "name": name or s[:90],
                    "klass": klass or ("suspicious" if "suspicious" in low or "review" in low else "confirmed"),
                    "params": params, "source": "judge", "text": s})

    m = re.search(r"(?:exclu\w*|not covered|non[- ]payable)[^:]*[:\-]\s*(.+)$", s, re.I)
    if m and not re.search(r"duplicate", low):
        terms = [t.strip().lower() for t in re.split(r"[;,]| and ", m.group(1)) if t.strip()]
        mk("exclusion", {"terms": terms}, klass="confirmed")
    elif re.search(r"\bexclu\w*|not covered|non[- ]payable", low):
        m2 = re.search(r"(?:exclu\w*|not covered)\s+(?:the\s+)?(?:following\s+)?(?:items?|services?)?\s*[:\-]?\s*(.+)$", s, re.I)
        if m2:
            terms = [t.strip().lower() for t in re.split(r"[;,]| and ", m2.group(1)) if t.strip()]
            mk("exclusion", {"terms": terms}, klass="confirmed")
    m = re.search(r"(?:room|bed)[^\d]{0,40}?(?:limit|cap|max\w*|up to|not exceed\w*)[^\d]{0,15}([\d,\.]+)", s, re.I)
    if m and _num(m.group(1)):
        mk("room_limit", {"per_day": _num(m.group(1))})
    m = re.search(r"sub[- ]?limit[^\d]{0,40}?(?:for|on)?\s*([a-z][a-z \-/&]{2,30}?)\s*(?:is|of|:|=|at|-)?\s*(?:rs\.?|inr|\$)?\s*([\d,\.]+)", s, re.I) \
        or re.search(r"([a-z][a-z \-/&]{2,30}?)\s+(?:is\s+)?(?:capped|limited|limit)\s+(?:at|to|of)?\s*(?:rs\.?|inr|\$)?\s*([\d,\.]+)", s, re.I)
    if m and _num(m.group(2)) and "room" not in m.group(1).lower():
        cat = re.sub(r"\b(sub[- ]?limit|the|a|an|for|on)\b", "", m.group(1), flags=re.I).strip().lower()
        if cat:
            mk("sub_limit", {"category": cat, "cap": _num(m.group(2))})
    m = re.search(r"co-?pay(?:ment)?[^\d]{0,20}([\d\.]+)\s*%", s, re.I)
    if m:
        mk("copay", {"pct": float(m.group(1))})
    m = re.search(r"deductible[^\d]{0,20}(?:rs\.?|inr|\$)?\s*([\d,\.]+)", s, re.I)
    if m and _num(m.group(1)) is not None:
        mk("deductible", {"amount": _num(m.group(1))})
    m = re.search(r"(?:coverage|sum insured|overall|policy|annual)\s*(?:limit|cap)[^\d]{0,20}(?:rs\.?|inr|\$)?\s*([\d,\.]+)", s, re.I)
    if m and _num(m.group(1)):
        mk("coverage_limit", {"limit": _num(m.group(1))})
    m = re.search(r"waiting\s*period[^\d]{0,20}(\d+)\s*days?", s, re.I)
    if m:
        mk("waiting_period", {"days": int(m.group(1))})
    m = re.search(r"(?:missing|require\w*|mandatory)[^:]{0,40}(?:doc\w*|attachments?)[^:]{0,20}[:\-]\s*(.+)$", s, re.I)
    if m:
        mk("required_document", {"required": [t.strip().lower() for t in re.split(r"[;,]| and ", m.group(1)) if t.strip()]}, klass="clarification")
    if re.search(r"near[- ]?duplic|similar|within\s+\d+\s*days", low):
        p = {}
        d = re.search(r"within\s+(\d+)\s*days?", low)
        if d:
            p["date_window_days"] = int(d.group(1))
        t = re.search(r"([\d\.]+)\s*%", low)
        if t:
            p["amount_tolerance_pct"] = float(t.group(1))
        mk("near_duplicate", p, klass="suspicious")
    elif re.search(r"duplicate\s+invoice|same invoice", low):
        mk("duplicate_invoice", {}, klass="confirmed")
    elif re.search(r"duplicate\s+pay", low):
        mk("duplicate_payment", {})
    elif re.search(r"duplicate", low):
        mk("duplicate_line", {})
    m = re.search(r"(?:amount|charge|line|bill)[^\d<>]{0,25}(>=|>|exceed\w*|above|over|more than)\s*(?:rs\.?|inr|\$)?\s*([\d,\.]+)", s, re.I)
    if m and _num(m.group(2)) and not out:
        mk("threshold", {"field": "amount", "op": ">", "value": _num(m.group(2))}, klass="suspicious")
    m = re.search(r"(\w+_date|\w+ date)\s+(?:must be |should be )?(?:before|after|on or before|on or after)\s+(\w+[_ ]date)", s, re.I)
    if m and not out:
        mk("date_order", {"text": s}, klass="suspicious")
    return out, (None if out else s)


# ---------------------------------------------------------------- structured intake
def _from_dict(d, idx):
    d = {str(k).strip().lower().replace(" ", "_"): v for k, v in d.items()}
    rid = str(d.get("id") or d.get("rule_id") or d.get("ruleid") or d.get("code") or f"J-{idx}")
    t = d.get("type") or d.get("rule_type") or d.get("category") or d.get("kind")
    text = str(d.get("description") or d.get("rule") or d.get("text") or d.get("name") or d.get("condition") or "")
    params = d.get("params") if isinstance(d.get("params"), dict) else {}
    reserved = {"id", "rule_id", "ruleid", "code", "type", "rule_type", "category", "kind", "description", "rule", "text",
                "name", "params", "class", "klass", "severity", "enabled", "condition"}
    for k, v in d.items():
        if k not in reserved and v not in (None, "") and v == v:
            params.setdefault(k, v)
    klass = str(d.get("klass") or d.get("class") or d.get("severity") or "").lower()
    klass = {"high": "confirmed", "hard": "confirmed", "confirmed": "confirmed", "error": "confirmed",
             "suspicious": "suspicious", "medium": "suspicious", "soft": "suspicious", "warn": "suspicious", "review": "suspicious",
             "low": "suspicious", "clarification": "clarification"}.get(klass, "")
    enabled = d.get("enabled")
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in ("false", "no", "0", "off")
    rule = None
    if t:
        ct = _canon_type(t)
        if ct in ALL_TYPES:
            if ct in ("exclusion", "required_document"):
                for key in ("terms", "items", "exclusions", "values", "list", "required"):
                    if key in params and isinstance(params[key], str):
                        params[key] = [x.strip().lower() for x in re.split(r"[;,|]", params[key]) if x.strip()]
                if "terms" not in params and ct == "exclusion":
                    for key in ("items", "exclusions", "values", "list"):
                        if key in params:
                            params["terms"] = params.pop(key)
            if ct in ("exclusion", "required_document") and not (params.get("terms") or params.get("required")):
                got, _ = parse_text_rule(text or str(t), idx)
                if got:
                    got[0]["id"] = rid
                    return [got[0]], None
            rule = {"id": rid, "type": ct, "name": text or rid, "klass": klass or ("clarification" if ct == "required_document" else "confirmed"),
                    "params": params, "source": "judge", "text": text}
            if enabled is not None:
                rule["enabled"] = bool(enabled)
            return [rule], None
    got, unparsed = parse_text_rule(text or " ".join(str(v) for v in d.values()), idx)
    for g in got:
        if klass:
            g["klass"] = klass
    return got, unparsed


def parse_rules(files, text="", llm_translate=None):
    """files: [(name, bytes)]; text: pasted rules. Returns {'rules': [...], 'unparsed': [...], 'notes': [...]}"""
    rules, unparsed, notes = [], [], []
    idx = [1]

    def push(r, un):
        rules.extend(r)
        if un:
            unparsed.append(un)
        idx[0] += 1

    def handle_obj(obj):
        if isinstance(obj, dict) and "rules" in obj:
            obj = obj["rules"]
        if isinstance(obj, dict):
            if all(isinstance(v, (dict, str, list)) for v in obj.values()) and not ({"id", "type"} & set(obj)):
                obj = [({"id": k, **v} if isinstance(v, dict) else {"id": k, "description": str(v)}) for k, v in obj.items()]
            else:
                obj = [obj]
        for item in obj:
            if isinstance(item, dict):
                push(*_from_dict(item, idx[0]))
            else:
                push(*parse_text_rule(str(item), idx[0]))

    for name, b in files:
        low = name.lower()
        try:
            if low.endswith((".json",)):
                handle_obj(json.loads(_decode(b)))
            elif low.endswith((".yaml", ".yml")):
                handle_obj(yaml.safe_load(_decode(b)))
            elif low.endswith((".csv", ".tsv")):
                df = pd.read_csv(io.StringIO(_decode(b)), sep=None, engine="python", dtype=str).fillna("")
                for rec in df.to_dict("records"):
                    push(*_from_dict(rec, idx[0]))
            elif low.endswith((".xlsx", ".xls")):
                for sn, df in pd.read_excel(io.BytesIO(b), sheet_name=None, dtype=str).items():
                    for rec in df.fillna("").to_dict("records"):
                        push(*_from_dict(rec, idx[0]))
            elif low.endswith(".pdf"):
                import fitz
                txt = "\n".join(p.get_text() for p in fitz.open(stream=b, filetype="pdf"))
                for ln in re.split(r"\n+|(?<=\.)\s+(?=[A-Z0-9])", txt):
                    if len(ln.strip()) > 8:
                        push(*parse_text_rule(ln, idx[0]))
            else:
                for ln in _decode(b).splitlines():
                    ln = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", ln)
                    if len(ln.strip()) > 5:
                        push(*parse_text_rule(ln, idx[0]))
        except Exception as e:
            notes.append(f"{name}: could not parse rules ({e})")
    for ln in (text or "").splitlines():
        ln = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", ln)
        if len(ln.strip()) > 5:
            push(*parse_text_rule(ln, idx[0]))

    if unparsed and llm_translate:
        still = []
        for u in unparsed:
            try:
                got = llm_translate(u)
            except Exception:
                got = None
            if got:
                for g in got:
                    g.setdefault("source", "judge+llm")
                rules.extend(got)
            else:
                still.append(u)
        unparsed = still
    seen = {}
    for r in rules:
        base = r["id"]
        if base in seen:
            seen[base] += 1
            r["id"] = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
    return {"rules": rules, "unparsed": unparsed, "notes": notes}


# ---------------------------------------------------------------- merge
def merge_rules(judge_rules, mode="augment"):
    """mode: 'augment' (defaults + judge) or 'judge_only'. Returns active rule list.
    Judge rule with same id or same engine type overrides that default (params merged)."""
    import copy
    defaults = [copy.deepcopy(r) | {"source": "default", "enabled": True} for r in DEFAULT_RULES]
    by_id = {r["id"]: r for r in defaults}
    by_type = {r["type"]: r for r in defaults}
    extra = []
    for j in judge_rules:
        j = copy.deepcopy(j)
        j.setdefault("enabled", True)
        target = by_id.get(j["id"]) or (by_type.get(j["type"]) if j["type"] not in GLOBAL_TYPES else None)
        if target is not None:
            target["params"] = {**target["params"], **j.get("params", {})}
            target["enabled"] = j.get("enabled", True)
            target["klass"] = j.get("klass") or target["klass"]
            target["source"] = "judge"
            target["name"] = j.get("name") if j.get("name") and j["name"] != j["id"] else target["name"]
            target["text"] = j.get("text", "")
            target["overridden"] = True
        else:
            extra.append(j)
    if mode == "judge_only":
        touched = {r["id"] for r in defaults if r.get("overridden")}
        # keep engines needed to make sense of the judge's rules, but only those touched
        defaults = [r for r in defaults if r["id"] in touched or r["type"] in ("incomplete_evidence", "lookalike_guard", "settlement", "coverage_limit", "policy_period")]
    return defaults + extra


def globals_from_rules(rules):
    """Collect judge-supplied policy knowledge."""
    g = {"exclusions": [], "sub_limits": {}, "room_limit": None, "coverage_limit": None, "copay_pct": None, "deductible": None,
         "waiting_days": None, "required_docs": [], "thresholds": [], "date_orders": []}
    for r in rules:
        if not r.get("enabled", True):
            continue
        p, t = r.get("params", {}), r["type"]
        if t == "exclusion":
            g["exclusions"] += [x.lower() for x in (p.get("terms") or [])]
        elif t == "sub_limit" and p.get("category") and _num(p.get("cap")) is not None:
            g["sub_limits"][str(p["category"]).lower()] = _num(p["cap"])
        elif t == "room_limit":
            v = _num(p.get("per_day") or p.get("limit") or p.get("cap"))
            if v:
                g["room_limit"] = min(v, g["room_limit"] or v)
        elif t == "coverage_limit" and _num(p.get("limit") or p.get("cap")):
            v = _num(p.get("limit") or p.get("cap"))
            g["coverage_limit"] = min(v, g["coverage_limit"] or v)
        elif t == "copay" and _num(p.get("pct")) is not None:
            g["copay_pct"] = _num(p["pct"])
        elif t == "deductible" and _num(p.get("amount")) is not None:
            g["deductible"] = _num(p["amount"])
        elif t == "waiting_period" and p.get("days"):
            g["waiting_days"] = int(p["days"])
        elif t == "required_document":
            g["required_docs"] += [x.lower() for x in (p.get("required") or [])]
        elif t == "threshold":
            g["thresholds"].append(r)
    return g
