### Gemini
Evaluating your two options requires looking closely at how **SharePoint Sync** interacts with your environment. Because SharePoint sync downloads files directly into the local user profile on the AVD (e.g., `C:\Users\...\`), the architecture of your solution matters significantly.

---

### Evaluating Your Options

#### Option 1: Add a Feature inside STATZWeb (Superuser UI)

* **The Hurdle:** STATZWeb is a web application (likely hosted on a web server or IIS). Web servers **cannot** see a user's local AVD synced SharePoint folder because SharePoint sync is tied to individual user profiles on specific virtual desktops.
* **The Workaround:** To make this work inside STATZWeb, you would have to rewrite the file-scanning logic to use the **Microsoft Graph API** to query SharePoint online directly, rather than scanning the local sync folder. In a **GCC-High** tenant, setting up Graph API authentication (App Registrations, Certificates, GCC-High endpoints `graph.microsoft.us`) can involve strict compliance and admin approval overhead.

#### Option 2: Standalone Windows Program on Desktop (GUI)

* **Why this fits best:** Since the files are already synced locally via SharePoint sync, a desktop application running in the user's AVD session can directly read the local directory path using standard file I/O (`System.IO`).
* **Bypassing CLI Restrictions:** By building a lightweight **Windows Forms or WPF graphical application**, you avoid command-line restrictions entirely. Users simply double-click the app (or launch it from a shortcut), use a clean UI to click "Run Scan," and watch the progress bars.

---

### Recommended Blueprint: Standalone Windows GUI App

If you go with **Option 2**, here is how you can design and deploy it cleanly within a GCC-High AVD environment:

* **Tech Stack:** C# .NET (.NET 8) compiled as a **single-file, self-contained executable** (`.exe`). This packages the .NET runtime directly into the executable, meaning it doesn't require pre-installing frameworks on the AVD golden image.
* **File System Access:** Uses standard C# directory enumeration (`Directory.GetFiles` / `EnumerateFiles`) targeting the local SharePoint sync sync path.
* **Database Connection:** Uses standard SQL client libraries to connect securely to your `STATZWeb` SQL Server database using Windows Authentication or encrypted connection strings.
* **GCC-High / AVD Considerations:**
* **Execution Policies:** Ensure the executable is placed in an approved directory (or signed if your organization's AppLocker/EDR policies require it) so it doesn't get blocked from running.
* **Permissions:** The app runs with the permissions of the logged-in user, meaning it will automatically respect whatever SharePoint sync and SQL access that specific user is authorized to have.



---

Would you like a basic C# Windows Forms template or code structure for scanning the local sync folder and updating your SQL Server database?


### Claude Sonnet 5.5
Short version: your two options aren't really equivalent, and one of them has a hole in it.

**The web app option can't see the sync folder.** STATZWeb runs on Azure, so it has no access to a folder synced onto an AVD. What it *can* do is scan the SharePoint side directly through Microsoft Graph with an app registration. In GCC High that means `graph.microsoft.us` and `login.microsoftonline.us`, and it's cleaner to scope it with `Sites.Selected` than to grant `Sites.Read.All`. So the web app only works if you don't actually need the local sync view.

**The desktop option has a different catch.** "Restricts running CLI processes" could mean a few things:
- AppLocker or WDAC blocking cmd/PowerShell/python only. A self-contained GUI .exe may run fine.
- An allowlist that blocks any unsigned or unknown exe. Then your self-contained program won't launch either, and you'd need a code-signing cert or a hash/publisher rule from whoever owns the AVD policy.

Your hands-on test is to drop a throwaway "hello world" GUI exe on the AVD and see if it launches. That's a 10-minute test that could save you a week.

**My lean:** a hybrid, not either/or.
1. A self-contained Windows GUI tool (.NET single-file, since `Microsoft.Data.SqlClient` ships inside it and you don't need an ODBC driver installed) walks the sync folder and compares it against STATZWeb's SQL data.
2. Optionally it writes results to a table, so a superuser page in STATZWeb can display them later. You get the nice UI without the web app ever needing disk access.

Watch out for these in the sync folder:
- **Files On-Demand placeholders:** reading file contents triggers a download of everything. Stick to metadata (names, sizes, attributes), and compare against Graph's `quickXorHash` if you need integrity checks.
- **Path length:** paths over 260 characters can bite you.
- **Stale sync state:** "present locally" doesn't mean "current in SharePoint."

Before I build anything, I need to know:
1. What is the scan actually *for*: missing files, orphaned DB records, duplicates, or sync-drift detection? That decides whether the local side matters at all.
2. Does the AVD policy block only shells and scripting, or also unsigned exes? Do you have a signing cert?
3. Can the AVD reach the SQL Server directly, and with what auth: Windows integrated, SQL login, or Entra?

Answer those and I'll sketch the architecture and, if you want, the zero-ambiguity build prompt for it.


### ChatGPT
Given your constraints, I would frame the two options this way:

### Option 1 — Add it to STATZWeb

A **Superuser-only administration page** inside the existing Django application.

It would:

1. Connect directly to the existing SQL Server database.
2. Let you select/configure what to scan.
3. Scan the SharePoint-synced filesystem from the machine running STATZWeb.
4. Compare the filesystem against the database.
5. Display results in a browser UI.
6. Potentially provide actions such as:

   * Missing files
   * Unexpected files
   * Database records with no corresponding file
   * Duplicate/mismatched files
   * File metadata discrepancies
   * Rescan/recheck
7. Keep the entire workflow inside the existing STATZWeb security boundary.

**The big problem:** where does the filesystem scan actually execute?

If STATZWeb is running in Azure/GCC High, it cannot simply see the SharePoint-synced files sitting on your AVD workstation. You would need some component running on the AVD machine to perform the filesystem access.

That starts turning the "simple Django feature" into a client/agent architecture.

---

### Option 2 — Standalone Windows program

A **single self-contained Windows executable** that you launch manually on the GCC-High AVD.

Something like:

```text
STATZ File System Scanner.exe
```

It would have its own UI and would:

```text
┌─────────────────────────────────────┐
│       STATZ File System Scanner     │
├─────────────────────────────────────┤
│                                     │
│ SQL Server:  [configured/default]   │
│ Database:    STATZWeb               │
│                                     │
│ SharePoint:  [Select Folder]        │
│                                     │
│ [ Scan ]                            │
│                                     │
├─────────────────────────────────────┤
│ Scan Results                        │
│                                     │
│ ✓ 1,247 files checked               │
│ ⚠  12 files missing                │
│ ⚠   3 unexpected files             │
│ ✓ Database records matched          │
└─────────────────────────────────────┘
```

The important part is that **the executable itself performs everything**:

* SQL Server connection
* Filesystem access
* SharePoint-synced-folder access
* Scanning
* Comparison logic
* UI
* Logging
* Results

No Python installation.

No `pip`.

No PowerShell script.

No command-line dependencies.

No separate service.

No Docker.

No requirement to modify STATZWeb.

You launch the `.exe`, it runs, and you close it.

### For your particular situation, I would lean toward Option 2.

The SharePoint sync is the deciding factor.

Your problem isn't really a web-application problem. It's a **local filesystem + database reconciliation problem** that happens to involve SharePoint.

The standalone program can run **on the exact computer that has the SharePoint files available through OneDrive/SharePoint sync**.

That gives you:

```text
                 GCC-High AVD
        ┌──────────────────────────┐
        │                          │
        │  SharePoint/OneDrive     │
        │       Sync               │
        │          │               │
        │          ▼               │
        │   Local synced files     │
        │          │               │
        │          │               │
        │    ┌─────▼─────────┐     │
        │    │ STATZ Scanner │     │
        │    │     .exe      │     │
        │    └─────┬─────────┘     │
        │          │               │
        └──────────┼───────────────┘
                   │
                   ▼
             SQL Server
             STATZWeb
```

And because it is **on-demand**, you don't have to introduce another continuously running service into your CMMC/GCC-High environment.

### One important wrinkle

You said:

> "I need to be able to run this on a GCC-High computer (AVD) that restricts running CLI processes"

That actually makes the standalone approach **more attractive**, but the implementation technology matters.

I would **not** build this as a Python executable that launches a hidden Python runtime. I would build a native Windows desktop executable that doesn't require an installed runtime.

Given your existing environment, I'd look at:

**C# / .NET desktop application → published self-contained `.exe`**

That gives you a normal Windows GUI application:

```text
STATZFileScanner.exe
```

rather than:

```text
python scanner.py
```

or:

```text
run_scanner.bat
```

The distinction matters in your AVD environment.

It also gives us straightforward access to:

* Windows filesystem APIs
* NTFS metadata
* OneDrive/SharePoint-synced paths
* SQL Server
* Windows authentication if appropriate
* encrypted configuration
* Windows Credential Manager if needed
* normal Windows dialogs
* a proper GUI

And you could eventually make the UI fairly slick without making it another STATZWeb subsystem.

### I would also avoid making it dependent on SharePoint APIs

At least initially.

If the SharePoint library is already synchronized onto the AVD, the scanner doesn't need to know that the files came from SharePoint.

It can simply see:

```text
C:\Users\Dion\STATZ Corp\Sales\...
```

and treat that as a filesystem.

That is actually a major simplification.

The scanner's job becomes:

**"Given this database and this folder, tell me whether the database and filesystem agree."**

That's a clean standalone tool.

If you give me the **specific thing you want the scanner to compare between SQL Server and the SharePoint files**, I can lay out the architecture and recommend exactly how I'd build the Windows executable.



### Copilot
Honestly, given your constraints, I would strongly lean toward building this into STATZWeb rather than creating a desktop program.

Why I would avoid a standalone Windows executable

Your requirements create several challenges:

GCC High / AVD environment
Restrictions on running CLI processes
Need access to SQL Server
Need access to SharePoint files
Need ability to scan local synced folders
Need something that can be executed on-demand by privileged users

A desktop executable sounds simpler initially, but you'll end up fighting:

Deployment/versioning
Security approvals
Code signing
Local machine dependencies
Future AVD policy changes
SharePoint authentication

Every time IT changes something, you're potentially back debugging the desktop application.

Option 1 (Recommended): Add a SuperUser Admin Tool to STATZWeb

Create a new module:

Admin
 └── File Inventory Scanner
      ├── Select root path
      ├── Run Scan
      ├── View Progress
      ├── Review Discrepancies
      └── Save Results

Architecture
STATZWeb
    |
    +-- SuperUser Page
            |
            +-- Scanner Service
                    |
                    +-- SQL Server (STATZWeb)
                    |
                    +-- File System Scan
                           |
                           +-- SharePoint Sync Folder


The scanner would run inside the web application process:

Directory.GetFiles(...)
Directory.GetDirectories(...)


No external executables.

No PowerShell.

No CLI.

No separate service.

No installation.

What it would do
Read records from STATZWeb database.

Example:

SELECT
    DocumentID,
    FilePath,
    FileName
FROM Documents

Scan SharePoint sync location

Example:

C:\Users\User\SharePoint Sync\

Build an in-memory index
Dictionary<string, FileInfo>

Compare
Database File
    Exists?
        Yes
        No

Filesystem File
    In Database?
        Yes
        No

Store results
FileScanResults

Display
Missing Files
Orphaned Files
Duplicate Files
Renamed Files
Size Mismatches
Date Mismatches

Biggest Advantage

The user only presses:

Run Scan


Everything happens from the existing application.

No installation.

No updates.

No separate security review.

Option 2: Self-Contained Windows Utility

If you truly want it outside STATZWeb, I'd make it:

STATZ Scanner.exe


Built with:

.NET 8
WPF
Single File Publish


Publish mode:

PublishSingleFile=true
SelfContained=true


This gives you:

STATZScanner.exe


One file.

No installer.

No .NET dependency.

No CLI.

Double-click and run.

UI
+----------------------------------+
| STATZ Scanner                    |
+----------------------------------+

Database Status: Connected

SharePoint Path:
[Browse]

[Run Scan]

Progress:
██████████░░░░░░ 65%

Results

Missing Files: 12
Orphan Files: 4
Duplicates: 2

[Export]

Technology Choice

I'd use:

WPF
.NET 8
Dapper
SQL Server


Avoid:

WinForms
Electron
PowerShell
Background services

The Third Option (what I'd actually build)

A hybrid.

Inside STATZWeb:

Admin > File Scanner


When the user clicks Run:

Browser uploads local scan manifest.
STATZWeb performs comparison.
Results stored in SQL.

The local component becomes extremely thin.

Scanner.exe
     |
     +-- Enumerate files
     +-- Create JSON manifest
     +-- POST to STATZWeb


All business logic stays in STATZWeb.

Advantages:

Scan runs with local file access.
Comparison logic stays centralized.
Easier maintenance.
Results/history stored in database.
Multiple admins can use it.
My recommendation

70% confidence: Build it directly into STATZWeb as a SuperUser-only feature.

The moment you mentioned:

GCC High
AVD
restricted CLI
SQL Server integration

it became more of a governance problem than a coding problem. Keeping everything inside the existing approved application boundary will almost always be easier to support long term than introducing a new executable, even a self-contained one.

One thing I'd want to understand next is how large the SharePoint library is (10k files, 100k files, 1M+ files) because that single number will drive whether a synchronous scan is fine or whether you'll need a queued/background scanning architecture.