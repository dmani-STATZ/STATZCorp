---
version: pwa-navigation-fix
publish_date: 2026-06-03
title: PWA Navigation Fix
severity: fix
---

## What Changed
Navigation links in the Contracts Dashboard and throughout the application now
stay inside the STATZ PWA window instead of pushing it to the background.

## Action Required  PWA Users Must Reinstall
If you use STATZ as an installed PWA in Microsoft Edge, **you must reinstall
the app** after this update for the fix to take full effect.

**Steps to reinstall:**
1. In Edge, click the **three-dot menu (...)** in the top-right corner.
2. Go to **Apps  Manage apps**.
3. Find **STATZ Corporation**, click the three-dot menu next to it, and select **Uninstall**.
4. Navigate back to the STATZ web address in Edge.
5. Edge will prompt you to reinstall  click **Install** when it appears.

If you do not reinstall, you may continue to experience the background-window
issue until the browser refreshes the cached manifest on its own (which can
take several days).
