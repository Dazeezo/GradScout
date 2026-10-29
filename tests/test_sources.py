from datetime import timedelta

from conftest import FakeResponse

RSS = """<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>{}</channel></rss>"""
ITEM = """<item><title>{t}</title><link>{l}</link><pubDate>{d}</pubDate><description>x</description>
<content:encoded><![CDATA[Application deadline: 15 January 2027]]></content:encoded></item>"""


def test_text_helpers(gs):
    s = gs.sources
    assert s.extract_deadline("The application deadline is 20 November 2026.") == "2026-11-20"
    assert s.extract_deadline("no date here") == "See link"
    assert s.guess_category("Graduate Research Assistantship") == "RA/TA"
    assert s.guess_category("Tuition waiver for X") == "Fee waiver"
    assert s.excluded("Graduate Trainee Programme 2027") == "graduate trainee"
    assert s.excluded("PhD Fellowship") is None


def test_window_memory(gs):
    s = gs.sources
    start, end = s.window("x", "kw")
    assert (end - start).days == gs.cfg.load_settings()["default_window_days"]
    s.record("x", "kw", start, end, 3)
    start2, _ = s.window("x", "kw")
    assert start2 == s.parse_ts(s.ts(end)) - timedelta(hours=24)
    forced, _ = s.window("x", "kw", force=True)
    assert forced < start2
    since, _ = s.window("x", "kw", since="2026-09-01")
    assert since.date().isoformat() == "2026-09-01"


def _post(title, link, day):
    return {"title": {"rendered": title}, "link": link, "date": f"2026-10-{day:02d}T10:00:00",
            "excerpt": {"rendered": "<p>Fully funded.</p>"},
            "content": {"rendered": "<p>Deadline: 1 March 2027</p>"}}


def test_pedia_search_filters_stashes_and_logs(gs, fake_http):
    st = gs.store
    st.save({"active": [st.blank({"Title": "Known", "Link": "https://p.com/known"})], "reviewed": [], "parked": [],
             "applications": []})
    fake_http.get.append(FakeResponse([_post("New PhD Scholarship", "https://p.com/new", 20),
                                       _post("Known", "https://p.com/known", 19),
                                       _post("Graduate Trainee Scheme", "https://p.com/t", 18)]))
    out = gs.sources.search_opportunitiespedia("PhD", 100, "", False)
    assert [r["title"] for r in out["results"]] == ["New PhD Scholarship"]
    assert out["results"][0]["deadline"] == "2027-03-01"
    assert out["excluded"] == 1 and out["already_tracked"] == 1 and not out["truncated"]
    assert list(gs.cfg.load_pending()) == ["https://p.com/new"]
    assert gs.sources.last_run("opportunitiespedia", "PhD")["found"] == 1


def test_truncated_search_logs_only_what_was_read(gs, fake_http):
    fake_http.get.append(FakeResponse([_post("A Scholarship", "https://p.com/a", 25),
                                       _post("B Scholarship", "https://p.com/b", 20)]))
    out = gs.sources.search_opportunitiespedia("x", 2, "", False)
    assert out["truncated"] and "Limit reached" in out["note"]
    assert gs.sources.last_run("opportunitiespedia", "x")["window_start"].startswith("2026-10-20")


def test_feed_search_pages_until_older_than_window(gs, fake_http):
    page = RSS.format(ITEM.format(t="Fresh Fellowship", l="https://s.com/1", d="Wed, 28 Oct 2026 10:00:00 +0000")
                      + ITEM.format(t="Ancient Scholarship", l="https://s.com/2", d="Mon, 01 Jan 2024 10:00:00 +0000"))
    fake_http.get.append(FakeResponse(content=page.encode()))
    out = gs.sources.search_scholarship_sites("PhD", ["scholars4dev"], 100, "2026-10-01", False)
    assert [r["title"] for r in out["results"]] == ["Fresh Fellowship"]
    assert out["results"][0]["deadline"] == "2027-01-15"
    assert len(fake_http.calls) == 1  # stopped at the first post older than the window
    assert out["errors"] == {} and out["truncated"] == []


def test_grants_gov_uses_open_date(gs, fake_http):
    hits = [{"id": 1, "title": "New &amp; Open", "agency": "NSF", "openDate": "10/25/2026", "closeDate": "01/15/2027"},
            {"id": 2, "title": "Old", "agency": "NSF", "openDate": "01/01/2020", "closeDate": ""}]
    fake_http.post.append(FakeResponse({"data": {"oppHits": hits}}))
    out = gs.sources.search_grants_gov("fellowship", 100, False, "2026-10-01", False)
    assert [r["title"] for r in out["results"]] == ["New & Open"]
    assert out["results"][0]["deadline"] == "2027-01-15"
    assert fake_http.calls[0][2]["sortBy"] == "openDate|desc"


def test_until_caps_window_and_skips_search_log(gs, fake_http):
    s = gs.sources
    start, end = s.window("x", "kw", since="2026-09-01", until="2026-09-30")
    assert start.date().isoformat() == "2026-09-01"
    assert end.isoformat().startswith("2026-09-30T23:59:59")  # a bare date covers the whole day

    st = gs.store
    st.save({"active": [st.blank({"Title": "Known", "Link": "https://p.com/known"})], "reviewed": [], "parked": [],
             "applications": []})
    fake_http.get.append(FakeResponse([_post("In Range Scholarship", "https://p.com/in", 10),
                                       _post("Known", "https://p.com/known", 9)]))
    out = s.search_opportunitiespedia("PhD", 100, "2026-10-01", False, "2026-10-15")
    assert fake_http.calls[0][2]["before"].startswith("2026-10-15T23:59:59")
    assert [r["title"] for r in out["results"]] == ["In Range Scholarship"]
    assert out["already_tracked"] == 1 and "not written to the search log" in out["note"]
    assert s.last_run("opportunitiespedia", "PhD") is None  # the "last run" marker is untouched


def test_feed_search_skips_posts_newer_than_until(gs, fake_http):
    page = RSS.format(ITEM.format(t="Too New Fellowship", l="https://s.com/new", d="Wed, 28 Oct 2026 10:00:00 +0000")
                      + ITEM.format(t="In Range Fellowship", l="https://s.com/mid", d="Mon, 12 Oct 2026 10:00:00 +0000")
                      + ITEM.format(t="Too Old Scholarship", l="https://s.com/old", d="Mon, 01 Jan 2024 10:00:00 +0000"))
    fake_http.get.append(FakeResponse(content=page.encode()))
    out = gs.sources.search_scholarship_sites("PhD", ["scholars4dev"], 100, "2026-10-01", False, "2026-10-15")
    assert [r["title"] for r in out["results"]] == ["In Range Fellowship"]
    assert gs.sources.last_run("scholars4dev", "PhD") is None
