---
id: 2026-05-19-po-number-deferred-finalization
title: PO Number Assignment — Deferred to Finalization
published: false
publish_date: 2026-05-19
tags: [improved, contracts]
critical: false
---

PO numbers are no longer assigned when a contract is opened for processing. The PO number is now minted at the moment a contract is finalized and submitted. This eliminates gaps in the PO number sequence caused by draft contracts that were cancelled or restarted before completion. The PO number field on the processing form will be empty during drafting and will appear in the finalization confirmation email as before. This change has no impact on QuickBooks — PO numbers continue to be issued sequentially with no gaps.
