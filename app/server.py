"""GradScout MCP server: finds graduate-school funding and tracks applications in GradScout.xlsx.

Tools only; storage lives in store.py, searches in sources.py, settings in config.py.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

import config as cfg  # noqa: E402
import sources  # noqa: E402
import store  # noqa: E402

INSTRUCTIONS = """GradScout tracks graduate-school opportunities (PhD, Master's, fellowships, scholarships,
fee waivers, RA/TA) for one applicant. Workflow for a refresh:
1. get_profile and refresh_plan.
2. Gmail: search the senders in settings with after:<gmail_after_epoch>, keep only new_threads, read them,
   then log_run(source='gmail', thread_ids=[...]).
3. Run search_opportunitiespedia / search_scholarship_sites / search_grants_gov for each keyword
   (they remember what they covered).
4. Score every result against the profile (Fit High/Medium/Low, reason, eligibility for a Nigerian citizen,
   checked on the official page when it matters) and record ALL of them with add_opportunities.
5. Finish with get_digest and report High/Medium finds, deadlines and next actions.
Nothing is ever deleted. Trainee programmes, internships and jobs are out of scope."""

mcp = FastMCP("gradscout", instructions=INSTRUCTIONS)

TYPE_FROM_CATEGORY = {"Scholarship": "Scholarship", "Fellowship": "Fellowship", "RA/TA": "RA/TA",
                      "Fee waiver": "Fee waiver"}
STATUS_FROM_STAGE = {"Preparing": "Applying", "Submitted": "Applied", "Interview": "Applied", "Offer": "Applied",
                     "Rejected": "Rejected", "Withdrawn": "Skip"}


# ---------------------------------------------------------------- profile and settings

@mcp.tool()
def get_profile() -> str:
    """Return the applicant profile (background, interests, targets, eligibility facts, Fit rubric). Read it before scoring results."""
    return cfg.PROFILE.read_text(encoding="utf-8") if cfg.PROFILE.exists() else "profile.md not found"


@mcp.tool()
def get_settings() -> dict:
    """Return all settings (search keywords, exclude terms, sources, Gmail senders, time windows, auto refresh, alerts, requirement defaults)."""
    return cfg.load_settings()


@mcp.tool()
def update_settings(changes: dict) -> dict:
    """Change settings; same keys as get_settings. The GUI edits the same file, and no restart is needed."""
    problems = cfg.validate_settings(changes)
    if problems:
        return {"error": problems, "valid_keys": list(cfg.DEFAULTS)}
    settings = cfg.load_settings()
    settings.update(changes)
    cfg.save_settings(settings)
    return settings


@mcp.tool()
def refresh_plan() -> dict:
    """What a refresh should do today: whether auto refresh is due, keywords, sources, Gmail senders and the Gmail start time."""
    settings = cfg.load_settings()
    today = cfg.DAYS[date.today().weekday()]
    gmail = get_last_run("gmail")
    return {"today": today, "auto_refresh": settings["auto_refresh"],
            "refresh_due_today": settings["auto_refresh"] and today in settings["refresh_days"],
            "keywords": settings["keywords"], "sites": settings["sites"], "gmail_senders": settings["gmail_senders"],
            "gmail_after_epoch": gmail["gmail_after_epoch"],
            "gmail_default_window_days": settings["default_window_days"]}


# ---------------------------------------------------------------- search memory

@mcp.tool()
def get_last_run(source: str, query: str = "") -> dict:
    """What was last searched for a source ('gmail', 'opportunitiespedia', 'scholars4dev', 'opportunitydesk', 'grants.gov').

    Returns the last run, `suggested_since` (its window end minus the overlap) and `gmail_after_epoch`
    (use as after:<epoch> in Gmail so only newer mail is read). With no history both are null and the
    default look-back applies.
    """
    last = sources.last_run(source, query)
    if not last:
        return {"last_run": None, "suggested_since": None, "gmail_after_epoch": None,
                "default_window_days": cfg.load_settings()["default_window_days"]}
    since = sources.parse_ts(last["window_end"]) - timedelta(hours=cfg.load_settings()["overlap_hours"])
    return {"last_run": last, "suggested_since": sources.ts(since), "gmail_after_epoch": int(since.timestamp())}


@mcp.tool()
def log_run(source: str, query: str = "", window_start: str = "", window_end: str = "",
            found: int = 0, added: int = 0, thread_ids: list[str] = []) -> str:
    """Record a search Claude ran itself (mainly Gmail) so the same period is not searched again.

    window_end defaults to now (UTC ISO). thread_ids are the Gmail threads read; new_threads filters them out later.
    """
    end = sources.parse_ts(window_end) if window_end else sources.now()
    start = sources.parse_ts(window_start) if window_start else end
    sources.record(source, query, start, end, found, added, thread_ids)
    return f"Logged {source} run covering up to {sources.ts(end)}"


@mcp.tool()
def new_threads(thread_ids: list[str]) -> list[str]:
    """Return only the Gmail thread ids that have not been processed in an earlier run."""
    seen = set(cfg.load_log()["gmail_threads"])
    return [t for t in thread_ids if t not in seen]


@mcp.tool()
def flush_pending() -> str:
    """Move search results that were shown but never recorded into the Reviewed sheet as 'Unscored' (also automatic before each search)."""
    return f"Moved {store.flush_pending()} unrecorded result(s) to the Reviewed sheet."


# ---------------------------------------------------------------- searches

@mcp.tool()
def search_opportunitiespedia(keyword: str, limit: int = 100, since: str = "", force: bool = False) -> dict:
    """Search opportunitiespedia.com (public WordPress API) for posts newer than the last run for this keyword.

    since: ISO date/time override; force: ignore history and use the default look-back.
    """
    return sources.search_opportunitiespedia(keyword, limit, since, force)


@mcp.tool()
def search_scholarship_sites(keyword: str, sites: list[str] | None = None, limit: int = 100,
                             since: str = "", force: bool = False) -> dict:
    """Search Scholars4dev and Opportunity Desk (public search feeds) for posts newer than each site's last run.

    Use short keywords (e.g. 'PhD', 'renewable energy'). sites defaults to the enabled ones in settings.
    """
    return sources.search_scholarship_sites(keyword, sites, limit, since, force)


@mcp.tool()
def search_grants_gov(keyword: str, limit: int = 100, include_forecasted: bool = False,
                      since: str = "", force: bool = False) -> dict:
    """Search Grants.gov (US federal funding; mostly institution-level, check eligibility) for postings opened since the last run."""
    return sources.search_grants_gov(keyword, limit, include_forecasted, since, force)


# ---------------------------------------------------------------- opportunities

@mcp.tool()
def add_opportunities(items: list[dict]) -> dict:
    """Record opportunities you reviewed. Nothing is ever deleted.

    fit High/Medium (or none) go to the Opportunities shortlist; fit Low goes to 'Reviewed (not shortlisted)'
    with its reason. Duplicates (same Link, or same Title+Organization, on any sheet) and titles containing an
    exclude term (trainee, internship, job...) are skipped. Item keys: title (required), category (RA/TA,
    Fee waiver, Fellowship, Scholarship, Other), organization, deadline (YYYY-MM-DD preferred), details, source,
    link, notes, fit, fit_reason, eligibility (can a Nigerian citizen apply). Record EVERY result you reviewed.
    """
    book = store.load()
    everything = store.all_opportunities(book)
    links = {store.norm_link(r["Link"]) for r in everything if r["Link"]}
    names = {(r["Title"].lower(), r["Organization"].lower()) for r in everything}
    pending = cfg.load_pending()
    shortlisted, reviewed, skipped = [], [], []
    for it in items:
        title = str(it.get("title", "")).strip()
        link = str(it.get("link", "") or "").strip()
        org = str(it.get("organization", "") or "").strip()
        if title:
            pending.pop(store.pkey(link, title), None)
        if not title:
            skipped.append({"item": it, "reason": "missing title"})
        elif sources.excluded(title):
            skipped.append({"title": title, "reason": f"excluded term: {sources.excluded(title)}"})
        elif (link and store.norm_link(link) in links) or (title.lower(), org.lower()) in names:
            skipped.append({"title": title, "reason": "duplicate"})
        else:
            fit = it.get("fit") if it.get("fit") in store.FITS else ""
            row = store.blank({
                "Fit": fit, "Title": title, "Organization": org,
                "Category": it.get("category") if it.get("category") in store.CATEGORIES else "Other",
                "Deadline": store.iso(it.get("deadline", "")), "Details": it.get("details", ""),
                "Eligibility": it.get("eligibility", ""), "Fit reason": it.get("fit_reason", ""), "Link": link,
                "Status": "Skip" if fit == "Low" else "New", "Notes": it.get("notes", ""),
                "Source": it.get("source", ""), "Added": date.today().isoformat(),
            })
            (book["reviewed"] if fit == "Low" else book["active"]).append(row)
            (reviewed if fit == "Low" else shortlisted).append(title)
            links.add(store.norm_link(link))
            names.add((title.lower(), org.lower()))
    store.save(book)
    cfg.save_pending(pending)
    return {"shortlisted": len(shortlisted), "reviewed_not_shortlisted": len(reviewed), "skipped": skipped,
            "tracker": str(cfg.tracker_path())}


@mcp.tool()
def list_opportunities(status: str = "", category: str = "", fit: str = "", sheet: str = "active") -> list[dict]:
    """List opportunities (best fit, nearest deadline first). sheet: 'active' (shortlist), 'reviewed', 'parked' or 'all'."""
    book = store.load()
    pools = {"active": ["active"], "reviewed": ["reviewed"], "parked": ["parked"],
             "all": ["active", "reviewed", "parked"]}.get(sheet, ["active"])
    out = [{**r, "Sheet": name} for name in pools for r in book[name]
           if (not status or r["Status"] == status) and (not category or r["Category"] == category)
           and (not fit or r["Fit"] == fit)]
    return sorted(out, key=store.opp_sort_key)


@mcp.tool()
def update_status(title: str, status: str, notes: str = "") -> str:
    """Set Status (New, Interested, Applying, Applied, Rejected, Skip) and optionally Notes on the shortlist or reviewed row matching `title`."""
    if status not in store.STATUSES:
        return f"Status must be one of {store.STATUSES}"
    book = store.load()
    row, error = store.find(book["active"] + book["reviewed"], title)
    if not row:
        return error
    row["Status"] = status
    if notes:
        row["Notes"] = notes
    store.save(book)
    return f"Updated '{row['Title']}' -> {status}"


@mcp.tool()
def update_fit(title: str, fit: str, fit_reason: str, eligibility: str = "") -> str:
    """Set Fit (High, Medium, Low), reason and eligibility. Low moves a shortlist row to Reviewed; High/Medium moves a Reviewed row to the shortlist."""
    if fit not in store.FITS:
        return f"Fit must be one of {store.FITS}"
    book = store.load()
    row, error = store.find(book["active"] + book["reviewed"], title)
    if not row:
        return error
    row["Fit"], row["Fit reason"] = fit, fit_reason
    if eligibility:
        row["Eligibility"] = eligibility
    on_active = store.within(row, book["active"])
    if fit == "Low" and on_active:
        book["active"].remove(row)
        book["reviewed"].append(row)
        row["Status"] = "Skip" if row["Status"] == "New" else row["Status"]
    elif fit != "Low" and not on_active:
        book["reviewed"].remove(row)
        book["active"].append(row)
        row["Status"] = "New" if row["Status"] == "Skip" else row["Status"]
    store.save(book)
    return f"Updated '{row['Title']}' -> {fit} (now on {'Reviewed' if fit == 'Low' else 'Opportunities'})"


@mcp.tool()
def promote_opportunity(title: str, fit: str = "Medium") -> str:
    """Move a row from the Reviewed sheet back to the Opportunities shortlist."""
    if fit not in ("High", "Medium"):
        return "fit must be High or Medium"
    book = store.load()
    row, error = store.find(book["reviewed"], title)
    if not row:
        return error
    book["reviewed"].remove(row)
    row["Fit"] = fit
    row["Status"] = "New" if row["Status"] == "Skip" else row["Status"]
    book["active"].append(row)
    store.save(book)
    return f"Promoted '{row['Title']}' to the shortlist as {fit}"


@mcp.tool()
def park_opportunities(titles: list[str]) -> dict:
    """Move rows whose Title matches any of `titles` to the 'Parked (jobs & internships)' sheet."""
    book = store.load()
    moved, problems = [], []
    for t in titles:
        row, error = store.find(book["active"] + book["reviewed"], t)
        if row:
            (book["active"] if store.within(row, book["active"]) else book["reviewed"]).remove(row)
            book["parked"].append(row)
            moved.append(row["Title"])
        else:
            problems.append(error)
    store.save(book)
    return {"moved": moved, "problems": problems}


# ---------------------------------------------------------------- applications

def _level_from(title: str) -> str:
    t = title.lower()
    if "phd" in t or "doctoral" in t or "doctorate" in t:
        return "PhD"
    if "master" in t or "msc" in t:
        return "Master's"
    return ""


def _check_fields(fields: dict) -> list[str]:
    problems = []
    for key, value in fields.items():
        if key not in store.APP_COLUMNS or key == "Days left":
            problems.append(f"unknown field '{key}'")
        elif key in store.APP_CHOICES and value not in store.APP_CHOICES[key] and value != "":
            problems.append(f"'{key}' must be one of {store.APP_CHOICES[key]}")
    return problems


def _set_fields(app: dict, fields: dict) -> None:
    for key, value in fields.items():
        parsed = store.parse_date(value) if key in store.APP_DATES else None
        app[key] = parsed.isoformat() if parsed else str(value)


@mcp.tool()
def start_application(title: str, app_type: str = "", level: str = "", contact: str = "", opens: str = "",
                      next_action: str = "", next_action_date: str = "", fee_status: str = "", fee_amount: str = "",
                      waiver_route: str = "", requirements: dict | None = None, notes: str = "",
                      provider: str = "", link: str = "", deadline: str = "") -> dict:
    """Start tracking an application on the Applications sheet.

    `title` matches an opportunity in the database (its title, organization, link and deadline are copied, and
    its Status becomes Applying). For an application not in the database (e.g. a university portal), also pass
    provider and/or link and deadline. app_type: PhD admission + funding, Scholarship, Fellowship, RA/TA, Fee waiver
    (default from the opportunity's category). The requirement checklist is pre-filled from the settings defaults
    for that type; check the official page and correct it via `requirements` ({requirement: Required/In progress/
    Done/N/A}) or update_application.
    """
    book = store.load()
    opp, error = store.find(book["active"] + book["reviewed"], title)
    if not opp and not (provider or link):
        return {"error": error + ". For an application not in the database, also pass provider and/or link."}
    name = opp["Title"] if opp else title
    if any(a["Opportunity"].lower() == name.lower() for a in book["applications"]):
        return {"error": f"An application for '{name}' already exists; use update_application."}
    settings = cfg.load_settings()
    app_type = app_type or TYPE_FROM_CATEGORY.get(opp["Category"] if opp else "", "PhD admission + funding")
    reqs = {r: ("Required" if r in settings["requirement_defaults"].get(app_type, []) else "") for r in cfg.REQUIREMENTS}
    reqs.update(requirements or {})
    fields = {
        "Opportunity": name, "Type": app_type, "Provider": provider or (opp["Organization"] if opp else ""),
        "Level": level or _level_from(name), "Link": link or (opp["Link"] if opp else ""), "Contact": contact,
        "Opens": opens, "Deadline": deadline or (opp["Deadline"] if opp else ""), "Stage": "Planning",
        "Next action": next_action, "Next action date": next_action_date,
        "Fee status": fee_status or ("Not required" if app_type == "Fee waiver" else settings["default_fee_status"]),
        "Fee amount": fee_amount, "Waiver route": waiver_route, "Notes": notes, **reqs,
    }
    problems = _check_fields({k: v for k, v in fields.items() if v})
    if problems:
        return {"error": problems}
    app = store.blank({}, store.APP_COLUMNS)
    _set_fields(app, fields)
    book["applications"].append(app)
    if opp:
        opp["Status"] = "Applying"
        if store.within(opp, book["reviewed"]):
            book["reviewed"].remove(opp)
            book["active"].append(opp)
    store.save(book)
    return {"created": name, "type": app_type, "requirements": {k: v for k, v in reqs.items() if v},
            "tip": "Confirm the checklist against the official page and fix it with update_application."}


@mcp.tool()
def update_application(title: str, fields: dict) -> dict:
    """Update an application. `fields` uses Applications column names, e.g. {"Stage": "Submitted",
    "Next action": "Email Prof. X", "Next action date": "2026-11-20", "Fee status": "Waived", "CV": "Done",
    "Recommenders": "Prof. Ighodaro; Dr. Owunna"}. Dropdown columns only accept their listed values.
    Moving the Stage also updates the opportunity's Status; Submitted fills 'Submitted on' if empty.
    """
    book = store.load()
    app, error = store.find(book["applications"], title, key="Opportunity")
    if not app:
        return {"error": error}
    problems = _check_fields(fields)
    if problems:
        return {"error": problems, "valid_fields": [c for c in store.APP_COLUMNS if c != "Days left"]}
    _set_fields(app, fields)
    if fields.get("Stage") == "Submitted" and not app["Submitted on"]:
        app["Submitted on"] = date.today().isoformat()
    if fields.get("Stage") in STATUS_FROM_STAGE:
        opp, _ = store.find(book["active"] + book["reviewed"], app["Opportunity"])
        if opp:
            opp["Status"] = STATUS_FROM_STAGE[fields["Stage"]]
    store.save(book)
    return {"updated": app["Opportunity"], "fields": list(fields)}


@mcp.tool()
def list_applications(stage: str = "", due_within_days: int = 0) -> list[dict]:
    """List applications (by stage, then deadline). due_within_days keeps those whose deadline or next action date falls within that many days (overdue included)."""
    book = store.load()
    limit = date.today() + timedelta(days=due_within_days)
    out = []
    for a in book["applications"]:
        if stage and a["Stage"] != stage:
            continue
        if due_within_days:
            dates = [store.parse_date(a["Deadline"]), store.parse_date(a["Next action date"])]
            if not any(d and d <= limit for d in dates):
                continue
        out.append(a)
    return sorted(out, key=store.app_sort_key)


@mcp.tool()
def get_digest(days: int = 0) -> dict:
    """Summary for a report: deadlines within `days` (default alert_days), next actions due, applications by stage, shortlist counts, items added in the last 7 days."""
    return store.digest(store.load(), cfg.load_settings(), days)


if __name__ == "__main__":
    mcp.run()
