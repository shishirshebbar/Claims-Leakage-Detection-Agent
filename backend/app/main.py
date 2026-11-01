import csv
import io
from typing import List, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import agent as AGT
from . import fingerprint as FP
from . import twin as TW
from . import llm
from . import pipeline as PL
from . import rules_dsl as RD
from . import sample as SM

app = FastAPI(title="ClaimIQ API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def sess(sid):
    S = PL.SESSIONS.get(sid)
    if not S:
        raise HTTPException(404, "session not found")
    return S


def ran(sid):
    S = sess(sid)
    if not S.get("ran"):
        raise HTTPException(409, "analysis has not been run")
    return S


@app.get("/api/health")
def health():
    ok, reason = llm.reachable()
    return {"ok": True, "llm": llm.available(), "llm_reachable": ok, "llm_detail": reason, "mode": AGT.run_mode(ok)}


@app.post("/api/sessions")
async def create_session(files: List[UploadFile] = File(default=[]), rule_files: List[UploadFile] = File(default=[]), rules_text: str = Form("")):
    fs = [(f.filename or "upload", await f.read()) for f in files]
    rf = [(f.filename or "rules", await f.read()) for f in rule_files]
    if not fs and not rf and not rules_text.strip():
        raise HTTPException(400, "no files supplied")
    S = PL.create_session(fs, rf, rules_text)
    return PL.mapping_view(S)


class RunBody(BaseModel):
    overrides: Optional[dict] = None
    rules: Optional[list] = None
    mode: str = "augment"


@app.post("/api/sessions/{sid}/run")
def run(sid: str, body: RunBody = RunBody()):
    S = sess(sid)
    try:
        PL.run_session(S, body.overrides, body.rules, body.mode)
    except Exception as e:  # surface a clear message instead of a stack trace
        raise HTTPException(422, f"Could not analyse the data: {e}")
    return {"agent_mode": S.get("agent_mode"), **PL.summary(S)}


@app.post("/api/samples/{kind}")
def load_sample(kind: str):
    bundle, truth = SM.build()
    files = [(f"{k}.csv", df.to_csv(index=False).encode()) for k, df in bundle.items()]
    rf = [("my_rules.txt", SM.JUDGE_RULES.encode())] if kind == "with_rules" else []
    S = PL.create_session(files, rf, "")
    PL.run_session(S)
    S["truth"] = truth
    return {"session": S["id"], "agent_mode": S.get("agent_mode"), "summary": PL.summary(S)}


@app.get("/api/sessions/{sid}/summary")
def get_summary(sid: str):
    return PL.summary(ran(sid))


@app.get("/api/sessions/{sid}/mapping")
def get_mapping(sid: str):
    return PL.mapping_view(sess(sid))


@app.get("/api/sessions/{sid}/findings")
def findings(sid: str, klass: Optional[str] = None, status: Optional[str] = None, rule: Optional[str] = None, q: Optional[str] = None, claim: Optional[str] = None):
    return PL.list_findings(ran(sid), klass, status, rule, q, claim)


@app.get("/api/sessions/{sid}/findings/{fid}")
def finding(sid: str, fid: str):
    d = PL.get_finding(ran(sid), fid)
    if not d:
        raise HTTPException(404, "finding not found")
    return d


class Decision(BaseModel):
    action: str
    reason: str = ""
    corrected_amount: Optional[float] = None
    user: str = "claims.handler"


@app.post("/api/sessions/{sid}/findings/{fid}/decision")
def decision(sid: str, fid: str, body: Decision, x_role: str = Header("authorised")):
    S = ran(sid)
    if x_role.lower() != "authorised":
        raise HTTPException(403, "Only authorised users can confirm, correct or dismiss findings")
    try:
        PL.decide(S, fid, body.action, body.user, body.reason, body.corrected_amount)
    except KeyError:
        raise HTTPException(404, "finding not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"finding": PL.get_finding(S, fid), "totals": S["state"]["totals"], "summary": PL.summary(S)}


@app.post("/api/sessions/{sid}/findings/{fid}/explain")
def explain(sid: str, fid: str):
    S = ran(sid)
    f = next((x for x in S["findings"] if x["id"] == fid), None)
    if not f:
        raise HTTPException(404, "finding not found")
    text, source = AGT.explain_finding(f)
    return {"llm": source == "agent", "source": source, "text": text}


@app.get("/api/sessions/{sid}/claims/{cid}")
def claim(sid: str, cid: str):
    S = ran(sid)
    st = S["state"]["claims"].get(cid)
    if not st:
        # Claim exists in the claims table but has no usable invoice lines, so it has no twin state yet.
        row = S["ds"].claims[S["ds"].claims["claim_id"] == cid]
        if row.empty:
            raise HTTPException(404, "claim not found")
        prop = row.iloc[0]["proposed_settlement"]
        prop = None if prop != prop else float(prop)
        tw = TW.compute(0.0, prop, S["eng"].eff_for(cid), 0.0, 0.0, False)
        st = {"twin": tw, "leakage": 0.0, "potential": 0.0, "line_reductions": {}}
        st["twin"]["steps"] = [{"label": "No invoice lines with a usable amount for this claim; nothing to recalculate", "value": 0}]
    L = S["ds"].lines
    rows = L[L["claim_id"] == cid]
    lines = [{"uid": r["uid"], "invoice_no": r["invoice_no"], "description": r["description"], "date": r["date"], "quantity": r["quantity"], "amount": r["amount"],
              "reduction": st["line_reductions"].get(r["uid"], 0)} for _, r in rows.iterrows()]
    c = S["ds"].claims[S["ds"].claims["claim_id"] == cid].iloc[0].to_dict()
    fl = [x for x in PL.list_findings(S, claim=cid)]
    docs = []
    D = S["ds"].documents
    if len(D):
        docs = sorted(set(D[D["claim_id"] == cid]["doc_type"]))
    pays = []
    P = S["ds"].payments
    if len(P):
        pays = P[P["claim_id"] == cid][["payment_id", "amount", "payment_date", "method", "reference"]].to_dict("records")
    timeline = sorted([{"date": x, "event": e} for x, e in (
        (c.get("loss_date"), "Loss / treatment"), (c.get("claim_date"), "Claim filed"), (c.get("admission_date"), "Admission"), (c.get("discharge_date"), "Discharge")) if x is not None and str(x) != "NaT"],
        key=lambda t: str(t["date"]))
    timeline += [{"date": p["payment_date"], "event": f"Payment {p['amount']}"} for p in pays if p.get("payment_date") is not None]
    return PL.clean({"claim": c, "twin": st["twin"], "leakage": st["leakage"], "potential": st["potential"], "lines": lines, "findings": fl, "documents": docs,
                     "payments": pays, "timeline": sorted(timeline, key=lambda t: str(t["date"]))})


@app.get("/api/sessions/{sid}/lookalikes")
def lookalikes(sid: str):
    return PL.clean(ran(sid)["lookalikes"])


@app.get("/api/sessions/{sid}/fingerprints")
def fingerprints(sid: str):
    return PL.clean(FP.compute(ran(sid)))


@app.get("/api/sessions/{sid}/audit")
def audit(sid: str):
    return PL.clean(sess(sid)["audit"])


@app.get("/api/sessions/{sid}/export.csv")
def export(sid: str):
    rows = PL.export_rows(ran(sid))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["finding_id"])
    w.writeheader()
    w.writerows(rows)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=claimiq_{sid}.csv"})


@app.get("/api/sessions/{sid}/truth-check")
def truth_check(sid: str):
    S = ran(sid)
    truth = S.get("truth")
    if not truth:
        raise HTTPException(404, "no ground truth for this session")
    hit = []
    for t in truth:
        cs = set(t["claims"])
        found = [f["rule_id"] for f in S["findings"] if cs & set(f["claim_ids"]) and f["klass"] != "under"]
        hit.append({"type": t["type"], "claims": t["claims"], "note": t["note"], "detected": bool(found) or t["type"] == "lookalike", "rules": sorted(set(found))})
    lk = [x for x in S["lookalikes"]]
    for h in hit:
        if h["type"] == "lookalike":
            h["detected"] = bool(lk) and not any(set(h["claims"]) & set(f["claim_ids"]) and f["klass"] in ("confirmed", "suspicious") for f in S["findings"])
    return {"planted": len(hit), "caught": sum(h["detected"] for h in hit), "items": hit}


@app.exception_handler(Exception)
async def all_errors(request, exc):
    return JSONResponse(status_code=500, content={"detail": f"Unexpected error: {exc}"})
