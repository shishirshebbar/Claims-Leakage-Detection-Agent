# ClaimIQ --- Claims Leakage Detection Agent

### Find the leakage before you pay.

ClaimIQ is an AI-assisted claims forensics platform designed to detect,
quantify, investigate, and prevent potential claims leakage before money
is paid out.

Instead of treating every suspicious claim as fraud, ClaimIQ
reconstructs claim economics, checks policy and evidence consistency,
identifies duplicate or anomalous payments, connects recurring leakage
patterns across claims, and gives investigators evidence-backed
explanations for each finding.

------------------------------------------------------------------------

## 🎥 Product Demo

**End-to-end ClaimIQ walkthrough**

[▶️ Watch the ClaimIQ Demo](https://drive.google.com/file/d/173CNBcU7KdQDhkFOdzvjxhfIB2y6n6X1/view?usp=sharing)

**Workflow**

`Upload Data → Map Data → Configure Rules → Run Analysis → Detect Leakage → Investigate Evidence → Review Claim Digital Twin → Record Decision`

> Replace `YOUR_GITHUB_VIDEO_URL` with the GitHub-hosted demo video link
> after uploading your recording.

------------------------------------------------------------------------

## 🚨 Problem

Claims leakage does not always come from obvious fraud.

Money can be lost because of:

-   Duplicate invoices or payments
-   Incorrect settlement calculations
-   Policy exclusions being overlooked
-   Sub-limit or coverage-limit violations
-   Waiting-period violations
-   Missing supporting documents
-   Repeated provider-level leakage patterns
-   Related-party or shared-bank-account relationships
-   Operational inconsistencies across claims

Traditional rule-based systems can identify isolated exceptions, but
often struggle to explain the financial impact or connect related
leakage across the portfolio.

------------------------------------------------------------------------

## 💡 Solution

**ClaimIQ combines deterministic claims forensics with AI-assisted
investigation.**

It answers four questions:

> **What went wrong?**\
> **How much money is at risk?**\
> **What evidence supports the finding?**\
> **Is the same leakage happening elsewhere?**

The deterministic engine remains authoritative for detection and
financial calculations. AI is used selectively for investigation
support, reasoning, and explanation.

------------------------------------------------------------------------

## 🔍 Core Capabilities

### 1. Flexible Data Ingestion

ClaimIQ supports:

-   CSV / TSV
-   XLSX
-   JSON / JSONL
-   XML
-   ZIP
-   PDF tables

Uploaded data is mapped into a canonical claims model using configurable
column mapping and field synonyms.

------------------------------------------------------------------------

### 2. Claim Digital Twin

For every claim, ClaimIQ reconstructs the financial lifecycle:

``` text
Billed Amount
      ↓
Eligible Amount
      ↓
Policy Reductions
      ↓
Deductible
      ↓
Co-pay
      ↓
Coverage / Sub-limit
      ↓
Expected Payable
      ↓
Actual / Proposed Settlement
      ↓
Potential Leakage
```

This provides a transparent view of how the claim amount changes at each
stage.

------------------------------------------------------------------------

### 3. Leakage Detection

ClaimIQ detects multiple leakage categories:

-   Duplicate invoices
-   Duplicate invoice lines
-   Near-duplicate invoices
-   Duplicate payments
-   Duplicate claim records
-   Policy exclusions
-   Room / sub-limit violations
-   Coverage-limit violations
-   Settlement mismatches
-   Deductible / co-pay inconsistencies
-   Waiting-period violations
-   Policy-period violations
-   Missing documents
-   Provider outliers
-   Related-party / shared-bank-account patterns

------------------------------------------------------------------------

### 4. Count-Once Financial Reconciliation

Multiple rules can identify the same underlying financial issue.

ClaimIQ reconciles overlapping findings so that the same financial
amount is not blindly counted multiple times.

This produces a more defensible estimate of potential leakage.

------------------------------------------------------------------------

### 5. Cross-Claim Leakage Fingerprinting

ClaimIQ looks beyond individual claims to identify recurring patterns
across:

-   Providers
-   Claimants
-   Bank accounts
-   Policies
-   Invoice structures
-   Payment relationships
-   Leakage categories

This helps investigators move from:

**"Something is wrong with this claim."**

to:

**"The same leakage pattern is appearing across multiple claims."**

------------------------------------------------------------------------

### 6. Evidence-Led Investigation

Each finding can be traced to supporting evidence such as:

-   Claim IDs
-   Invoice records
-   Payment records
-   Source rows
-   Policy rules
-   Calculations
-   Related findings

Investigators can therefore inspect the underlying evidence instead of
relying on an unexplained model score.

------------------------------------------------------------------------

### 7. AI-Assisted Investigation

ClaimIQ uses AI selectively for:

-   Evidence review
-   Legitimate lookalike analysis
-   Plain-English explanations

The deterministic engine remains authoritative for:

-   Detection
-   Financial calculations
-   Rule execution
-   Leakage amounts

If an LLM is unavailable, ClaimIQ continues operating in deterministic
mode.

------------------------------------------------------------------------

### 8. Bring Your Own Rules

Rules can be supplied through supported structured or plain-text
formats.

Examples include:

``` text
Room rent cannot exceed the policy room limit.

Dental procedures are excluded unless explicitly covered.

Claims submitted during the waiting period are not eligible.

Maximum payable amount is limited by the applicable coverage cap.
```

Rules are parsed into executable checks where supported. Unparseable
rules are surfaced rather than silently treated as executable logic.

------------------------------------------------------------------------

### 9. Human-in-the-Loop Review

Investigators can:

-   Confirm findings
-   Correct findings
-   Dismiss findings
-   Reopen findings

Decisions are recorded through an audit trail.

AI recommendations are therefore reviewable rather than automatically
treated as final payment decisions.

------------------------------------------------------------------------

## 🧠 Architecture

``` text
                  ┌──────────────────────┐
                  │     Claims Data      │
                  │ CSV / XLSX / JSON    │
                  │ XML / PDF / ZIP      │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ Flexible Ingestion   │
                  │ & Column Mapping     │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ Canonical Claims     │
                  │ Data Model           │
                  └──────────┬───────────┘
                             │
                             ▼
          ┌─────────────────────────────────────┐
          │      Deterministic Forensics        │
          │                                     │
          │ Duplicates • Limits • Exclusions   │
          │ Settlement • Documents • Payments  │
          │ Related Parties • Provider Patterns│
          └──────────────────┬──────────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
   ┌─────────────────────┐       ┌─────────────────────┐
   │ Claim Digital Twin  │       │ Cross-Claim         │
   │ & Financial Model   │       │ Fingerprinting      │
   └──────────┬──────────┘       └──────────┬──────────┘
              │                             │
              └──────────────┬──────────────┘
                             ▼
                  ┌──────────────────────┐
                  │ AI Investigation     │
                  │ Evidence • Explain   │
                  │ Lookalike Analysis   │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ Investigator Review  │
                  │ + Audit Trail        │
                  └──────────────────────┘
```

------------------------------------------------------------------------

## 🔄 Application Workflow

### Step 1 --- Upload

Upload claims, policies, invoices, payments, and supporting evidence.

### Step 2 --- Map

Map incoming columns to ClaimIQ's canonical data model.

### Step 3 --- Configure Rules

Use built-in rules or provide additional business rules.

### Step 4 --- Run Analysis

The deterministic forensics engine evaluates claims, transactions,
policy conditions, and relationships.

### Step 5 --- Review Leakage

The dashboard summarizes findings, affected claims, and potential
financial impact.

### Step 6 --- Investigate

Open individual findings to inspect evidence, calculations, source
records, and explanations.

### Step 7 --- Review the Claim Digital Twin

Inspect the claim's financial reconstruction and settlement calculation.

### Step 8 --- Record Decision

Confirm, correct, dismiss, or reopen the finding.

------------------------------------------------------------------------

## 💰 Financial Reconciliation

ClaimIQ distinguishes between:

-   **Billed amount**
-   **Eligible amount**
-   **Policy reductions**
-   **Deductible**
-   **Co-pay**
-   **Coverage caps**
-   **Expected payable**
-   **Actual / proposed settlement**
-   **Potential leakage**

This allows a reviewer to understand not just that a claim is
suspicious, but **where the financial discrepancy originated**.

------------------------------------------------------------------------

## 🧪 Demo Dataset

The repository includes a synthetic claims dataset containing planted
scenarios such as:

-   Duplicate invoices
-   Duplicate invoice lines
-   Near duplicates
-   Duplicate payments
-   Room-limit violations
-   Excluded items
-   Settlement mismatches
-   Missing documents
-   Waiting-period violations
-   Policy-period violations
-   Coverage-limit violations
-   Sub-limit violations
-   Related-party patterns
-   Legitimate lookalikes

The demo dataset is synthetic and does not contain customer or
production data.

------------------------------------------------------------------------

## 📊 Validation

ClaimIQ includes deterministic validation against planted synthetic
ground truth.

A recorded large-data validation run used approximately **30,000 rows**,
with:

-   40 injected exact duplicates
-   40 injected near duplicates
-   40/40 exact duplicates detected
-   40/40 near duplicates detected
-   Approximately 46 seconds runtime

These are validation-test results on synthetic data and are **not a
claim of production accuracy**.

------------------------------------------------------------------------

## 🛠️ Technology Stack

### Frontend

-   Next.js
-   React
-   TypeScript
-   Tailwind CSS

### Backend

-   Python
-   FastAPI
-   Uvicorn
-   Pandas
-   NumPy
-   Pydantic
-   RapidFuzz
-   PyMuPDF
-   PyYAML

### AI

-   OpenAI-compatible APIs
-   Google Gemini
-   Configurable LLM model

------------------------------------------------------------------------

## 🚀 Quick Start

### 1. Start the backend

``` bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```

### 2. Start the frontend

``` bash
cd frontend
npm install
npm run dev
```

Open:

``` text
http://localhost:3000
```

For a production-style frontend build:

``` bash
npm run build
npm run start
```

The frontend proxies `/api/*` requests to:

``` text
http://127.0.0.1:8000
```

Override this with `API_URL` when required.

------------------------------------------------------------------------

## 🤖 Optional LLM Configuration

ClaimIQ works without an LLM for deterministic analysis.

To enable AI-assisted investigation, configure one of the supported
providers.

### OpenAI-compatible API

``` bash
export OPENAI_API_KEY="your-key"
```

### Google Gemini

``` bash
export GEMINI_API_KEY="your-key"
```

Optional model configuration:

``` bash
export CLAIMIQ_MODEL="gemini-2.5-flash"
```

The exact model can be changed according to the configured provider.

------------------------------------------------------------------------

## 🔌 API Overview

  ----------------------------------------------------------------------------------------------
  Endpoint                                                   Purpose
  ---------------------------------------------------------- -----------------------------------
  `GET /api/health`                                          Service and LLM health

  `POST /api/sessions`                                       Create analysis session

  `POST /api/samples/{kind}`                                 Load sample/demo data

  `GET /api/sessions/{id}/mapping`                           Inspect data mapping

  `POST /api/sessions/{id}/run`                              Run claims analysis

  `GET /api/sessions/{id}/summary`                           Analysis summary

  `GET /api/sessions/{id}/findings`                          List findings

  `GET /api/sessions/{id}/findings/{finding_id}`             Finding details

  `POST /api/sessions/{id}/findings/{finding_id}/decision`   Record reviewer decision

  `POST /api/sessions/{id}/findings/{finding_id}/explain`    Generate explanation

  `GET /api/sessions/{id}/claims/{claim_id}`                 Claim Digital Twin

  `GET /api/sessions/{id}/lookalikes`                        Lookalike analysis

  `GET /api/sessions/{id}/fingerprints`                      Cross-claim leakage patterns

  `GET /api/sessions/{id}/audit`                             Audit trail

  `GET /api/sessions/{id}/truth-check`                       Synthetic ground-truth validation
  ----------------------------------------------------------------------------------------------

------------------------------------------------------------------------

## 📁 Project Structure

``` text
ClaimIQ/
│
├── backend/
│   └── app/
│       ├── agent.py
│       ├── aggregate.py
│       ├── canonical.py
│       ├── engine.py
│       ├── fingerprint.py
│       ├── ingest.py
│       ├── llm.py
│       ├── main.py
│       ├── pipeline.py
│       ├── rules_dsl.py
│       ├── sample.py
│       └── twin.py
│
├── frontend/
│   └── app/
│       ├── components/
│       ├── s/
│       ├── f/
│       ├── c/
│       └── ...
│
└── README.md
```

------------------------------------------------------------------------

## 🔐 Security & Responsible AI

ClaimIQ follows an evidence-first approach:

-   No customer production data is required for the demo.
-   Synthetic data is used for validation.
-   Financial calculations remain deterministic.
-   AI does not directly decide payment amounts.
-   AI output is treated as investigation support.
-   Human review is required for final finding decisions.
-   Finding decisions are recorded in an audit trail.
-   Unparseable rules are not silently treated as executable rules.

------------------------------------------------------------------------

## ⚖️ AI Design Principle

ClaimIQ deliberately separates **calculation** from **reasoning**.

``` text
Deterministic Engine
        │
        ├── Detection
        ├── Rules
        ├── Financial Maths
        ├── Leakage Amounts
        └── Reconciliation
                │
                ▼
        AI Investigation Layer
                │
                ├── Evidence Review
                ├── Lookalike Analysis
                └── Explanation
                │
                ▼
        Human Investigator
                │
                ├── Confirm
                ├── Correct
                ├── Dismiss
                └── Reopen
```

This reduces the risk of using a probabilistic model for calculations
that should be deterministic and auditable.

------------------------------------------------------------------------

## 🌟 What Makes ClaimIQ Different?

Many claims AI systems focus primarily on:

> **"Is this claim suspicious?"**

ClaimIQ focuses on the larger financial investigation:

> **"Where did the money leak, what evidence supports it, how much is at
> risk, and is the same leakage happening elsewhere?"**

The key differentiators are:

-   **Claim Digital Twin** --- reconstructs claim economics.
-   **Evidence-led findings** --- traces results back to source data.
-   **Count-once reconciliation** --- avoids blindly double-counting
    overlapping findings.
-   **Cross-claim fingerprinting** --- finds recurring leakage patterns.
-   **Configurable business rules** --- supports domain-specific policy
    logic.
-   **AI-assisted investigation** --- uses AI where reasoning adds
    value.
-   **Human-in-the-loop decisions** --- keeps investigators accountable
    for final outcomes.

ClaimIQ is therefore designed as a **claims forensics and leakage
intelligence layer**, rather than simply another fraud score.

------------------------------------------------------------------------

## 🔮 Future Extensions

Potential future capabilities include:

-   OCR and richer scanned-document analysis
-   Image-based damage and invoice reconciliation
-   Evidence graphs
-   Advanced provider network analysis
-   Recovery and subrogation intelligence
-   Leakage prevention simulation
-   Advanced anomaly detection
-   Enterprise authentication and role management
-   Persistent database and multi-tenant deployment
-   Claims-platform integrations
-   Model monitoring and evaluation

These are future extensions and are not represented as implemented
prototype capabilities.

------------------------------------------------------------------------

## 🏆 Hackathon Context

Built for:

**Azentio.ai Build Labs --- HackCulture**

**Selected Theme:** Claims Leakage Detection Agent

ClaimIQ was developed as a working prototype using synthetic data,
deterministic claims forensics, configurable rules, AI-assisted
investigation, and an auditable human-review workflow.

------------------------------------------------------------------------

## 👥 Team

Built by the ClaimIQ team for the Azentio.ai Build Labs HackCulture
challenge.

------------------------------------------------------------------------

## 📜 License

This project was created for the hackathon prototype and demonstration.

------------------------------------------------------------------------

### ClaimIQ

**Find the leakage before you pay.**
