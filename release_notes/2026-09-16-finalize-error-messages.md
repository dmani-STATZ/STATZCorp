---
id: 2026-09-16-finalize-error-messages
title: Improved — Save & Finalize now shows a real error message on failure
published: true
publish_date: 2026-09-16
tags: [improved, contracts]
critical: false
---

When Save & Finalize hit an unexpected error, it used to show a cryptic
popup ("Unexpected token '<' ... is not valid JSON") instead of saying
what actually went wrong. Save & Finalize now always returns a real,
readable error message you can act on (or hand to IT) instead of that
generic failure.
