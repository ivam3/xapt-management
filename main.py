#!/usr/bin/env python3
"""Xapt: a small Tkinter frontend for APT on Termux."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from xapt_core import AptError, AptService, CommandResult, Package

APP_NAME = "Xapt"
APP_VERSION = "2.0.0"
APP_TITLE = "Xapt - APT package manager"


class XaptApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.service = AptService()
        self.packages: list[Package] = []
        self.visible_packages: list[Package] = []
        self.busy = False
        self.events: queue.Queue[tuple] = queue.Queue()
        self.icons: dict[str, tk.PhotoImage] = {}
        self.current_package: str | None = None

        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="All packages")
        self.status_var = tk.StringVar(value="Ready")
        self.count_var = tk.StringVar(value="0 packages")

        self.root.title(APP_TITLE)
        self.root.geometry("1180x760")
        self.root.minsize(900, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self._configure_style()
        self._load_icons()
        self._build_ui()
        self._bind_keys()
        self.refresh_packages()
        self.root.after(100, self._drain_events)

    # ------------------------------------------------------------------
    # Presentation
    # ------------------------------------------------------------------
    def _configure_style(self) -> None:
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure(".", font=("DejaVu Sans", 10))
        self.style.configure("Title.TLabel", font=("DejaVu Sans", 18, "bold"))
        self.style.configure("Subtitle.TLabel", foreground="#4b5563")
        self.style.configure("Status.TLabel", foreground="#4b5563")
        self.style.configure("Accent.TButton", font=("DejaVu Sans", 10, "bold"))
        self.style.configure("Danger.TButton", foreground="#991b1b")
        self.style.configure("Treeview", rowheight=26)
        self.style.configure("Treeview.Heading", font=("DejaVu Sans", 10, "bold"))

    def _load_icons(self) -> None:
        base = Path(__file__).resolve().parent
        for name in ("xapt", "download", "uninstall", "info", "fix", "searching"):
            for folder in (base / "img", base / ".deb" / "img"):
                path = folder / f"{name}.png"
                if path.exists():
                    try:
                        self.icons[name] = tk.PhotoImage(file=str(path))
                        break
                    except tk.TclError:
                        continue
        if "xapt" in self.icons:
            try:
                self.root.iconphoto(True, self.icons["xapt"])
            except tk.TclError:
                pass

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        # Keep the search toolbar visible when the window is short (landscape).
        self.root.rowconfigure(1, weight=0)

        header = ttk.Frame(self.root, padding=(18, 14, 18, 8))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        title = ttk.Label(header, text=APP_TITLE, style="Title.TLabel")
        title.grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Install, inspect and maintain Termux packages without leaving the desktop.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        right = ttk.Frame(header)
        right.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(right, text="Theme").grid(row=0, column=0, padx=(0, 6))
        self.theme_box = ttk.Combobox(
            right,
            values=("clam", "alt", "default", "classic"),
            width=10,
            state="readonly",
        )
        self.theme_box.set("clam")
        self.theme_box.grid(row=0, column=1, padx=(0, 10))
        self.theme_box.bind("<<ComboboxSelected>>", self._change_theme)
        ttk.Button(right, text="About", command=self.show_about).grid(row=0, column=2)

        toolbar = ttk.Frame(self.root, padding=(18, 4, 18, 8))
        toolbar.grid(row=1, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)

        ttk.Label(toolbar, text="Search").grid(row=0, column=0, padx=(0, 6))
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.search_var.trace_add("write", lambda *_: self.apply_filter())

        ttk.Label(toolbar, text="Show").grid(row=0, column=2, padx=(0, 6))
        self.filter_box = ttk.Combobox(
            toolbar,
            textvariable=self.filter_var,
            values=("All packages", "Installed", "Upgradable"),
            width=16,
            state="readonly",
        )
        self.filter_box.grid(row=0, column=3, padx=(0, 8))
        self.filter_box.bind("<<ComboboxSelected>>", lambda *_: self.apply_filter())
        ttk.Button(toolbar, text="Refresh", command=self.refresh_packages).grid(row=0, column=4)

        body = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        body.grid(row=2, column=0, sticky="nsew", padx=18)
        self.root.rowconfigure(2, weight=1)

        left = ttk.Frame(body)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        body.add(left, weight=3)

        columns = ("package", "version", "status", "summary")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", height=8, selectmode="browse")
        self.tree.heading("package", text="Package")
        self.tree.heading("version", text="Version")
        self.tree.heading("status", text="Status")
        self.tree.heading("summary", text="Summary")
        self.tree.column("package", width=190, minwidth=120)
        self.tree.column("version", width=130, minwidth=90)
        self.tree.column("status", width=100, minwidth=80, anchor="center")
        self.tree.column("summary", width=420, minwidth=160)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.tag_configure("installed", foreground="#065f46")
        self.tree.tag_configure("upgradable", foreground="#92400e")

        tree_y = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        tree_y.grid(row=0, column=1, sticky="ns")
        tree_x = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.tree.xview)
        tree_x.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=tree_y.set, xscrollcommand=tree_x.set)

        right_panel = ttk.Frame(body)
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(0, weight=1)
        body.add(right_panel, weight=2)

        self.details = ttk.Notebook(right_panel)
        self.details.grid(row=0, column=0, sticky="nsew")
        self.details_text = self._text_tab(self.details, "Details")
        self.deps_text = self._text_tab(self.details, "Dependencies")
        self.files_text = self._text_tab(self.details, "Files")

        actions = ttk.Frame(self.root, padding=(18, 10, 18, 4))
        actions.grid(row=3, column=0, sticky="ew")
        for index in range(7):
            actions.columnconfigure(index, weight=1)

        self.action_buttons: list[ttk.Button] = []
        self._action(actions, 0, "Install", self.install_selected, "download", "Accent.TButton")
        self._action(actions, 1, "Remove", self.remove_selected, "uninstall", "Danger.TButton")
        self._action(actions, 2, "Purge", self.purge_selected, "uninstall", "Danger.TButton")
        self._action(actions, 3, "Update", self.update_index, "fix")
        self._action(actions, 4, "Upgrade", self.upgrade_all, "fix", "Accent.TButton")
        self._action(actions, 5, "Autoremove", self.autoremove, None)
        self._action(actions, 6, "Clean", self.clean_cache, None)

        lower_actions = ttk.Frame(self.root, padding=(18, 2, 18, 10))
        lower_actions.grid(row=4, column=0, sticky="ew")
        for index in range(4):
            lower_actions.columnconfigure(index, weight=1)
        self._action(lower_actions, 0, "Hold", self.hold_selected, None)
        self._action(lower_actions, 1, "Unhold", self.unhold_selected, None)
        self.cancel_button = self._action(lower_actions, 2, "Cancel operation", self.cancel_operation, None)
        self._action(lower_actions, 3, "Clear log", self.clear_log, None)

        log_frame = ttk.LabelFrame(self.root, text="APT output", padding=6)
        log_frame.grid(row=5, column=0, sticky="nsew", padx=18, pady=(0, 8))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.root.rowconfigure(5, weight=1)

        self.log = tk.Text(log_frame, width=40, height=6, wrap="word", state="disabled", font=("DejaVu Sans Mono", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.tag_configure("command", foreground="#1d4ed8")
        self.log.tag_configure("error", foreground="#b91c1c")
        self.log.tag_configure("success", foreground="#047857")

        status = ttk.Frame(self.root, padding=(18, 0, 18, 10))
        status.grid(row=6, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(status, textvariable=self.count_var, style="Status.TLabel").grid(row=0, column=1, sticky="e")

    def _text_tab(self, notebook: ttk.Notebook, title: str) -> scrolledtext.ScrolledText:
        frame = ttk.Frame(notebook)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        widget = scrolledtext.ScrolledText(
            frame,
            wrap="word",
            state="disabled",
            width=40,
            height=8,
            font=("DejaVu Sans", 9),
        )
        widget.grid(row=0, column=0, sticky="nsew")
        notebook.add(frame, text=title)
        return widget

    def _action(
        self,
        parent: ttk.Frame,
        column: int,
        text: str,
        command,
        icon: str | None = None,
        style: str = "TButton",
    ) -> ttk.Button:
        kwargs = {"text": text, "command": command, "style": style}
        if icon and icon in self.icons:
            kwargs["image"] = self.icons[icon]
            kwargs["compound"] = "left"
        button = ttk.Button(parent, **kwargs)
        button.grid(row=0, column=column, sticky="ew", padx=3)
        self.action_buttons.append(button)
        return button

    def _bind_keys(self) -> None:
        self.root.bind("<Control-f>", lambda _event: self.search_entry.focus_set())
        self.root.bind("<F5>", lambda _event: self.refresh_packages())
        self.root.bind("<Control-q>", lambda _event: self.close())

    # ------------------------------------------------------------------
    # Async event loop
    # ------------------------------------------------------------------
    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._append_log(event[1], event[2])
                elif kind == "status":
                    self.status_var.set(event[1])
                elif kind == "packages":
                    self.packages = event[1]
                    self.apply_filter()
                    self._set_busy(False)
                    self.status_var.set(f"Loaded {len(self.packages)} packages")
                elif kind == "details":
                    name, details, deps, files = event[1:]
                    if name == self.current_package:
                        self._set_text(self.details_text, details)
                        self._set_text(self.deps_text, deps)
                        self._set_text(self.files_text, files)
                elif kind == "done":
                    result: CommandResult = event[1]
                    self._set_busy(False)
                    if result.cancelled:
                        self._append_log("Operation cancelled.", "error")
                        self.status_var.set("Operation cancelled")
                    elif result.returncode == 0:
                        self._append_log("Operation completed successfully.", "success")
                        self.status_var.set("Operation completed")
                        self.refresh_packages()
                    else:
                        self._append_log(f"Operation failed with exit code {result.returncode}.", "error")
                        self.status_var.set("Operation failed")
                elif kind == "error":
                    self._set_busy(False)
                    self._append_log(str(event[1]), "error")
                    self.status_var.set("Error")
                    messagebox.showerror(APP_NAME, str(event[1]))
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in self.action_buttons:
            button.configure(state=state)
        if busy:
            self.cancel_button.configure(state="normal")
        self.filter_box.configure(state="disabled" if busy else "readonly")
        self.theme_box.configure(state="disabled" if busy else "readonly")
        self.search_entry.configure(state=state)

    def _run_async(self, label: str, worker) -> None:
        if self.busy:
            messagebox.showinfo(APP_NAME, "Another operation is already running.")
            return
        self._set_busy(True)
        self.status_var.set(label)
        self._append_log(label, "command")

        def runner() -> None:
            try:
                self.events.put(("done", worker()))
            except AptError as exc:
                self.events.put(("error", str(exc)))
            except Exception as exc:  # pragma: no cover - defensive UI guard
                self.events.put(("error", f"Unexpected error: {exc}"))

        threading.Thread(target=runner, daemon=True).start()

    # ------------------------------------------------------------------
    # Package list
    # ------------------------------------------------------------------
    def refresh_packages(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.status_var.set("Reading APT package index...")

        def loader() -> None:
            try:
                self.events.put(("packages", self.service.list_packages()))
            except AptError as exc:
                self.events.put(("error", str(exc)))
            except Exception as exc:  # pragma: no cover
                self.events.put(("error", f"Could not read package index: {exc}"))

        threading.Thread(target=loader, daemon=True).start()

    def apply_filter(self) -> None:
        query = self.search_var.get().strip().lower()
        mode = self.filter_var.get()
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        self.visible_packages = []
        for pkg in self.packages:
            if mode == "Installed" and pkg.status != "installed":
                continue
            if mode == "Upgradable" and pkg.status != "upgradable":
                continue
            haystack = f"{pkg.name} {pkg.summary}".lower()
            if query and query not in haystack:
                continue
            self.visible_packages.append(pkg)
            tags = (pkg.status,) if pkg.status in {"installed", "upgradable"} else ()
            item = self.tree.insert(
                "",
                "end",
                iid=pkg.name,
                values=(pkg.name, pkg.version, pkg.status.title(), pkg.summary),
                tags=tags,
            )
            if item in selected:
                self.tree.selection_add(item)
        self.count_var.set(f"{len(self.visible_packages)} of {len(self.packages)} packages")

    def _on_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        name = selection[0]
        self.current_package = name
        self._set_text(self.details_text, "Loading package details...")
        self._set_text(self.deps_text, "")
        self._set_text(self.files_text, "")
        if self.busy:
            return

        def loader() -> None:
            try:
                details = self.service.details(name)
                text = "\n".join(f"{key}: {value}" for key, value in details.items())
                deps = self.service.dependencies(name)
                files = self.service.files(name)
                self.events.put(("details", name, text, deps, files))
            except AptError as exc:
                self.events.put(("details", name, str(exc), "", ""))
            except Exception as exc:  # pragma: no cover
                self.events.put(("details", name, f"Could not load details: {exc}", "", ""))

        threading.Thread(target=loader, daemon=True).start()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def selected_package(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo(APP_NAME, "Select a package first.")
            return None
        return selection[0]

    def install_selected(self) -> None:
        name = self.selected_package()
        if name and messagebox.askyesno(APP_NAME, f"Install {name}?"):
            self._run_async(f"Installing {name}...", lambda: self.service.install(name, self._line_callback))

    def remove_selected(self) -> None:
        name = self.selected_package()
        if name and messagebox.askyesno(APP_NAME, f"Remove {name}?\nConfiguration files will be kept."):
            self._run_async(f"Removing {name}...", lambda: self.service.remove(name, self._line_callback))

    def purge_selected(self) -> None:
        name = self.selected_package()
        if name and messagebox.askyesno(
            APP_NAME,
            f"Purge {name}?\nThis removes the package and its configuration files.",
            icon="warning",
        ):
            self._run_async(f"Purging {name}...", lambda: self.service.purge(name, self._line_callback))

    def update_index(self) -> None:
        self._run_async("Updating APT index...", lambda: self.service.update(self._line_callback))

    def upgrade_all(self) -> None:
        if messagebox.askyesno(APP_NAME, "Upgrade all installed packages?"):
            self._run_async("Upgrading installed packages...", lambda: self.service.upgrade(self._line_callback))

    def autoremove(self) -> None:
        if messagebox.askyesno(APP_NAME, "Remove automatically installed packages that are no longer needed?"):
            self._run_async("Removing unused packages...", lambda: self.service.autoremove(self._line_callback))

    def clean_cache(self) -> None:
        if messagebox.askyesno(APP_NAME, "Clear the APT package cache?"):
            self._run_async("Cleaning APT cache...", lambda: self.service.clean(self._line_callback))

    def hold_selected(self) -> None:
        name = self.selected_package()
        if name:
            self._run_async(f"Holding {name}...", lambda: self.service.hold(name, self._line_callback))

    def unhold_selected(self) -> None:
        name = self.selected_package()
        if name:
            self._run_async(f"Unholding {name}...", lambda: self.service.unhold(name, self._line_callback))

    def cancel_operation(self) -> None:
        if not self.busy:
            self._append_log("No operation is running.", "error")
            return
        self.service.cancel()
        self.status_var.set("Cancelling operation...")

    def _line_callback(self, line: str) -> None:
        self.events.put(("log", line, "info"))

    # ------------------------------------------------------------------
    # Widget helpers
    # ------------------------------------------------------------------
    def _append_log(self, text: str, tag: str = "info") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    @staticmethod
    def _set_text(widget: scrolledtext.ScrolledText, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _change_theme(self, _event=None) -> None:
        try:
            self.style.theme_use(self.theme_box.get())
        except tk.TclError as exc:
            messagebox.showerror(APP_NAME, f"Could not apply theme: {exc}")

    def show_about(self) -> None:
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME} {APP_VERSION}\n\n"
            "A graphical frontend for the Advanced Package Tool (APT) on Termux.\n\n"
            "Maintainer: @Ivam3\n"
            "Project: https://github.com/ivam3/xapt-management\n"
            "Support: https://t.me/Ivam3_Bot",
        )

    def close(self) -> None:
        if self.busy and not messagebox.askyesno(APP_NAME, "An operation is running. Close anyway?"):
            return
        self.service.cancel()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    XaptApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
