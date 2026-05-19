---
id: 2026-05-19-supplier-dashboard-search-fix
title: Supplier Dashboard — Live search fix
published: false
publish_date: 2026-05-19
tags: [fixed, contracts]
critical: false
---

**Fix: Supplier dashboard search now works correctly.**

The search box on the Supplier Dashboard was unresponsive due to a form submission conflict and a script initialization timing issue. Both have been resolved. Typing a supplier name, CAGE code, or contract number now returns live results as expected. Searches with no matches display a "No suppliers found" message instead of a blank dropdown.

**Fix: Supplier dashboard search no longer errors on lookup.**

Searching by supplier name, CAGE code, or contract number on the Supplier Dashboard was returning a server error (HTTP 500) due to an incorrect database relationship traversal. This has been corrected. All three search types now work as expected.
