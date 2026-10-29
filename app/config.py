"""Paths, settings, search log and pending-results storage shared by the server, the GUI and the tests."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("GRADSCOUT_DATA", ROOT / "data"))
PROFILE = ROOT / "profile" / "profile.md"
README = ROOT / "README.md"

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
APP_TYPES = ["PhD admission + funding", "Scholarship", "Fellowship", "RA/TA", "Fee waiver"]
REQUIREMENTS = ["Admission first", "Supervisor acceptance", "Research proposal", "SOP / Personal statement", "CV",
                "Recommendation letters", "Transcripts", "English test", "GRE", "Essays", "Nomination"]
FEE_STATUSES = ["Not required", "Required", "Waiver requested", "Waived", "Paid"]
SITES = ["opportunitiespedia", "scholars4dev", "opportunitydesk", "grants.gov"]

DEFAULTS = {
    "keywords": ["PhD", "mechanical engineering", "renewable energy", "composite materials", "fully funded masters",
                 "fellowship", "application fee waiver"],
    "exclude_terms": ["graduate trainee", "trainee", "internship", "internships", "job", "jobs", "vacancy", "vacancies",
                      "recruitment"],
    "sites": list(SITES),
    "gmail_senders": ["linkedin.com", "findaphd.com"],
    "default_window_days": 120,
    "overlap_hours": 24,
    "auto_refresh": True,
    "refresh_days": ["Mon", "Thu"],
    "refresh_time": "08:00",
    "alert_days": 14,
    "next_action_alert_days": 7,
    "requirement_defaults": {
        "PhD admission + funding": ["SOP / Personal statement", "CV", "Recommendation letters", "Transcripts", "English test"],
        "Scholarship": ["Admission first", "SOP / Personal statement", "CV", "Recommendation letters", "Transcripts",
                        "English test", "Essays"],
        "Fellowship": ["Research proposal", "SOP / Personal statement", "CV", "Recommendation letters", "Transcripts"],
        "RA/TA": ["Supervisor acceptance", "CV", "Transcripts"],
        "Fee waiver": [],
    },
    "default_fee_status": "Required",
}


def tracker_path() -> Path:
    return DATA / "GradScout.xlsx"


def backups_dir() -> Path:
    return DATA / "backups"


def _file(name: str) -> Path:
    return DATA / name


def _read(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return json.loads(json.dumps(default))


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def validate_settings(changes: dict) -> list[str]:
    """Return a list of problems with `changes` (empty when valid)."""
    problems = []
    for key, value in changes.items():
        if key not in DEFAULTS:
            problems.append(f"unknown setting '{key}'")
        elif type(value) is not type(DEFAULTS[key]):
            problems.append(f"'{key}' must be {type(DEFAULTS[key]).__name__}")
        elif key == "refresh_days" and not set(value) <= set(DAYS):
            problems.append(f"refresh_days must be from {DAYS}")
        elif key == "sites" and not set(value) <= set(SITES):
            problems.append(f"sites must be from {SITES}")
        elif key == "default_fee_status" and value not in FEE_STATUSES:
            problems.append(f"default_fee_status must be one of {FEE_STATUSES}")
        elif key == "requirement_defaults" and (not set(value) <= set(APP_TYPES)
                                                or any(not set(v) <= set(REQUIREMENTS) for v in value.values())):
            problems.append(f"requirement_defaults keys must be from {APP_TYPES} and values from {REQUIREMENTS}")
        elif key in ("default_window_days", "alert_days", "next_action_alert_days") and value < 1:
            problems.append(f"'{key}' must be at least 1")
    return problems


def load_settings() -> dict:
    settings = json.loads(json.dumps(DEFAULTS))
    stored = _read(_file("settings.json"), {})
    settings.update({k: v for k, v in stored.items() if k in DEFAULTS and not validate_settings({k: v})})
    return settings


def save_settings(settings: dict) -> None:
    _write(_file("settings.json"), settings)


def load_log() -> dict:
    log = _read(_file("search_log.json"), {"runs": [], "gmail_threads": []})
    log.setdefault("runs", [])
    log.setdefault("gmail_threads", [])
    return log


def save_log(log: dict) -> None:
    _write(_file("search_log.json"), log)


def load_pending() -> dict:
    """Search results shown to Claude but not yet recorded in the workbook, keyed by link or title."""
    return _read(_file("pending_review.json"), {})


def save_pending(pending: dict) -> None:
    _write(_file("pending_review.json"), pending)
