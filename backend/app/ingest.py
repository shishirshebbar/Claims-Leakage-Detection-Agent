"""Ingestion: read any plausible upload, classify tables, map columns, normalise into canonical frames."""
import io
import json
import re
import zipfile
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from .canonical import ENTITIES, ENTITY_LABELS, norm_header, role_ok

AMOUNT_FIELDS = {"claimed_amount", "proposed_settlement", "amount", "unit_price", "invoice_total", "coverage_limit",
                 "deductible", "room_limit_per_day", "deductible_applied", "copay_applied"}
NUM_FIELDS = {"quantity", "waiting_days", "copay_pct"}
CURRENCY_SYMBOLS = [("₹", "INR"), ("rs.", "INR"), ("rs ", "INR"), ("inr", "INR"), ("$", "USD"), ("usd", "USD"),
                    ("€", "EUR"), ("eur", "EUR"), ("£", "GBP"), ("gbp", "GBP"), ("aed", "AED"), ("sgd", "SGD")]


@dataclass
class RawTable:
    name: str
    sheet: str
    df: pd.DataFrame
    notes: list = field(default_factory=list)

    @property
    def key(self):
        return f"{self.name}::{self.sheet}" if self.sheet else self.name


# ---------------------------------------------------------------- reading
def _decode(b: bytes) -> str:
    import chardet
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    enc = chardet.detect(b[:200000]).get("encoding") or "latin-1"
    return b.decode(enc, errors="replace")


def _read_delimited(b: bytes) -> pd.DataFrame:
    text = _decode(b)
    if not text.strip():
        raise ValueError("file is empty")
    import csv
    try:
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|")
        sep = dialect.delimiter
    except Exception:
        sep = ","
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, skipinitialspace=True)


def _flatten_json(obj):
    if isinstance(obj, dict):
        lists = [k for k, v in obj.items() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if lists:
            return {k: pd.json_normalize(obj[k]) for k in lists}
        return {"data": pd.json_normalize(obj)}
    if isinstance(obj, list):
        return {"data": pd.json_normalize(obj)}
    raise ValueError("unsupported JSON structure")


def read_tables(files):
    """files: list of (filename, bytes). Returns (tables, could_not_process)."""
    tables, failed = [], []

    def add(name, sheet, df, notes=None):
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        df = df.loc[:, ~pd.Index(df.columns).duplicated()]
        df = df.dropna(how="all")
        if df.empty:
            failed.append({"file": name + (f"::{sheet}" if sheet else ""), "reason": "no data rows"})
            return
        tables.append(RawTable(name, sheet, df.astype(str).replace({"nan": "", "None": ""}), notes or []))

    def handle(name, b):
        low = name.lower()
        try:
            if low.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(b)) as z:
                    for zi in z.infolist():
                        if zi.is_dir() or zi.filename.startswith("__MACOSX"):
                            continue
                        handle(zi.filename, z.read(zi))
            elif low.endswith((".csv", ".tsv", ".txt")):
                add(name, "", _read_delimited(b))
            elif low.endswith((".xlsx", ".xlsm", ".xls")):
                sheets = pd.read_excel(io.BytesIO(b), sheet_name=None, dtype=str)
                for sn, df in sheets.items():
                    add(name, sn, df.fillna(""))
            elif low.endswith((".json", ".jsonl", ".ndjson")):
                text = _decode(b)
                if low.endswith((".jsonl", ".ndjson")):
                    parts = {"data": pd.json_normalize([json.loads(x) for x in text.splitlines() if x.strip()])}
                else:
                    parts = _flatten_json(json.loads(text))
                for sn, df in parts.items():
                    add(name, sn if len(parts) > 1 else "", df)
            elif low.endswith(".xml"):
                add(name, "", pd.read_xml(io.BytesIO(b), dtype=str, parser="etree"))
            elif low.endswith(".pdf"):
                import fitz
                doc = fitz.open(stream=b, filetype="pdf")
                got = False
                for pno, page in enumerate(doc):
                    for ti, t in enumerate(page.find_tables().tables):
                        rows = t.extract()
                        if len(rows) > 1:
                            df = pd.DataFrame(rows[1:], columns=[str(c or f"col{i}") for i, c in enumerate(rows[0])])
                            add(name, f"page{pno + 1}-t{ti + 1}", df, ["extracted from PDF table; verify against source"])
                            got = True
                if not got:
                    failed.append({"file": name, "reason": "PDF has no extractable tables (scanned or free text); needs OCR/vision extraction"})
            elif low.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff")):
                failed.append({"file": name, "reason": "image documents need OCR/vision extraction (not run offline)"})
            else:
                try:
                    add(name, "", _read_delimited(b))
                except Exception:
                    failed.append({"file": name, "reason": "unsupported file type"})
        except Exception as e:  # never crash on one bad file
            failed.append({"file": name, "reason": f"could not read: {e}"})

    for name, b in files:
        handle(name, b)
    return tables, failed


