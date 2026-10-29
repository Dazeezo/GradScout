"""Server-side searches with search memory.

Each search covers a time window per (source, keyword): from the last covered time minus an overlap,
or the default look-back on a first run. Covered windows go to search_log.json; results already in
the workbook are not returned again, and returned results are stashed until they are recorded.
"""
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

import config as cfg
import store

GRANTS_URL = "https://api.grants.gov/v1/api/search2"
PEDIA_URL = "https://opportunitiespedia.com/wp-json/wp/v2/posts"
FEED_SITES = {
    "scholars4dev": "https://www.scholars4dev.com",
    "opportunitydesk": "https://opportunitydesk.org",
}
UA = {"User-Agent": "GradScout/1.0 (personal research tracker)"}
MAX_FEED_PAGES = 6


# ---------------------------------------------------------------- text helpers

def plain(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup or ""))).strip()


def extract_deadline(text: str) -> str:
    date_re = r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Z][a-z]+,?\s+\d{4}|[A-Z][a-z]+\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})"
    for m in re.finditer(r"deadline", text, re.I):
        d = re.search(date_re, text[m.end():m.end() + 200])
        if d and store.parse_date(d.group(1)):
            return store.parse_date(d.group(1)).isoformat()
    return "See link"


def guess_category(title: str) -> str:
    t = title.lower()
    for words, cat in [(("assistantship", "research assistant", "teaching assistant"), "RA/TA"),
                       (("fee waiver", "tuition waiver"), "Fee waiver"),
                       (("fellowship",), "Fellowship"), (("scholarship",), "Scholarship")]:
        if any(w in t for w in words):
            return cat
    return "Other"


def excluded(title: str) -> str | None:
    for term in cfg.load_settings()["exclude_terms"]:
        if re.search(r"\b" + re.escape(term) + r"\b", title, re.I):
            return term
    return None


def make_item(title: str, body: str, excerpt: str, link: str, published: str, source: str) -> dict:
    funding = re.search(r"\(([^)]*(?:funded|paid|stipend)[^)]*)\)", title, re.I)
    return {
        "category": guess_category(title),
        "title": title,
        "deadline": extract_deadline(body),
        "details": ((funding.group(1) + ". ") if funding else "") + excerpt[:300],
        "source": source,
        "link": link,
        "published": published,
    }


# ---------------------------------------------------------------- search memory

def now() -> datetime:
    return datetime.now(timezone.utc)


def ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_ts(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def last_run(source: str, query: str = "") -> dict | None:
    runs = [r for r in cfg.load_log()["runs"] if r["source"] == source and (not query or r["query"] == query)]
    return runs[-1] if runs else None


def window(source: str, query: str, since: str = "", force: bool = False) -> tuple[datetime, datetime]:
    settings, end = cfg.load_settings(), now()
    if since:
        return parse_ts(since), end
    last = None if force else last_run(source, query)
    if last:
        return parse_ts(last["window_end"]) - timedelta(hours=settings["overlap_hours"]), end
    return end - timedelta(days=settings["default_window_days"]), end


def record(source: str, query: str, start: datetime, end: datetime, found: int,
           added: int | None = None, thread_ids: list[str] | None = None) -> None:
    log = cfg.load_log()
    log["runs"].append({"source": source, "query": query, "run_at": ts(now()), "window_start": ts(start),
                        "window_end": ts(end), "found": found, "added": added})
    log["runs"] = log["runs"][-500:]
    log["gmail_threads"] = list(dict.fromkeys(log["gmail_threads"] + (thread_ids or [])))[-5000:]
    cfg.save_log(log)
    store.refresh()  # keep the Search log sheet current; the JSON file is the source of truth


def auto_flush() -> None:
    try:
        store.flush_pending()
    except RuntimeError:  # workbook open in Excel; items stay pending and are flushed next time
        pass


def finish(source: str, query: str, start: datetime, end: datetime, results: list[dict], truncated: bool) -> dict:
    tracked = {store.norm_link(r["Link"]) for r in store.all_opportunities(store.load()) if r["Link"]}
    allowed = [r for r in results if not excluded(r["title"])]
    kept = [r for r in allowed if store.norm_link(r["link"]) not in tracked]
    store.stash(kept)
    oldest = min((r["published"] for r in results if r.get("published")), default="")
    note = ""
    if not truncated:
        record(source, query, start, end, len(kept))
    elif oldest:  # results are newest first, so only the span back to the oldest item was read
        record(source, query, parse_ts(oldest), end, len(kept))
        note = (f"Limit reached: only the newest items (back to {oldest}) were read and logged as covered, so the next "
                f"run looks only at newer posts. Narrow the keyword or raise limit to cover older ones.")
    else:
        note = "Limit reached and nothing was logged. Narrow the keyword or raise limit."
    return {"results": kept, "excluded": len(results) - len(allowed), "already_tracked": len(allowed) - len(kept),
            "window": {"start": ts(start), "end": ts(end)}, "truncated": truncated, "note": note,
            "reminder": "Record every result you review with add_opportunities (Low fit goes to the Reviewed sheet); "
                        "unrecorded ones are moved there as Unscored before the next search."}


# ---------------------------------------------------------------- sources

def search_grants_gov(keyword: str, limit: int, include_forecasted: bool, since: str, force: bool) -> dict:
    auto_flush()
    start, end = window("grants.gov", keyword, since, force)
    statuses = "forecasted|posted" if include_forecasted else "posted"
    try:
        resp = httpx.post(GRANTS_URL, json={"keyword": keyword, "oppStatuses": statuses, "rows": limit,
                                            "sortBy": "openDate|desc"}, timeout=30)
        resp.raise_for_status()
        hits = resp.json().get("data", {}).get("oppHits", [])
    except (httpx.HTTPError, ValueError) as e:
        return {"error": f"Grants.gov search failed: {e}"}
    last_open = store.parse_date(hits[-1].get("openDate")) if hits else None
    truncated = len(hits) >= limit and (last_open is None or last_open >= start.date())  # newest first
    results = []
    for h in hits:
        opened = store.parse_date(h.get("openDate"))
        if opened and opened < start.date():
            continue
        closes = store.parse_date(h.get("closeDate"))
        results.append({"title": plain(h.get("title", "")), "organization": h.get("agency"),
                        "deadline": closes.isoformat() if closes else "See link", "number": h.get("number"),
                        "source": "Grants.gov", "published": opened.isoformat() if opened else "",
                        "link": f"https://www.grants.gov/search-results-detail/{h.get('id')}"})
    return finish("grants.gov", keyword, start, end, results, truncated)


def search_opportunitiespedia(keyword: str, limit: int, since: str, force: bool) -> dict:
    auto_flush()
    start, end = window("opportunitiespedia", keyword, since, force)
    per_page = min(limit, 100)
    try:
        resp = httpx.get(PEDIA_URL, params={"search": keyword, "per_page": per_page,
                                            "after": start.strftime("%Y-%m-%dT%H:%M:%S"),
                                            "_fields": "link,title,date,excerpt,content"}, headers=UA, timeout=30)
        resp.raise_for_status()
        posts = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"error": f"Opportunities Pedia search failed: {e}"}
    results = [make_item(plain(p["title"]["rendered"]), plain(p["content"]["rendered"]), plain(p["excerpt"]["rendered"]),
                         p["link"], p["date"][:10], "Opportunities Pedia") for p in posts]
    return finish("opportunitiespedia", keyword, start, end, results, len(posts) >= per_page)


def _search_feed(base_url: str, keyword: str, limit: int, start: datetime, source: str) -> tuple[list[dict], bool]:
    """Page through a WordPress search feed (newest first) until posts are older than `start`."""
    ns = {"c": "http://purl.org/rss/1.0/modules/content/"}
    out: list[dict] = []
    for page in range(1, MAX_FEED_PAGES + 1):
        resp = httpx.get(base_url, params={"s": keyword, "feed": "rss2", "orderby": "date", "order": "desc",
                                           "paged": page}, headers=UA, timeout=30, follow_redirects=True)
        if resp.status_code == 404 and page > 1:
            return out, False
        resp.raise_for_status()
        items = list(ET.fromstring(resp.content).iter("item"))
        if not items:
            return out, False
        for it in items:
            published = parsedate_to_datetime(it.findtext("pubDate"))
            if published < start:
                return out, False
            body = plain(it.findtext("c:encoded", default="", namespaces=ns) or it.findtext("description", default=""))
            out.append(make_item(plain(it.findtext("title", default="")), body,
                                 plain(it.findtext("description", default="")), it.findtext("link", default=""),
                                 published.date().isoformat(), source))
            if len(out) >= limit:
                return out, True
    return out, True


def search_scholarship_sites(keyword: str, sites: list[str] | None, limit: int, since: str, force: bool) -> dict:
    auto_flush()
    chosen = sites or [s for s in cfg.load_settings()["sites"] if s in FEED_SITES]
    results, errors, truncated, windows = [], {}, [], {}
    for name in chosen:
        if name not in FEED_SITES:
            errors[name] = f"unknown site, choose from {list(FEED_SITES)}"
            continue
        start, end = window(name, keyword, since, force)
        try:
            found, cut = _search_feed(FEED_SITES[name], keyword, limit, start, name)
        except (httpx.HTTPError, ET.ParseError, TypeError, ValueError) as e:
            errors[name] = str(e)
            continue
        out = finish(name, keyword, start, end, found, cut)
        results += out["results"]
        windows[name] = out["window"]
        if cut:
            truncated.append(name)
    return {"results": results, "errors": errors, "truncated": truncated, "windows": windows,
            "reminder": "Record every result you review with add_opportunities."}
