---
id: 2026-09-14-pdf-intake-parse-error-swallowing-fix
title: Fixed award PDFs being rejected with a misleading "could not extract a contract number" error
published: true
publish_date: 2026-09-14
tags: [fixed, contracts]
critical: false
---

## What was wrong

Dragging a perfectly normal award PDF onto the Contracts Intake queue could fail with:

> `<filename>: could not extract a contract number.`

The message was wrong. In these cases the contract number — along with the buyer, award date, contract value, contractor, and CLINs — had already been read out of the PDF successfully. An unrelated internal error then fired at the very end of parsing, and the parser threw away everything it had just extracted and reported the result as if the document were unreadable.

This was intermittent and looked random, because it only happened when a background AI-assisted extraction step (CLIN, IDIQ supplier, or CMMC detection) happened to fail first — for example when the Anthropic API was briefly unavailable or rejected an unusually large document. Those steps are designed to fail quietly and let parsing continue, but the act of writing their warning to Application Insights was itself crashing, which cancelled the whole parse.

The underlying cause was an incompatibility between the Application Insights logging handler and Python 3.13+, which left the handler without a working internal lock. Every warning or error routed to Application Insights raised an exception back into whatever code was doing the logging. Because the intake parser logs from inside its own error handling, the failure escaped and destroyed an otherwise-complete parse.

## What changed

- The Application Insights log handler now has a working lock, so writing a log record can no longer raise an exception back into the calling code. This affects every app that logs warnings or errors in production, not just Contracts Intake.
- Award PDF parsing now writes a full traceback to the server logs whenever it fails, instead of only a one-line message. Previously the flattened error text shown in the UI was the only record that anything had gone wrong, which made these failures very hard to diagnose.
- The user-visible behaviour for genuinely unreadable PDFs is unchanged: a scanned or corrupt document still reports that text could not be extracted.

If you previously had a PDF rejected with "could not extract a contract number" and the document looked fine, re-upload it — it should now go through.
