## 2️⃣ The TODO checklist (this is the core deliverable)

This is the **exact checklist** I would hand a senior engineer to do this safely.

You can paste this into Jira, Notion, or a markdown file.

---

### ✅ PHASE 0 — Safety & baselines (DONE / CONFIRMED)

* [x] Back up original CSS files
* [x] Restore original menu / sidebar behavior CSS
* [x] Move `{% tailwind_css %}` after custom CSS
* [x] Ensure `<body>` always has `dark` or `light`
* [x] Confirm app loads with no visual regressions

**Rule:** Nothing gets deleted before Phase 4.

---

### 🟡 PHASE 1 — Introduce semantic layer (NO behavior changes)

* [ ] Add new `theme.css` (semantic classes only)
* [ ] Load `theme.css` **after existing CSS**
* [ ] Define first semantic classes:

  * `.card`
  * `.card-padded`
  * `.label`
  * `.row`
  * `.row-between`
  * `.btn`
  * `.btn-primary`
  * `.text-muted`
  * `.stat-value`
  * `.container-soft`
* [ ] Do **not** use these classes anywhere yet

**Success condition:** App looks identical.

---

### 🟡 PHASE 2 — Opt-in usage (low-risk surfaces only)

Target **non-interactive UI only**.

* [ ] Dashboard stat cards
* [ ] Summary panels
* [ ] List containers
* [ ] Info boxes

Checklist per template:

* [ ] Replace `bg-white border shadow rounded` → `.card`
* [ ] Replace padding utilities → `.card-padded`
* [ ] Replace label text clusters → `.label`
* [ ] Leave menus, modals, settings untouched

**Rule:** No menus. No sidebars. No overlays.

---

### 🟡 PHASE 3 — Codex-assisted cleanup (mechanical refactors)

* [ ] Run Codex on 5–10 templates at a time
* [ ] Only allow:

  * semantic class replacement
  * no layout changes
  * no JS changes
* [ ] Review diffs before commit
* [ ] Commit frequently

**Success condition:** HTML readability improves, visuals unchanged.

---

### 🟠 PHASE 4 — Dark-mode override isolation (NOT deletion yet)

* [ ] Identify dark-mode rules that target:

  * `.bg-*`
  * `.text-*`
  * `.border`
* [ ] Add a temporary safety flag (e.g. `.tailwind-legacy`)
* [ ] Verify which overrides are still needed
* [ ] Stop introducing new Tailwind color classes

**Rule:** Replace usage before deleting rules.

---

### 🔴 PHASE 5 — Cleanup (only when confident)

* [ ] Remove unused dark-mode overrides
* [ ] Remove dead Tailwind color usage
* [ ] Optional: split menu CSS into `components.css`
* [ ] Final visual pass

---

## 3️⃣ How you transition to working directly with Codex

This is important. You don’t want to re-explain context every time.

### A. Create a **Codex “house rules” prompt** (save this)

Use this as the **system / project prompt** in Codex:

```
This is a Django app using Tailwind CSS with a semantic CSS layer.

Rules:
- Do NOT modify menus, sidebars, modals, overlays, or settings panels
- Do NOT change JavaScript or Django template logic
- Prefer semantic classes from theme.css over Tailwind utility clusters
- Never introduce new bg-*, text-*, or border-* color utilities
- Preserve responsive prefixes (md:, lg:)
- If unsure, leave code unchanged

Goal:
Reduce Tailwind utility noise by replacing repeated class patterns
with semantic classes such as card, label, row, btn, etc.
```


---

Step B — You use narrow Codex prompts

These go directly into Cursor.

🔹 Prompt 1 — Card refactor
Refactor this Django template.

Replace Tailwind utility class combinations that represent
card-like containers (bg-white, border, rounded-*, shadow, p-*)
with the semantic classes `card` and `card-padded`.

Do NOT modify:
- sidebar
- menu
- settings
- toast
- header
- any JavaScript hooks

Preserve all Django template logic.
If unsure, leave the code unchanged.

🔹 Prompt 2 — Label normalization

Follow the project Codex House Rules in /docs/codex-house-rules.md.
Go down the list of files, checking them off as you go, in the /docs/template_tracking.md file and do the following,

Replace repeated label-style Tailwind utility classes
(text-xs, uppercase, text-gray-500 or text-gray-600, font-medium or font-semibold)
with the semantic class label.

Preserve all other classes (e.g. truncate, spacing, layout).
Do not modify menus, sidebar, header, settings, or toast UI.
Do not change HTML structure or Django template logic.


-----
🔹 Prompt 2 — Normalize row-between:

Follow the project Codex House Rules in /docs/codex-house-rules.md.
Go down the list of files, checking them off as you go, in the /docs/template_tracking.md file and do the following,

Normalize horizontal row layouts with spaced content.

Replace repeated Tailwind utility combinations equivalent to:
flex + items-center + justify-between
(with or without gap utilities)
with the semantic class `row-between`.

Preserve any additional utilities such as text size,
responsive prefixes, or spacing.

Do NOT modify:
- responsive behavior
- menus, sidebar, header, settings, or toast UI
- Django template logic

If justify-between is not present, do nothing.
Output only the modified file.


----
🔹 Prompt 2 — Normalize row:

Follow the project Codex House Rules in /docs/codex-house-rules.md.
Go down the list of files, checking them off as you go, in the /docs/template_tracking.md file and do the following,

Normalize simple horizontal alignment rows.

Replace repeated Tailwind utility combinations equivalent to:
flex + items-center
with the semantic class `row`.

Preserve spacing utilities (gap-*, space-x-*)
and any non-structural classes.

Do NOT modify:
- responsive behavior
- menus, sidebar, header, settings, or toast UI
- Django template logic

If additional layout logic is present, leave unchanged.
Output only the modified file.

----
🔹 Prompt 2 — Normalize card:

Follow the project Codex House Rules in /docs/codex-house-rules.md.
Go down the list of files, checking them off as you go, in the /docs/template_tracking.md file and do the following,

Normalize card-like containers.

Replace repeated Tailwind utility combinations that represent
card surfaces (bg-white or bg-gray-*, border, rounded-*, shadow,
padding utilities)
with the semantic classes `card` and `card-padded`.

Preserve any layout, grid, or width utilities.

Do NOT modify:
- menus, sidebar, header, settings, or toast UI
- responsive behavior
- Django template logic

If the container is not clearly a card surface, leave unchanged.
Output only the modified file.



🔹 Prompt 3 — Audit only (no changes)
Scan these templates and list elements that could be replaced
with semantic classes (card, label, row, row-between).

Do not make any changes.
Return a short list with line numbers.


This prompt is extremely safe and very useful.

---

### C. Your stopping rule (very important)

If Codex:

* touches menus
* edits JS
* changes layout
* removes classes it shouldn’t

👉 **Stop, revert, tighten the prompt**

That’s not failure — that’s correct usage.

---

## 4️⃣ One final reassurance

You did not mess this up.

What you actually did was:

* Identify where behavior CSS lives
* Protect it
* Put infrastructure in place
* Choose a checklist-driven approach

That’s exactly how big, scary refactors succeed.



---
2. How to use the audit list (the missing step)
The correct workflow is one replacement at a time, not batch edits

You do this loop, repeatedly:

🔁 The Semantic Refactor Loop

Pick ONE item from the audit list
(literally one line number)

Apply the semantic class in place

Keep all other classes

Add the semantic class

Optionally remove redundant utilities

Reload the page

If nothing changes visually → keep it

Commit after a few small wins