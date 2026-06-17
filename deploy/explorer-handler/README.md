# STATZ Open in Explorer — Desktop Handler

## Overview

The STATZ document browser can open contract SharePoint folders directly in **Windows Explorer** via a custom URL scheme: `statzfile://`.

Django derives these URIs read-only from the contract's SharePoint drive-relative path (`build_explorer_uri()` in `contracts/services/sharepoint_paths.py`). The browser navigates to a `statzfile:///` URI; Windows invokes this handler, which resolves the path under `%USERPROFILE%` and launches Explorer.

Example URI:

```
statzfile:///OneDrive%20-%20statzcorpgcch/Statz%20-%20V87/aFed-DOD/Contract%20SPE3SE-26-V-0530
```

Maps to:

```
%USERPROFILE%\OneDrive - statzcorpgcch\Statz - V87\aFed-DOD\Contract SPE3SE-26-V-0530
```

## Deployment (Intune / manual)

1. Copy `open-explorer.ps1` to **`C:\ProgramData\STATZ\open-explorer.ps1`** on each workstation.
2. Import `statzfile.reg` to register the `statzfile://` protocol (requires admin / Intune registry policy).
3. Configure **Microsoft Edge** to allow the custom protocol from the STATZ web origin via the **AutoLaunchProtocolsFromOrigins** policy:

   ```json
   [
     {
       "allowed_origins": ["https://your-statz-host.example"],
       "protocol": "statzfile"
     }
   ]
   ```

   Without this policy, Edge may block silent navigation to `statzfile://` from the document browser.

## OneDrive / V87 sync note

The local mount folder name **`Statz - V87`** must match the user's synced OneDrive library. When IT bumps the SharePoint library version (currently **V87**), update these Django settings together:

- `SHAREPOINT_PATH_PREFIX`
- `EXPLORER_SHAREPOINT_STRIP_PREFIX`
- `EXPLORER_LOCAL_MOUNT`

Workstations must have the matching OneDrive sync folder before "Open in Explorer" will succeed.

## Logging

Handler activity is appended to `C:\ProgramData\STATZ\logs\open-explorer.log`.

## Files

| File | Purpose |
|------|---------|
| `open-explorer.ps1` | Protocol handler script |
| `statzfile.reg` | Windows registry entries for `statzfile://` |
| `README.md` | This document |

These artifacts are version-controlled for Intune packaging; Django does not execute them at runtime.
