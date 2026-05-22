# intake — Release Notes

## Inline Create from Match Modal (2026-05-22)
**User-visible changes:**
- The Match modal now has an **+ Add new** panel for Buyer, NSN, and
  Supplier. Click it to inline-create the canonical record and apply it
  to the draft in one step — no need to leave the editor.
- For new Buyers: enter the buyer description. For new NSNs: enter the
  NSN code (and optionally a description). For new Suppliers: enter the
  name and CAGE code (both required).
- The parsed value pre-fills the obvious field (e.g. the parsed buyer
  text → Buyer description) so analysts don't retype.
- Create-and-apply happens inside the same database transaction; if your
  lock has expired or anything else fails, the new canonical row rolls
  back too — nothing is half-created.

**Behind-the-scenes:**
- `matchers.create_record(match_type, payload)` is the single creator.
  Dedup is enforced (Buyer.description, Nsn.nsn_code, Supplier.cage_code).
- `match_endpoint` learned `action: "create"` and `action: "creatable_types"`.
- IDIQ and Contract are intentionally NOT creatable from the modal —
  they have richer required fields. Use the contracts app's full forms
  for those, then re-Match.


## CLIN Editor Overhaul + GP Split (2026-05-21)
**User-visible changes:**
- CLIN rows are now **expandable cards** with clearly separated **Contract Data** and **Supplier/Quote** sections (replaces the wide flat table).
- **Item Type**, **IA**, and **FOB** fields now show full labels (Production, GFAT, Origin, Destination, etc.) instead of single-letter codes. The single-letter code is still stored under the hood.
- **Supplier Due Date** added to each CLIN.
- **Special Payment Terms** dropdown added to each CLIN (sourced from `SpecialPaymentTerms`).
- Finance lines are now entered **per-CLIN** — the shared root-level Finance Lines table has been removed from the editor.
- Each CLIN has a new **GP Split** section: enter company name + percentage; split dollar value is calculated automatically from planned GP.
- New **GP Summary** block shows per-CLIN planned GP, packaging deduction, and net contract GP — all calculated live as you type.
- **Quote Total** auto-calculates as `unit_price × order_qty` per CLIN.

**Behind-the-scenes:**
- Per-CLIN finance lines and splits land in `ContractFinanceLine` and `ClinSplit` rows respectively on finalization.
- Backward-compat: legacy drafts created before this change carry root-level `finance_lines`. Finalization still accepts these and attaches them to the first CLIN, with a warning logged. The legacy path will be removed once the queue is confirmed clear.
- POST key conventions now include nested `clin-<i>-fin-<j>-<field>` and `clin-<i>-split-<j>-<field>` patterns. See `CONTEXT.md`.

### Editor Polish + Field Fixes (2026-05-21)
**User-visible changes:**
- Fixed: parsed 1155 unit price now correctly populates Item Value
  (government contract price), not Quote Price
- CLIN Item Type now defaults to Production when not specified by parser
- Contractor Name and CAGE fields removed from editor (not tracked)
- Sales Class dropdown added to contract header
- PO Number shown as read-only placeholder in contract header
- Packaging section is now hidden by default; click Add Packaging to open
- Packaging section moved above CLINs
- CLIN cards now start collapsed; expand individually as needed