# ---------------------------------------------------------------- mapping
def _match_columns(cols, entity):
    """Return {source_col: field} choosing best source per field, each source used once."""
    spec = ENTITIES[entity]
    cand = []
    for c in cols:
        n = norm_header(c)
        if not n:
            continue
        for fld, (w, syns) in spec.items():
            if n in syns:
                cand.append((1.0, w, c, fld))
            else:
                best = max((fuzz.ratio(n, s) for s in syns), default=0)
                if best >= 90 and len(n) > 3:
                    cand.append((best / 100 * 0.9, w, c, fld))
    cand.sort(key=lambda x: (-x[0], -x[1]))
    used_c, used_f, out = set(), set(), {}
    for sc, w, c, fld in cand:
        if c in used_c or fld in used_f:
            continue
        out[c] = fld
        used_c.add(c)
        used_f.add(fld)
    return out


def propose(table: RawTable):
    cols = list(table.df.columns)
    per = {e: _match_columns(cols, e) for e in ENTITIES}
    roles = [e for e in ENTITIES if role_ok(e, per[e].values())]
    m_all = set()
    for e in ("claims", "lines", "payments"):
        m_all |= set(per[e].values()) if e in roles else set()
    if "documents" in roles and (set(roles) & {"claims", "lines", "payments"}):
        roles.remove("documents")
    if "payments" in roles and "lines" in roles and "description" not in per["lines"].values():
        roles.remove("lines")
    if "lines" in roles and "claims" in roles and not (set(per["claims"].values()) & {"claimed_amount", "proposed_settlement"}):
        roles.remove("claims")
    return {"table": table.key, "file": table.name, "sheet": table.sheet, "rows": len(table.df),
            "columns": cols, "roles": roles, "mapping": {e: per[e] for e in roles},
            "all_mappings": per, "unmapped": [c for c in cols if not any(c in per[e] for e in roles)],
            "sample": table.df.head(3).to_dict("records")}


# ---------------------------------------------------------------- value parsing
def parse_money(v):
    """Returns (float|nan, currency|None). Handles 1,23,456.00 / 1.234,56 / (100) / symbols."""
    if v is None:
        return np.nan, None
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "none", "null", "-", "n/a", "na"):
        return np.nan, None
    low = s.lower()
    cur = next((c for sym, c in CURRENCY_SYMBOLS if sym in low), None)
    neg = (s.startswith("(") and s.endswith(")")) or s.startswith("-")
    t = re.sub(r"[^0-9.,]", "", s)
    if not t:
        return np.nan, cur
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        if re.fullmatch(r"\d{1,3}(,\d{2,3})+", t):
            t = t.replace(",", "")
        elif re.fullmatch(r"\d+,\d{1,2}", t):
            t = t.replace(",", ".")
        else:
            t = t.replace(",", "")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        x = float(t)
    except ValueError:
        return np.nan, cur
    return (-x if neg else x), cur


def parse_money_series(s: pd.Series):
    uniq = s.dropna().unique()
    cache = {u: parse_money(u) for u in uniq}
    vals = s.map(lambda x: cache.get(x, (np.nan, None))[0]).astype(float)
    curs = {c for (_, c) in cache.values() if c}
    return vals, curs


def parse_date_series(s: pd.Series, default_dayfirst=True):
    """Returns (datetime series, ambiguous_flag)."""
    raw = s.astype(str).str.strip()
    uniq = raw[raw != ""].unique()
    if len(uniq) == 0:
        return pd.Series(pd.NaT, index=s.index), False
    dayfirst, ambiguous = default_dayfirst, False
    pairs = [re.match(r"^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", u) for u in uniq]
    pairs = [p for p in pairs if p]
    if pairs:
        if any(int(p.group(1)) > 12 for p in pairs):
            dayfirst = True
        elif any(int(p.group(2)) > 12 for p in pairs):
            dayfirst = False
        else:
            ambiguous = True

    def one(u):
        if re.fullmatch(r"\d{5}(\.\d+)?", u) and 20000 < float(u) < 80000:
            return pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(u))
        if re.match(r"^\d{4}-\d{2}-\d{2}", u):
            return pd.to_datetime(u, errors="coerce")
        return pd.to_datetime(u, errors="coerce", dayfirst=dayfirst)

    cache = {u: one(u) for u in uniq}
    out = raw.map(lambda x: cache.get(x, pd.NaT))
    return pd.to_datetime(out, errors="coerce"), ambiguous


