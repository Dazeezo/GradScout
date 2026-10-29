from datetime import date, timedelta


def seed(gs):
    gs.server.add_opportunities([
        {"title": "Alpha PhD Scholarship", "organization": "Uni A", "category": "Scholarship", "fit": "High",
         "link": "https://a.org", "deadline": "2027-01-15"},
        {"title": "Beta Fellowship", "organization": "Funder B", "category": "Fellowship", "fit": "Low",
         "fit_reason": "US citizens only", "link": "https://b.org"},
    ])


def test_add_routes_and_dedupes(gs):
    seed(gs)
    out = gs.server.add_opportunities([
        {"title": "Dup by link", "link": "https://b.org/"},
        {"title": "Engineering Graduate Trainee Programme"},
        {"title": "Gamma Masters", "fit": "Medium"},
    ])
    assert out["shortlisted"] == 1
    assert [s["reason"] for s in out["skipped"]] == ["duplicate", "excluded term: graduate trainee"]
    book = gs.store.load()
    assert {r["Title"] for r in book["active"]} == {"Alpha PhD Scholarship", "Gamma Masters"}
    assert book["reviewed"][0]["Status"] == "Skip"


def test_fit_moves_promote_and_park(gs):
    seed(gs)
    assert "now on Reviewed" in gs.server.update_fit("Alpha", "Low", "changed")
    assert "Promoted" in gs.server.promote_opportunity("Alpha", "High")
    assert "now on Opportunities" in gs.server.update_fit("Beta", "Medium", "eligible after all")
    assert gs.server.park_opportunities(["Funder B"])["moved"] == ["Beta Fellowship"]
    book = gs.store.load()
    assert [r["Title"] for r in book["parked"]] == ["Beta Fellowship"]
    gs.server.add_opportunities([{"title": "Alpha Masters", "fit": "Medium"}])
    assert "matches 2 rows" in gs.server.update_status("Alpha", "Interested")  # ambiguous lookups are refused


def test_application_lifecycle(gs):
    seed(gs)
    out = gs.server.start_application("Uni A", next_action="Email supervisor",
                                      next_action_date=(date.today() + timedelta(days=3)).isoformat())
    assert out["type"] == "Scholarship"
    assert out["requirements"]["Admission first"] == "Required"
    assert "already exists" in gs.server.start_application("Alpha PhD Scholarship")["error"]
    assert "error" in gs.server.start_application("Not in database")
    assert gs.server.start_application("Portal X", provider="Uni X", deadline="15 January 2027")["created"] == "Portal X"

    assert "error" in gs.server.update_application("Alpha", {"Stage": "Bogus"})
    gs.server.update_application("Alpha", {"Stage": "Submitted", "Fee status": "Waived", "CV": "Done"})
    app = [a for a in gs.store.load()["applications"] if a["Opportunity"].startswith("Alpha")][0]
    assert app["Submitted on"] == date.today().isoformat() and app["Fee status"] == "Waived"
    assert [r["Status"] for r in gs.store.load()["active"] if r["Title"].startswith("Alpha")] == ["Applied"]
    assert [a["Opportunity"] for a in gs.server.list_applications(due_within_days=7)] == ["Alpha PhD Scholarship"]
    assert gs.server.get_digest()["next_actions_due"][0]["next_action"] == "Email supervisor"


def test_settings_and_refresh_plan(gs):
    assert "error" in gs.server.update_settings({"refresh_days": ["Funday"]})
    assert "error" in gs.server.update_settings({"alert_days": "7"})
    gs.server.update_settings({"refresh_days": list(gs.cfg.DAYS), "alert_days": 21})
    assert gs.server.get_settings()["alert_days"] == 21
    assert gs.server.refresh_plan()["refresh_due_today"] is True
    gs.server.update_settings({"auto_refresh": False})
    assert gs.server.refresh_plan()["refresh_due_today"] is False


def test_gmail_memory(gs):
    assert gs.server.get_last_run("gmail")["gmail_after_epoch"] is None
    gs.server.log_run("gmail", found=2, thread_ids=["t1", "t2"])
    assert gs.server.new_threads(["t1", "t3"]) == ["t3"]
    assert isinstance(gs.server.get_last_run("gmail")["gmail_after_epoch"], int)
