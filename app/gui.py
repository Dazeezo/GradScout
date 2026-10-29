"""GradScout home window: dashboard plus all settings (stdlib Tkinter only)."""
import os
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
import store  # noqa: E402


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("GradScout")
        self.geometry("920x640")
        self.minsize(760, 540)
        self.settings = cfg.load_settings()
        self.links: dict[str, str] = {}

        # Button bar first, at the bottom, so it stays visible at any window size.
        bar = ttk.Frame(self, padding=(12, 6))
        bar.pack(side="bottom", fill="x")
        for text, command in (("Save settings", self.save), ("Open spreadsheet", self.open_sheet),
                              ("Open profile", lambda: self._open(cfg.PROFILE)),
                              ("Open README", lambda: self._open(cfg.README)), ("Reload", self.reload)):
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=4)
        self.status = ttk.Label(bar, text="", foreground="#555555")
        self.status.pack(side="right")

        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.home = ttk.Frame(tabs, padding=10)
        frames = {}
        tabs.add(self.home, text="Home")
        for name in ("Search", "Refresh & alerts", "Applications"):
            frames[name] = ttk.Frame(tabs, padding=10)
            tabs.add(frames[name], text=name)
        self._build_home()
        self._build_search(frames["Search"])
        self._build_refresh(frames["Refresh & alerts"])
        self._build_apps(frames["Applications"])
        self.reload()

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _lines(parent, label: str, values: list[str], height: int) -> tk.Text:
        box = ttk.LabelFrame(parent, text=label, padding=6)
        box.pack(fill="x", pady=4)
        text = tk.Text(box, height=height, width=40)
        text.insert("1.0", "\n".join(values))
        text.pack(fill="x")
        return text

    @staticmethod
    def _read(text: tk.Text) -> list[str]:
        return [line.strip() for line in text.get("1.0", "end").splitlines() if line.strip()]

    @staticmethod
    def _tree(parent, columns: list[tuple[str, str, int]], height: int) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=[c[0] for c in columns], show="headings", height=height)
        for key, text, width in columns:
            tree.heading(key, text=text)
            tree.column(key, width=width, stretch=key == columns[-1][0])
        tree.pack(fill="both", expand=True)
        return tree

    def _open(self, path: Path) -> None:
        if path.exists():
            os.startfile(path)
        else:
            messagebox.showinfo("Not found", f"{path.name} does not exist yet.")

    # ------------------------------------------------------------ Home
    def _build_home(self) -> None:
        self.summary = ttk.Label(self.home, text="", font=("Segoe UI", 10, "bold"))
        self.summary.pack(anchor="w")
        self.apps_line = ttk.Label(self.home, text="")
        self.apps_line.pack(anchor="w", pady=(2, 0))
        self.refresh_line = ttk.Label(self.home, text="", foreground="#555555")
        self.refresh_line.pack(anchor="w", pady=(2, 8))
        due = ttk.LabelFrame(self.home, text="Due soon (double-click to open the link)", padding=6)
        due.pack(fill="both", expand=True)
        self.due = self._tree(due, [("date", "Date", 95), ("days", "Days", 55), ("kind", "What", 170), ("title", "Title", 460)], 9)
        self.due.tag_configure("overdue", foreground="#9C0006")
        self.due.tag_configure("soon", foreground="#C65911")
        self.due.bind("<Double-1>", self._open_due)
        runs = ttk.LabelFrame(self.home, text="Last search per source", padding=6)
        runs.pack(fill="x", pady=(8, 0))
        self.runs = self._tree(runs, [("source", "Source", 160), ("run", "Ran at (UTC)", 190), ("covered", "Covered up to (UTC)", 190)], 4)

    def _open_due(self, _event) -> None:
        item = self.due.focus()
        if self.links.get(item):
            webbrowser.open(self.links[item])

    def reload(self) -> None:
        self.settings = cfg.load_settings()
        try:
            book = store.load()
        except Exception as e:  # unreadable workbook: show it instead of crashing
            self.summary.config(text=f"Could not read the spreadsheet: {e}")
            return
        d = store.digest(book, self.settings)
        fits = d["shortlist_by_fit"]
        self.summary.config(text=f"Shortlist: High {fits['High']}  ·  Medium {fits['Medium']}  ·  Unscored {fits['Unscored']}"
                                 f"      Reviewed {d['reviewed']}      Parked {d['parked']}")
        stages = ", ".join(f"{k} {v}" for k, v in d["applications_by_stage"].items()) or "none yet"
        self.apps_line.config(text=f"Applications: {stages}      Added in the last 7 days: {len(d['added_last_7_days'])}")
        s = self.settings
        auto = (f"On: {', '.join(s['refresh_days']) or 'no days selected'} at {s['refresh_time']}"
                if s["auto_refresh"] else "Off")
        self.refresh_line.config(text=f"Auto refresh: {auto}      Alerts: deadlines within {s['alert_days']} days, "
                                      f"next actions within {s['next_action_alert_days']} days")
        self.due.delete(*self.due.get_children())
        self.links.clear()
        rows = [(a["date"], a["days_left"], "Next action: " + a["next_action"], a["title"], "") for a in d["next_actions_due"]]
        rows += [(x["date"], x["days_left"], x["kind"], x["title"], x.get("link", "")) for x in d["deadlines_soon"]]
        for date_, days, kind, title, link in sorted(rows, key=lambda r: r[1]):
            tag = "overdue" if days < 0 else "soon" if days <= 7 else ""
            item = self.due.insert("", "end", values=(date_, days, kind, title), tags=(tag,))
            self.links[item] = link
        self.runs.delete(*self.runs.get_children())
        latest = {}
        for run in cfg.load_log()["runs"]:
            latest[run["source"]] = run
        for source, run in sorted(latest.items()):
            self.runs.insert("", "end", values=(source, run["run_at"], run["window_end"]))

    # ------------------------------------------------------------ Search
    def _build_search(self, frame) -> None:
        left, right = ttk.Frame(frame), ttk.Frame(frame)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))
        s = self.settings
        self.keywords = self._lines(left, "Search keywords (one per line; short phrases work best)", s["keywords"], 9)
        self.exclude = self._lines(left, "Excluded title terms (results with these words are dropped)", s["exclude_terms"], 7)
        self.senders = self._lines(right, "Gmail senders to read (one per line)", s["gmail_senders"], 3)
        sites = ttk.LabelFrame(right, text="Sources to search", padding=6)
        sites.pack(fill="x", pady=4)
        self.site_vars = {name: tk.BooleanVar(value=name in s["sites"]) for name in cfg.SITES}
        for name in cfg.SITES:
            ttk.Checkbutton(sites, text=name, variable=self.site_vars[name]).pack(anchor="w")
        window = ttk.LabelFrame(right, text="Time window", padding=6)
        window.pack(fill="x", pady=4)
        self.days = tk.IntVar(value=s["default_window_days"])
        self.overlap = tk.IntVar(value=s["overlap_hours"])
        for label, var, top in (("First-run look-back (days)", self.days, 1500), ("Overlap on later runs (hours)", self.overlap, 240)):
            row = ttk.Frame(window)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label).pack(side="left")
            ttk.Spinbox(row, from_=0, to=top, width=6, textvariable=var).pack(side="right")
        ttk.Button(right, text="Reset search history", command=self.reset_history).pack(anchor="w", pady=(8, 0))

    def reset_history(self) -> None:
        if messagebox.askyesno("Reset search history", "Forget all covered time windows and read Gmail threads? "
                                                       "The next run will search the full look-back again."):
            cfg.save_log({"runs": [], "gmail_threads": []})
            self.reload()

    # ------------------------------------------------------------ Refresh & alerts
    def _build_refresh(self, frame) -> None:
        s = self.settings
        self.auto = tk.BooleanVar(value=s["auto_refresh"])
        ttk.Checkbutton(frame, text="Run the refresh automatically", variable=self.auto).pack(anchor="w")
        days = ttk.LabelFrame(frame, text="Refresh on these days (on other days the scheduled run only checks deadlines)", padding=6)
        days.pack(fill="x", pady=8)
        self.day_vars = {d: tk.BooleanVar(value=d in s["refresh_days"]) for d in cfg.DAYS}
        for d in cfg.DAYS:
            ttk.Checkbutton(days, text=d, variable=self.day_vars[d]).pack(side="left", padx=6)
        ttk.Label(frame, text=f"Time of day: {s['refresh_time']}. The Claude app's scheduler owns the time; ask Claude "
                              f"to change it. The app must be open (a missed run happens on next launch).",
                  foreground="#555555", wraplength=760).pack(anchor="w", pady=(0, 8))
        alerts = ttk.LabelFrame(frame, text="Alerts", padding=6)
        alerts.pack(fill="x")
        self.alert_days = tk.IntVar(value=s["alert_days"])
        self.action_days = tk.IntVar(value=s["next_action_alert_days"])
        for label, var in (("Warn about deadlines within (days)", self.alert_days),
                           ("Warn about next actions within (days)", self.action_days)):
            row = ttk.Frame(alerts)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label).pack(side="left")
            ttk.Spinbox(row, from_=1, to=120, width=6, textvariable=var).pack(side="right")

    # ------------------------------------------------------------ Applications
    def _build_apps(self, frame) -> None:
        s = self.settings
        ttk.Label(frame, text="Requirements pre-filled as 'Required' when an application of each type is started "
                              "(Claude then checks the official page and corrects them).", wraplength=760).pack(anchor="w")
        grid = ttk.Frame(frame, padding=(0, 8))
        grid.pack(anchor="w")
        ttk.Label(grid, text="").grid(row=0, column=0)
        for j, app_type in enumerate(cfg.APP_TYPES, start=1):
            ttk.Label(grid, text=app_type, wraplength=110, justify="center").grid(row=0, column=j, padx=6)
        self.req_vars = {}
        for i, req in enumerate(cfg.REQUIREMENTS, start=1):
            ttk.Label(grid, text=req).grid(row=i, column=0, sticky="w", pady=1)
            for j, app_type in enumerate(cfg.APP_TYPES, start=1):
                var = tk.BooleanVar(value=req in s["requirement_defaults"].get(app_type, []))
                self.req_vars[(app_type, req)] = var
                ttk.Checkbutton(grid, variable=var).grid(row=i, column=j)
        row = ttk.Frame(frame)
        row.pack(anchor="w", pady=(4, 0))
        ttk.Label(row, text="Default application fee status:").pack(side="left")
        self.fee = tk.StringVar(value=s["default_fee_status"])
        ttk.Combobox(row, textvariable=self.fee, values=cfg.FEE_STATUSES, state="readonly", width=18).pack(side="left", padx=6)

    # ------------------------------------------------------------ actions
    def save(self) -> None:
        try:
            changes = {
                "keywords": self._read(self.keywords), "exclude_terms": self._read(self.exclude),
                "gmail_senders": self._read(self.senders), "sites": [n for n, v in self.site_vars.items() if v.get()],
                "default_window_days": int(self.days.get()), "overlap_hours": int(self.overlap.get()),
                "auto_refresh": bool(self.auto.get()), "refresh_days": [d for d, v in self.day_vars.items() if v.get()],
                "alert_days": int(self.alert_days.get()), "next_action_alert_days": int(self.action_days.get()),
                "requirement_defaults": {t: [r for r in cfg.REQUIREMENTS if self.req_vars[(t, r)].get()] for t in cfg.APP_TYPES},
                "default_fee_status": self.fee.get(),
            }
        except (tk.TclError, ValueError):
            messagebox.showerror("Invalid value", "Days and hours must be whole numbers.")
            return
        problems = cfg.validate_settings(changes)
        if problems:
            messagebox.showerror("Invalid settings", "\n".join(problems))
            return
        settings = cfg.load_settings()
        settings.update(changes)
        cfg.save_settings(settings)
        self.status.config(text="Settings saved. They apply to the next search; no restart needed.")
        self.reload()

    def open_sheet(self) -> None:
        self._open(cfg.tracker_path())


if __name__ == "__main__":
    App().mainloop()