def parse_kv_list(v):
    """'room:5000;towing:3000' or JSON -> dict[str,float]"""
    if v is None or str(v).strip() == "":
        return {}
    s = str(v).strip()
    if s.startswith("{"):
        try:
            return {str(k).lower().strip(): float(x) for k, x in json.loads(s).items()}
        except Exception:
            pass
    out = {}
    for part in re.split(r"[;|\n]", s):
        if ":" in part or "=" in part:
            k, x = re.split(r"[:=]", part, 1)
            m, _ = parse_money(x)
            if not np.isnan(m):
                out[k.strip().lower()] = m
    return out


def parse_list(v):
    if v is None or str(v).strip() == "":
        return []
    return [x.strip().lower() for x in re.split(r"[;|\n,]", str(v)) if x.strip()]


def norm_invoice(v):
    s = re.sub(r"[^A-Z0-9]", "", str(v).upper())
    s = re.sub(r"^(INVOICE|INV|BILL|NO|REF)+", "", s)
    s = re.sub(r"(?<![0-9])0+(?=[0-9])", "", s)
    return s


def norm_text(v):
    s = re.sub(r"[^a-z0-9 ]", " ", str(v).lower())
    return re.sub(r"\s+", " ", s).strip()


def norm_vendor(v):
    s = norm_text(v)
    s = re.sub(r"\b(pvt|private|ltd|limited|llc|inc|co|corp|llp)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- build
@dataclass
class Dataset:
    claims: pd.DataFrame
    policies: pd.DataFrame
    lines: pd.DataFrame
    payments: pd.DataFrame
    documents: pd.DataFrame
    quarantine: list
    notes: list
    failed_files: list
    currencies: list
    has: dict
    dup_claim_rows: pd.DataFrame

    def summary(self):
        return {"claims": len(self.claims), "policies": len(self.policies), "lines": len(self.lines),
                "payments": len(self.payments), "documents": len(self.documents),
                "quarantined": len(self.quarantine), "currencies": self.currencies, "has": self.has}


def _apply(table: RawTable, entity: str, mapping: dict, notes: list, quarantine: list) -> pd.DataFrame:
    df = table.df
    out = pd.DataFrame(index=df.index)
    for src, fld in mapping.items():
        if src in df.columns:
            out[fld] = df[src].astype(str).str.strip()
    out["_src"] = [f"{table.key} row {i + 2}" for i in range(len(df))]
    curs = set()
    for fld in list(out.columns):
        if fld in AMOUNT_FIELDS:
            vals, cs = parse_money_series(out[fld])
            bad = out[fld].astype(str).str.strip().ne("") & vals.isna()
            for i in out.index[bad]:
                quarantine.append({"file": table.key, "row": int(i) + 2, "entity": entity, "field": fld,
                                   "reason": f"unparseable amount '{out.at[i, fld]}'", "action": "value ignored"})
            out[fld] = vals
            curs |= cs
        elif fld in NUM_FIELDS:
            vals, _ = parse_money_series(out[fld])
            out[fld] = vals
        elif fld.endswith("_date"):
            vals, amb = parse_date_series(out[fld])
            if amb:
                notes.append({"level": "warn", "text": f"{table.key}: date column '{fld}' is ambiguous (dd/mm vs mm/dd); assumed day-first"})
            out[fld] = vals
    if "currency" in out.columns:
        curs |= {c.upper() for c in out["currency"].unique() if c}
    out.attrs["currencies"] = curs
    return out


def build_dataset(tables, proposals, overrides=None):
    """proposals: list from propose(); overrides: {table_key: {"roles":[...], "mapping":{entity:{src:field}}}}"""
    overrides = overrides or {}
    notes, quarantine, currencies = [], [], set()
    parts = {e: [] for e in ENTITIES}
    by_key = {t.key: t for t in tables}
    for p in proposals:
        t = by_key[p["table"]]
        ov = overrides.get(p["table"])
        roles = ov["roles"] if ov and "roles" in ov else p["roles"]
        for r in roles:
            mapping = (ov or {}).get("mapping", {}).get(r) or p["all_mappings"].get(r) or {}
            if not mapping:
                continue
            frame = _apply(t, r, mapping, notes, quarantine)
            currencies |= frame.attrs.get("currencies", set())
            parts[r].append(frame)
    cat = {e: (pd.concat(v, ignore_index=True) if v else pd.DataFrame()) for e, v in parts.items()}

    # ---- claims
    claims, lines = cat["claims"], cat["lines"]
    if len(claims):
        claims["claim_id"] = claims["claim_id"].astype(str).str.strip()
        miss = claims["claim_id"].eq("")
        for i in claims.index[miss]:
            quarantine.append({"file": claims.at[i, "_src"], "row": None, "entity": "claims", "reason": "missing claim_id", "action": "row skipped"})
        claims = claims[~miss]
    if len(lines):
        lines["claim_id"] = lines.get("claim_id", pd.Series("", index=lines.index)).astype(str).str.strip()
        lines.loc[lines["claim_id"].eq(""), "claim_id"] = "UNLINKED"
        bad = lines["amount"].isna()
        for i in lines.index[bad]:
            quarantine.append({"file": lines.at[i, "_src"], "row": None, "entity": "lines", "reason": "line amount missing/unparseable", "action": "row skipped"})
        lines = lines[~bad]

    has_real_lines = len(lines) > 0
    if not len(claims) and has_real_lines:
        g = lines.groupby("claim_id", sort=False)
        claims = g.agg(claimed_amount=("amount", "sum")).reset_index()
        for f in ("policy_id", "claimant_id", "provider", "claim_type", "loss_date"):
            if f in lines.columns:
                claims[f] = claims["claim_id"].map(g[f].first())
        claims["_src"] = "derived from invoice lines"
        notes.append({"level": "info", "text": "No claims table found; claims derived from invoice lines"})
    dup_claim_rows = pd.DataFrame()
    if len(claims):
        dup_mask = claims.duplicated("claim_id", keep="first")
        dup_claim_rows = claims[dup_mask].copy()
        claims = claims[~dup_mask].reset_index(drop=True)
    for c in ("policy_id", "claimant_id", "provider", "claim_type", "invoice_no", "status", "bank_account", "phone", "address", "diagnosis"):
        if c not in claims.columns:
            claims[c] = ""
        claims[c] = claims[c].fillna("").astype(str)
    for c in ("claimed_amount", "proposed_settlement", "deductible_applied", "copay_applied"):
        if c not in claims.columns:
            claims[c] = np.nan
    for c in ("loss_date", "claim_date", "admission_date", "discharge_date"):
        if c not in claims.columns:
            claims[c] = pd.NaT

    # ---- lines (synthesise when only claim-level amounts exist)
    synthetic = False
    if not has_real_lines and len(claims):
        synthetic = True
        amt = claims["claimed_amount"].fillna(claims["proposed_settlement"])
        lines = pd.DataFrame({
            "claim_id": claims["claim_id"], "invoice_no": claims["invoice_no"], "vendor": claims["provider"],
            "invoice_date": claims["claim_date"], "service_date": claims["loss_date"],
            "description": claims["claim_type"].replace("", "Claim (no line detail)"),
            "category": claims["claim_type"], "quantity": 1.0, "unit_price": amt, "amount": amt,
            "_src": claims["_src"]})
        lines = lines[lines["amount"].notna()]
        notes.append({"level": "info", "text": "No invoice-line table found; one line per claim synthesised from claim-level amount"})
    for c in ("invoice_no", "vendor", "description", "category"):
        if c not in lines.columns:
            lines[c] = ""
        lines[c] = lines[c].fillna("").astype(str)
    for c in ("invoice_date", "service_date"):
        if c not in lines.columns:
            lines[c] = pd.NaT
    for c in ("quantity", "unit_price", "invoice_total"):
        if c not in lines.columns:
            lines[c] = np.nan
    lines["quantity_given"] = lines["quantity"].notna()
    lines["quantity"] = lines["quantity"].fillna(1.0)
    lines = lines.reset_index(drop=True)
    if "line_id" not in lines.columns:
        lines["line_id"] = lines.groupby("claim_id").cumcount() + 1
    lines["line_id"] = lines["line_id"].astype(str)
    lines["uid"] = [f"{c}#{l}#{i}" for i, (c, l) in enumerate(zip(lines["claim_id"], lines["line_id"]))]
    lines["inv_norm"] = lines["invoice_no"].map(norm_invoice)
    lines["vendor_norm"] = lines["vendor"].map(norm_vendor)
    lines["desc_norm"] = lines["description"].map(norm_text)
    lines["cat_norm"] = lines["category"].map(norm_text)
    lines["date"] = lines["service_date"].fillna(lines["invoice_date"])
    lines["synthetic"] = synthetic

    if len(claims):
        claims["claimed_amount"] = claims["claimed_amount"].fillna(claims["claim_id"].map(lines.groupby("claim_id")["amount"].sum()))
        info = claims.set_index("claim_id")
        for f in ("claimant_id", "policy_id", "provider", "claim_type"):
            lines[f"c_{f}"] = lines["claim_id"].map(info[f])
        lines["c_loss_date"] = lines["claim_id"].map(info["loss_date"])
        lines["vendor_norm"] = np.where(lines["vendor_norm"].eq(""), lines["c_provider"].map(norm_vendor), lines["vendor_norm"])
        lines["vendor"] = np.where(lines["vendor"].eq(""), lines["c_provider"], lines["vendor"])

    # ---- policies, payments, documents
    pol = cat["policies"]
    if len(pol):
        pol["policy_id"] = pol["policy_id"].astype(str).str.strip()
        pol = pol[pol["policy_id"].ne("")].drop_duplicates("policy_id").reset_index(drop=True)
        pol["sub_limits_d"] = pol["sub_limits"].map(parse_kv_list) if "sub_limits" in pol else [{}] * len(pol)
        pol["exclusions_l"] = pol["exclusions"].map(parse_list) if "exclusions" in pol else [[]] * len(pol)
        pol["required_docs_l"] = pol["required_documents"].map(parse_list) if "required_documents" in pol else [[]] * len(pol)
        for c in ("coverage_limit", "deductible", "copay_pct", "room_limit_per_day", "waiting_days"):
            if c not in pol.columns:
                pol[c] = np.nan
        for c in ("start_date", "end_date"):
            if c not in pol.columns:
                pol[c] = pd.NaT
        cp = pol["copay_pct"]
        pol["copay_pct"] = np.where(cp.notna() & (cp <= 1) & (cp > 0), cp * 100, cp)
    pay = cat["payments"]
    if len(pay):
        for c in ("claim_id", "invoice_no", "payment_id", "reference", "method"):
            if c not in pay.columns:
                pay[c] = ""
            pay[c] = pay[c].fillna("").astype(str).str.strip()
        if "payment_date" not in pay.columns:
            pay["payment_date"] = pd.NaT
        bad = pay["amount"].isna()
        for i in pay.index[bad]:
            quarantine.append({"file": pay.at[i, "_src"], "row": None, "entity": "payments", "reason": "payment amount missing/unparseable", "action": "row skipped"})
        pay = pay[~bad].reset_index(drop=True)
        pay["inv_norm"] = pay["invoice_no"].map(norm_invoice)
        pay["ref_norm"] = pay["reference"].map(lambda x: re.sub(r"[^A-Z0-9]", "", x.upper()))
    doc = cat["documents"]
    if len(doc):
        doc["claim_id"] = doc["claim_id"].astype(str).str.strip()
        doc["doc_type"] = doc["doc_type"].map(lambda x: re.sub(r"[^a-z0-9]+", "_", str(x).lower()).strip("_"))

    cur_list = sorted(currencies)
    if len(cur_list) > 1:
        notes.append({"level": "warn", "text": f"Multiple currencies detected ({', '.join(cur_list)}). Amounts are NOT converted; totals mix currencies and must be reviewed."})
    has = {"policies": bool(len(pol)), "documents": bool(len(doc)), "payments": bool(len(pay)),
           "real_lines": has_real_lines, "claims": bool(len(claims))}
    if not has["policies"]:
        notes.append({"level": "warn", "text": "No policy coverage supplied: limit, exclusion and settlement rules cannot be evaluated"})
    if not has["documents"]:
        notes.append({"level": "warn", "text": "No supporting-document inventory supplied: missing-document rule cannot be evaluated"})
    return Dataset(claims, pol if len(pol) else pd.DataFrame(), lines, pay if len(pay) else pd.DataFrame(),
                   doc if len(doc) else pd.DataFrame(), quarantine, notes, [], cur_list, has, dup_claim_rows)
