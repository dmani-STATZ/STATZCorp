### 🧭 Codex House Rules — CSS & Templates

#### Purpose

This project uses Bootstrap CSS **with a semantic abstraction layer**.
Codex must follow these rules when modifying templates or CSS.

---
Codex must treat theme.css as the single source of truth
for semantic classes. No new semantics may be proposed
unless explicitly instructed.
---
The Contracts app has completed semantic normalization.
Codex must preserve existing semantic classes in contracts/*
and must not reintroduce Bootstrap utility stacks
for card, row, row-between, or label patterns.
---

### 1. Semantic classes are preferred

When encountering repeated Bootstrap utility patterns, prefer these semantic classes:

* `card`
* `card-padded`
* `label`
* `row`
* `row-between`
* `btn`
* `btn-primary`

Semantic classes may coexist with Bootstrap utilities.

---

### 2. NEVER refactor behavioral UI

The following are **hands off** and must not be changed or refactored:

* Sidebar / menu elements
* Settings panel / overlay
* Toast / notification system
* Header / navigation
* Any element with JS hooks or ARIA dialog behavior

If unsure, do not modify.

---

### 3. Do not change layout or logic

* Do not alter HTML structure
* Do not remove Django template logic
* Do not change responsive behavior unless explicitly instructed

---

### 4. Replace, don’t redesign

Allowed:

* Replace `flex items-center justify-between` → `row-between`
* Replace label-style text utilities → `label`

Not allowed:

* Invent new colors
* Change spacing semantics
* Combine unrelated components

---

### 5. One semantic replacement per element

* Apply **one** semantic class at a time
* Preserve non-semantic utilities (`truncate`, `gap-*`, `text-sm`, etc.)

---

### 6. When uncertain, do nothing

If a semantic mapping is not obvious:

* Leave the code unchanged
* Report the location instead

---

## 5. How this changes your day-to-day work

Before:

> “Should I change this?”

Now:

* Run audit prompt
* Pick **one item**
* Apply known mapping
* Commit

You’ve converted a scary refactor into a **mechanical process**.

---

## 6. Why you felt stuck (and why you’re not anymore)

You weren’t missing skill.
You were missing **process glue** between:

* “Codex can see patterns”
* “I can safely act on them”

You now have that glue.

