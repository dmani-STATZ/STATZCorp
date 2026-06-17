---
id: 2026-06-10-fk-autocomplete-search
title: Searchable autocomplete for supplier and NSN fields in transaction edit modal
published: true
publish_date: 2026-06-10
tags: [improved, system]
critical: false
---

Staff can now type to search when editing FK fields (Supplier, NSN) in the
transaction edit modal. Previously the dropdown was silently truncated to the
first 500 alphabetical records — with 1,300+ suppliers, only A–F appeared. These
fields now use an AJAX-powered autocomplete that searches as you type (3+
characters). All other FK dropdowns in the modal also gain local search via
Tom Select.
