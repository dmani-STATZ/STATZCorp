---
title: Save Contract Button — Visibility and Dirty State Indicator
date: 2026-05-22
app: processing
type: improvement
---

**Save Contract button now shows label and unsaved changes indicator.**

- Button now displays "Save Contract" text alongside the floppy disk icon so it is clearly identifiable as a save action.
- Contract Type and Sales Class dropdowns now auto-save on change, consistent with all other contract-level fields.
- When any contract field is edited, the button turns amber and reads "Unsaved Changes" to indicate there are pending saves. It returns to normal after a successful save.
- Fixed a false "Leave site?" warning that appeared even when no contract fields had been changed.
- The New Contract Notification email compose page now uses a minimal shell with a STATZ header only — nav links, notification bell, Contract Menu, and Reminders are removed for a cleaner focused send experience.
