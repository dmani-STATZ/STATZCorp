---
id: 2026-09-29-quotes-edit-logged-quote
title: Reopen and edit a logged quote until it goes to DIBBS
published: false
publish_date: 2026-09-29
tags: [new, sales]
critical: false
---

## What Changed
A quote you logged from a message now shows up in the **Log quote** tray, and you can change it. Before, the tray always opened blank, even for a solicitation you had already quoted, and saving again would have made a second copy.

Open the tray on a SOL that already has a quote and you see what you logged. Change it and press **Update quote**; the same quote is updated, nothing is duplicated. The **Edit** button beside each row under the message jumps straight to that quote.

## What You'll Notice
- When a supplier priced a solicitation's lines separately, a **Quote** picker at the top of the tray lists each of their quotes, plus **＋ Quote the other line** for a line they have not quoted yet. With a single quote covering everything there is nothing to pick, so it is left out.
- An edited quote covers the same lines it was logged for. A quote logged for all lines stays all lines; one logged for a single line stays that line.
- A bid you already started follows the change: if it still has the quote's old price or delivery days it picks up the new ones, and a price you typed into the bid yourself is left alone. A bid that was **ready to export** goes back to **Needs bid** so it gets checked again.
- Once a quote's bid has been exported to DIBBS it shows **Sent**. It opens read-only with a note saying which file it went out in. If DIBBS rejected that file, reopen it on the Bid Board and the quote becomes editable again.
- Changes you have not saved are kept if you close the tray or leave the page, and **Undo my changes** puts back what is saved.
- The **Log quote** tray is about 10% smaller so more of the form fits without scrolling. Only that tray changed; the rest of the app is the same size.
- Fixed: a line of stray template text that appeared under the "Quotes logged from this message" table.

## Action Required
None.
