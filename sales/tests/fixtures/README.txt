Place two fixture files here before running the awdrecs_parser tests:

  awdrecs_with_rows.html  — Raw HTML from a real AwdRecs.aspx response for a CAGE
                            that has >= 1 award today (or any day with results).
                            Use: curl or browser Save-As after searching by CAGE.

  awdrecs_empty.html      — Raw HTML from a real AwdRecs.aspx response for a CAGE
                            that returned 0 awards (the "No records found" page).

These files are intentionally not committed to source control; they contain
live government data and must be refreshed before each test run if you need
date-accurate CAGE validation.
