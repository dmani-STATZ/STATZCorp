# Deploy checklist — Quote app + DIBBS app + UI refresh

Branch `dibbs-app-extraction` → `main`. This release:

- replaces the unused `sales` app with a new `dibbs` app (DIBBS imports, awards, notices, competitors, CAGEs),
- adds the `quote` app (Phases 1–4),
- refreshes the UI across the whole site.

The database changes are **one-way**, so work through this list in order.

---

## 1. Before merging

- [ ] The PR's CI check (tests) is green.
- [ ] Nobody is mid-import in DIBBS. Don't deploy during the nightly award import window.

## 2. Back up production

- [ ] Take a full backup of the production SQL Server database. On Azure SQL, write down the current UTC time so you can do a point-in-time restore.
  - `dibbs/0002` **drops** the old sales workflow tables: RFQs, supplier quotes, matches, inbox and templates. Those tables only ever held test data.
  - `dibbs/0003` **renames** 4 tables:

    | Old name | New name |
    |---|---|
    | `sales_dibbsnotice` | `dibbs_notice` |
    | `sales_competitor*` (3 tables) | `dibbs_competitor_*` |

## 3. Confirm prod has every old `sales` migration (SSMS)

`dibbs/0001` *replaces* all 63 `sales` migrations. Django treats it as already applied **only if all 63 are recorded**. Run this against production:

```sql
SELECT COUNT(*) AS applied, MAX(name) AS latest
FROM django_migrations
WHERE app = 'sales';
```

- [ ] Expected result: `applied = 63` and `latest = 0063_dibbs_award_url_default_constraints`.
- [ ] If the count is lower, **stop**. Deploy `main` as it is today first so the missing `sales` migrations run, then come back to this list.

## 4. Merge and deploy

- [ ] Merge the PR into `main`.
- [ ] Let Azure deploy `main` the usual way.
- [ ] Migrations must run. `startup.sh` only runs them when the App Setting **`RUN_MIGRATIONS=1`** is set. Either:
  - set `RUN_MIGRATIONS=1` for this deploy, **or**
  - run migrate by hand in the App Service SSH console:
    ```bash
    cd /home/site/wwwroot
    /tmp/antenv/bin/python manage.py migrate --noinput
    ```

> **Heads up:** `startup.sh` runs `migrate ... || true`, so a failed migration **will not stop the site from starting**. After deploying, read the log stream for `[startup] Running migrations` and make sure there are no errors.

## 5. Verify the migrations landed (SSMS)

```sql
SELECT app, name FROM django_migrations
WHERE app IN ('dibbs', 'quote') ORDER BY app, name;
```

- [ ] `dibbs`: 0001, 0002, 0003.
- [ ] `quote`: 0001 through 0007.
- [ ] `SELECT TOP 1 * FROM dibbs_notice;` works. It proves the table rename ran.

## 6. Stored procedures and views

- [ ] `usp_process_award_staging` **does not need to be redeployed**. The SQL file only moved from `sales/sql/` to `dibbs/sql/`; its contents are identical.
- [ ] Check the log stream for `verify_stored_procs`. It should report no drift.
- [ ] The two old views `dibbs_supplier_nsn_scored` and `dibbs_solicitation_match_counts` are dropped by `dibbs/0002`. Nothing needs replacing.

## 7. App settings (Azure → Configuration)

- [ ] `GRAPH_MAIL_ENABLED`:
  - `True` means RFQ emails really send from `GRAPH_MAIL_SENDER_RFQ` (`quotes@statzcorp.com` by default).
  - Leave it `False` until you're ready to email suppliers for real. When it's `False`, sends fall back to mailto links.
- [ ] `GRAPH_MAIL_CLIENT_ID` / `GRAPH_MAIL_CLIENT_SECRET` are set, and the app registration can send from, and read, the `quotes@` mailbox. The Mailbox page pulls from it on **Check for new mail**.

## 8. Scheduled tasks

The migrations seed two new `core.ScheduledTask` rows. They run through the existing background-tasks WebJob:

- [ ] `archive_stale_solicitations`: daily.
- [ ] `reconcile_bid_outcomes`: hourly.
- [ ] `send_queued_rfqs` (the old sales task) is removed by `dibbs/0002`. That's expected.

## 9. Smoke test in production

- [ ] Log in. The new header and sidebar show, and dark mode toggles.
- [ ] **DIBBS Data**: dashboard, Imports, Awards and Notices all load.
- [ ] **STATZ Quotes**: dashboard, Solicitations queue and Our Bids all load.
- [ ] Contracts dashboard and a contract page load. The Reminders page loads (it used to 500).
- [ ] Next morning, the nightly DIBBS solicitation import and award import both ran normally.

## Rollback

- **Code only** (the migrations haven't run yet): redeploy the previous `main` commit.
- **After the migrations ran**: the table drops can't be reversed by Django. Restore the database from step 2 **and** redeploy the previous `main` commit.
