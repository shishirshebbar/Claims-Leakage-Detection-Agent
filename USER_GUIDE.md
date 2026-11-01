# ClaimIQ — User Guide

Open **http://localhost:3000**. (Start both servers first; see README.md.)

## 1. Home page — bring your data
| What you do | What happens |
|---|---|
| **Load sample (with my rules)** | Loads 50 synthetic claims plus a sample rules file, runs the analysis and opens the report. Fastest demo. |
| **Load sample (default rules)** | Same data, built-in checks only. |
| **Drop / browse files** (box 1) | Add claims, policies, invoice lines, payments, documents. CSV, Excel, JSON, XML, PDF tables or ZIP. Any column names; they are matched automatically. **remove** deletes a file from the list. |
| **Rules box / Attach rules file** (box 2) | Type rules in plain language (e.g. "Room rent is capped at 5,000 per day", "Co-pay is 10%", "Cosmetic procedures are excluded") or attach a rules file (text, JSON, YAML, CSV, Excel, PDF). Optional. |
| **Dropdown: My rules + default checks / My rules only** | Choose whether built-in checks run alongside your rules. |
| **Review mapping & rules** | Reads the files and shows the next screen. Nothing is analysed yet. |

## 2. Mapping & rules review
- Each file shows how it was understood. **Treat as** checkboxes set whether it is claims, policies, lines, payments or documents.
- Expand a section to see **Source column → Maps to** and change any mapping with the dropdown. "(ignore)" skips a column.
- **Rules understood** lists the rules recognised. Any rule that could not be turned into a check is shown as "Not executable" rather than dropped.
- **Run analysis** starts detection and opens the report. **Back** returns to the upload step.

## 3. Leakage report
- **Four tiles:** Confirmed leakage (rule violations, each amount counted once), Potential (suspicious patterns needing review), At risk · evidence missing (claims that need clarification), Under-settlement.
- Yellow notes warn about things like unreadable files, mixed currencies or rows set aside (quarantined).
- **Findings table:** use the class tabs, status filter, rule filter and search box. **Click a row** to open its explanation page.
- **Rules that fired** shows hits and amounts per rule. **Top claims by leakage:** click one to open its claim view.
- **Legitimate lookalikes** lists similar claims deliberately not flagged (e.g. weekly physiotherapy).
- **Export CSV** downloads all findings. **Audit trail** opens the log of every action.

**How the analysis runs (agent flow):**
- The rule engine finds the issues and does all the money maths.
- A **coordinator agent** then makes **one** Gemini call per run. Within that call, three subagent roles work together: **evidence-check** gives each finding a verdict (confirm / needs review / dismiss) with a reason, **lookalike-check** marks similar claims as legitimate or possible duplicate, and **explainer** writes the plain-English explanation on the finding page.
- The subagents only give advice. They never change amounts. Amounts always come from the rules.
- If Gemini is reachable, the report shows **mode: agent**. If it is unreachable, the report shows **deterministic (LLM unreachable)** and the rule engine results stand alone. A run that loses the connection mid-way is labelled **agent (partial)**.
- The free tier allows about 20 requests per day per model, so each run uses one of them. Rule translation of free-text rules is a separate call, and the bundled `my_rules.txt` needs none.
- Check `/api/health` → `llm_reachable` and `mode` to see the current state. `llm` only shows that a key is set.
- Each run reviews at most 40 findings with the LLM. Any beyond that stay deterministic.

## 4. Finding page — decide
- Top: amount, confidence, claims involved (click to open).
- **Evidence:** the matching rows side by side (green = original, red = repeat) with source file and row.
- **How the amount was calculated:** step-by-step maths. **Clause & possible legitimate explanation** states the rule and what could make it valid.
- **Explain in plain language:** short narrative (uses OpenAI if a key is set; otherwise a standard text).
- **Decision** (needs the *Authorised handler* role):
  - **Confirm leakage** — accepts the finding; suspicious items then count in totals.
  - **Correct amount** — enter a corrected amount and a reason.
  - **Dismiss** — requires a reason; the amount drops out of totals.
  - **Reopen** — undo a decision.
  - Totals on the report update immediately, and **History** records who did what and when.

## 5. Claim view
Reached from a claim ID. Shows **As proposed/paid vs Should pay vs Difference**, the settlement recalculation (deductible → co-pay → cap), a timeline, every invoice line with its reduction, findings and payments.

## 6. Role switch (top right)
- **Authorised handler:** can confirm, correct, dismiss.
- **Viewer (read-only):** decisions are refused with a message.

## Which files to upload for testing

**Test file formats.** `sample_data\mock_claims.json` and `sample_data\mock_claims.xml` each contain three synthetic claims. `sample_data\mock_claims.xlsx` contains claims and policies on separate sheets, `sample_data\mock_claims.pdf` contains a small extractable claims table, and `sample_data\mock_claims_bundle.zip` contains claims and policies CSVs. Upload one of these at a time in the first box to test its format; the workbook and ZIP each produce more than one table. These are mock records and are separate from the full demo below.

**Test 1 — full demo (recommended).** In `claimsentry\sample_data\` select all of these in the first upload box:
`claims.csv`, `policies.csv`, `invoice_lines.csv`, `payments.csv`, `documents.csv`.
Then attach `my_rules.txt` in the rules box. Expected: about 14 findings (duplicate invoice, duplicate line, room limit, excluded item, wrong settlement, near-duplicate, missing document, waiting period, policy period, coverage limit, sub-limit, duplicate payment, related party) and one legitimate lookalike (physiotherapy) not flagged. `ground_truth.json` lists what was planted. Skip the rules file to see only built-in checks.

**Test 2 — claims-only real data.** Upload just
`Healthcare Provider Fraud Detection Analysis dataset\Train_Outpatientdata-1542865627584.csv` (large; the first run can take a minute). There is no policy or invoice data, so only duplicate and pattern checks apply, and the report will say which checks were skipped.

**Test 3 — your own rules.** Upload any of the above and type rules such as `Room rent is capped at 5000 per day` or `Co-pay is 10%`.

## Tips
- Re-run with different rules by going back to Home and uploading again.
- Sample files are in `sample_data\` if you want to test an upload by hand: select `claims.csv`, `policies.csv`, `invoice_lines.csv`, `payments.csv`, `documents.csv` and `my_rules.txt`.
