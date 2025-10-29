AI-Driven Reports (Natural Language → Query → Results)

Goal
- Enable users to ask for reports in plain English and receive tabular results and an Excel export, with smart follow‑ups that add fields/joins (e.g., CLIN lines, suppliers, NSNs) without rebuilding from scratch.

Scope
- Primary data domain: the contracts app (models in `contracts/models.py`). If you meant “contacts,” this design still applies; the introspection targets any app label and is set to `contracts` by default.

Current State
- Models: `reports/models.py` has `ReportRequest`, `Report`, `ReportChange` for request, output, and follow‑ups.
- Views: `reports/views.py` already renders a landing page, runs raw SQL, and exports to Excel.
- Schema support: `contracts/utils/contracts_schema.py` builds a schema description for LLM prompts.
- UI: `reports/templates/reports/user_reports.html` is a suitable landing page with a modal to “Request New Report.”

Design Overview
- NLQ pipeline
  - Schema introspection: Build a graph of tables/fields/relations for the `contracts` app via Django introspection (reuse `generate_condensed_contracts_schema(user_query)` for tighter prompts).
  - LLM planning: Prompt the model to produce a structured QueryPlan (JSON), not ad‑hoc SQL. The plan contains base model, filters, selected fields, joins, grouping, order, and limits.
  - Validation: Validate the plan against the Django model graph (whitelist models/fields; check ops/types; cap limits; forbid DML/DDL).
  - Execution: Compile the plan to Django ORM (preferred) or controlled SQL. Paginate and cap row counts. Log/audit queries.
  - Rendering: Show tabular results with column labels; provide immediate Excel export.
  - Follow‑ups: Merge the new instruction into the prior plan (add fields/joins/filters) and re‑execute.

Key Data Model (contracts)
- Contract → Clin (1‑to‑many): `Clin.contract`.
- Clin → Supplier (FK): `Clin.supplier`.
- Clin → Nsn (FK): `Clin.nsn`.
- Additional useful tables: `IdiqContract`, `PaymentHistory`, etc.
  - This supports “new contracts this month,” and follow‑ups like “add CLIN lines, suppliers, NSNs.”

LLM Contract (Structured Output)
- Require a strict JSON object from the LLM:
  - base_model: "contracts.Contract"
  - selects: [{ model: "contracts.Contract", field: "contract_number", alias: "Contract" }, ...]
  - filters: [{ model: "contracts.Contract", field: "award_date", op: "this_month" }]
  - joins: [{ from_model: "contracts.Contract", to_model: "contracts.Clin" }, { from_model: "contracts.Clin", to_model: "contracts.Supplier" }, { from_model: "contracts.Clin", to_model: "contracts.Nsn" }]
  - group_by, order_by, limit, result_mode: "flat" | "nested"
- Only after server validation do we compile to ORM or generate SQL. Optional: also ask the LLM to return an explanation string for UI transparency.

Example Query → Plan
- User: “Can you give me a report for all the new contracts from this month?”
  - Plan: base_model=Contract; filters=[award_date this_month]; selects=[contract_number, award_date].
- Follow‑up: “Add CLIN lines, the suppliers and the NSNs.”
  - Plan update: joins append Clin→Supplier/Nsn; selects append fields for CLIN id/qty/price and Supplier name and NSN code; result_mode may switch to flat for Excel.

Execution Strategy
- Compile to ORM
  - Build QuerySet from `base_model`.
  - Apply filters (interpret helpers like this_month/last_30_days/year=YYYY).
  - Apply joins via `select_related`/`prefetch_related` and `values()` for a flat output.
  - Use annotations for aggregates when requested.
- Guardrails
  - Whitelist models/fields scoped to `contracts`.
  - Enforce SELECT‑only semantics and row caps (e.g., 10k default).
  - Validate ops/field types; reject ambiguous plans.
  - Timeouts and pagination.

UX Flow
- Landing page (in place): `reports:user-reports` lists requests and completed reports; “Request New Report” opens a modal.
- AI creation tool (modal or dedicated page)
  - Step 1: user asks a question; we call the LLM with condensed schema.
  - Step 2: show preview table and column list; “Export to Excel” link.
  - Step 3: follow‑ups create diffed plan updates and rerender.

Storage & Reproducibility
- Save the final QueryPlan JSON with each `Report` for reproducibility and reruns; store the originating question and follow‑ups on `ReportRequest` and `ReportChange`.
- Optionally also save the executed SQL as a snapshot for auditing.

Security & Privacy
- No direct execution of LLM‑provided SQL. Always validate a structured plan.
- Hide credentials; route keys via settings/env. Never hardcode tokens.
- Add role‑based access to restrict sensitive fields/tables.

Excel Export
- Reuse existing `export_report` view; extend it to consume the same compiled dataset (from the QueryPlan) so UI and export are consistent.

Implementation Plan (phased)
- Phase 1: Core plumbing
  - Add `reports/services/nlq.py` with `QueryPlan` dataclasses, validator, and a basic compiler to ORM (Contract/Clin path).
  - Add a JSON field to `Report` (or use a related config model) to persist the QueryPlan.
  - Switch `ai_generate_report_view` to request JSON plans from the LLM and compile them server‑side.
- Phase 2: Follow‑ups & UX polish
  - Add a “Continue refining” chat strip on `report_view.html` to apply `ReportChange` as deltas to the saved plan.
  - Add column chips/toggles and quick filters UI.
- Phase 3: Aggregations & caching
  - Support group_by/aggregations in the planner and compiler.
  - Cache compiled results for re‑downloads.

Notes
- This design deliberately centers ORM compilation to minimize SQL‑injection risk and keep cross‑DB portability. When raw SQL is necessary, validate with a parser and strict whitelists.
