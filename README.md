# GradScout

Finds graduate-school funding (PhD, Master's, fellowships, scholarships, application fee waivers, RA/TA), scores it against your profile, and tracks your applications, all in one Excel workbook. Trainee programmes, internships and jobs are out of scope (a separate tool later).

## Setting up for yourself
GradScout is built around one applicant. To use it for yourself:
1. Install Python 3.10+ and create the environment: `python -m venv .venv`, then `.venv\Scripts\python.exe -m pip install -r requirements.txt` (on macOS/Linux: `.venv/bin/python`). The home window (`GradScout.bat`) is Windows-only; the MCP server and tests are not.
2. Write `profile/profile.md` (create the folder). This is what Fit is scored against: your degree and grades, research interests, target level (PhD / Master's), target intake, citizenship, languages, and any must-haves or exclusions. Without it the tools return "profile.md not found". `profile/` is git-ignored, so it stays on your machine.
3. Register the server with Claude Code: `claude mcp add gradscout --scope user -- <path-to>/.venv/Scripts/python.exe <path-to>/app/server.py`.
4. Optional: connect Gmail in Claude (for LinkedIn and FindAPhD alert emails) and add a scheduled task that runs the refresh; both are set up in the Claude app, not in this repo. The sender list is in the home window's settings.

`data/` (workbook, settings, search log, backups) is created on first use; set `GRADSCOUT_DATA` to keep it elsewhere. Defaults such as refresh days, alert windows and requirement checklists are in `data/settings.json` and the home window.

## Everyday use
- **Home window:** double-click `GradScout.bat`. Shows your shortlist counts, applications by stage, what is due soon (double-click to open the link), the last search per source, and every setting.
- **Spreadsheet:** `data/GradScout.xlsx` (or "Open spreadsheet" in the home window).
- **Claude:** just chat. Examples:
  - "Run a GradScout refresh."
  - "Start an application for the UBC PhD; next action: email supervisors by 10 November."
  - "Mark the CV done for VISTEC and set the fee status to Waived."
  - "What's due in the next two weeks?"
  - "Promote the Ghent one back to the shortlist."
  - "Re-scan the last 30 days, ignoring history."

## Automatic refresh
A Claude scheduled task, **GradScout refresh**, runs daily at 10:00 while the Claude app is open (a missed run happens on next launch). On your refresh days (default Mon and Thu) it searches Gmail and all sources, scores and records everything, then reports new finds, deadlines and next actions; on other days it only reports what is due. Change the days, alerts and on/off switch in the home window ("Refresh & alerts"); change the time by asking Claude.

## The workbook (nothing is ever deleted)
| Sheet | What it holds |
|---|---|
| Opportunities | Shortlist: High and Medium fit. Fit colours, Days left, Open? (Open / Closed / Check), clickable links, dropdowns. |
| Applications | What you are applying to, grouped like your 2025 tracker: Opportunity, Dates, Progress (stage, next action, date), Application fee (status, amount, waiver route), Requirements checklist (Required / In progress / Done / N/A), Outcome. |
| Reviewed (not shortlisted) | Everything read but judged Low fit, with the reason, plus "Unscored" items that were shown but never recorded. |
| Parked (jobs & internships) | Out-of-scope items kept for the future jobs tool. |
| Search log | Which time window each source covered. |

- **Status column** (dropdown on Opportunities, Reviewed and Parked; each value has its own colour):

  | Status | Colour | Meaning | Effect |
  |---|---|---|---|
  | New | Blue | Just found, not yet looked at | None |
  | Interested | Purple | You might pursue it | None; a marker for you |
  | Applying | Orange | You have decided to apply | The next sync creates an Applications row |
  | Applied | Green | Submitted | Set automatically when the application Stage becomes Submitted; setting it by hand does not create an application |
  | Rejected | Red | Turned down | Dropped from due-soon alerts |
  | Skip | Grey | Not pursuing | Dropped from due-soon alerts |

  Status is only read from the spreadsheet for **Applying**. The application Stage drives Status (Stage to Status, not the reverse), so update the Stage on the Applications sheet as you progress.
- **Starting applications:** set a row's Status to **Applying** in Excel (Opportunities or Reviewed), then ask Claude "sync applications" (or wait for the next scheduled run, which does it automatically). Every Applying row without an application gets one, with the checklist pre-filled. You can still say "Start an application for X" for a single one.
- Changing Fit moves a row between Opportunities and Reviewed; starting an application sets the opportunity's Status to Applying, and the application Stage keeps it in sync.
- Requirement checklists are pre-filled per type from the defaults in the home window ("Applications" tab); Claude then checks the official page.
- Close the workbook in Excel before Claude updates it; otherwise the write is refused with a clear message (search results are kept and recorded next time).
- **Backups:** the first save each day copies the workbook to `data/backups/` (30 days kept).

## Search memory
Every search records the window it covered; the next run starts there (minus a 24-hour overlap), so nothing is searched twice. Gmail uses an exact timestamp and remembers threads already read. Results already in the workbook are not returned again. "Reset search history" (Search tab) starts over. To search a fixed date range, ask Claude (for example "Opportunities Pedia, 1-30 September"): it passes `since` and `until`, skips anything already in the workbook, and does not write the search log, so the normal "last run" marker is unaffected.

## Sources
- **Email:** LinkedIn notifications from accounts you follow, FindAPhD alerts (FindAPhD blocks automated access, so alerts are the way in). Senders are listed in settings.
- **Server searches:** Opportunities Pedia (public API), Scholars4dev and Opportunity Desk (public search feeds), Grants.gov (US federal funding; mostly institution-level).
- **Claude directly:** EURAXESS, official funder pages (DAAD, Chevening, Commonwealth, Erasmus Mundus, Swedish Institute, Gates Cambridge, Eiffel, MEXT) and the open web.
- Skipped: ProFellow (blocks automated requests), scholarship-positions.com (feed redirects to an unrelated domain).

## Profile and matching
`profile/profile.md` (built from your CV, statements and letters in `profile/Personal Data Resource/`) drives Fit: High / Medium / Low with a reason and an eligibility note for a Nigerian citizen. Edit it when your goals change.

## Folder layout
```
GradScout.bat      home window
app/               config.py, store.py (workbook), sources.py (searches), server.py (MCP tools), gui.py
tests/             pytest suite (network mocked)
data/              GradScout.xlsx, settings.json, search_log.json, pending_review.json, backups/
profile/           profile.md, Personal Data Resource/
```
`data/` and `profile/` are kept out of git on purpose.

## Maintenance
- Run tests: `.venv\Scripts\python.exe -m pytest -q`
- The MCP server is registered for all Claude sessions as `gradscout` (`claude mcp list`). After code changes, start a new Claude session (or restart the app) so the server reloads; settings changes need no restart.
- Recreate the environment: `python -m venv .venv` then `.venv\Scripts\python.exe -m pip install -r requirements.txt`.
