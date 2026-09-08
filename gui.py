# -*- coding: utf-8 -*-
"""
Dr. Digital - GUI
==================
Run with:  python gui.py   (Administrator terminal recommended)

Requires only the standard library + the doctor_digital package.
"""

import ctypes
import datetime
import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

# ── Patch doctor_digital so GUI supplies confirmation instead of stdin ────────
import doctor_digital.usb_sanitizer as _san_mod
import doctor_digital._dir_sanitizer as _dir_mod
from doctor_digital.detect import detect_dir
from doctor_digital import usb_recovery

# ─────────────────────────────────────────────────────────────────────────────
# Colour palette
# ─────────────────────────────────────────────────────────────────────────────
BG        = "#0f1117"
PANEL     = "#1a1d27"
CARD      = "#1f2235"
ACCENT    = "#4f8ef7"
ACCENT2   = "#7c5cbf"
SUCCESS   = "#3ddc97"
DANGER    = "#f7604f"
WARNING   = "#f7c04f"
TEXT      = "#e8eaf0"
SUBTEXT   = "#8a8fa8"
BORDER    = "#2a2d3e"
HOVER     = "#252840"

FONT_FAMILY = "Segoe UI"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _fmt_size(gb: float) -> str:
    if gb >= 1000:
        return f"{gb/1000:.1f} TB"
    return f"{gb:.1f} GB"


def _drive_letter_for_disk(disk_number: int) -> str | None:
    """Return the first drive letter mapped to a physical disk number."""
    ps = (
        f"Get-Partition -DiskNumber {disk_number} | "
        "Get-Volume | Select-Object -ExpandProperty DriveLetter | "
        "Select-Object -First 1"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=10
        )
        letter = r.stdout.strip()
        return letter if len(letter) == 1 and letter.isalpha() else None
    except Exception:
        return None


def _list_path(path: str) -> list[dict]:
    """Return children of `path` as list of {name, type, size, modified}."""
    items = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    stat = entry.stat()
                    items.append({
                        "name": entry.name,
                        "type": "folder" if entry.is_dir() else "file",
                        "size": stat.st_size,
                        "modified": datetime.datetime.fromtimestamp(
                            stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        "path": entry.path,
                    })
                except Exception:
                    pass
    except Exception:
        pass
    items.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
    return items


# ─────────────────────────────────────────────────────────────────────────────
# Reusable styled widgets
# ─────────────────────────────────────────────────────────────────────────────

class FlatButton(tk.Label):
    """A label that looks and behaves like a flat button."""

    def __init__(self, parent, text, command=None,
                 bg=ACCENT, fg=TEXT, pad_x=18, pad_y=8,
                 radius=6, **kw):
        super().__init__(parent, text=text, bg=bg, fg=fg,
                         padx=pad_x, pady=pad_y,
                         font=(FONT_FAMILY, 10, "bold"),
                         cursor="hand2", **kw)
        self._bg = bg
        self._command = command
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>",   self._on_enter)
        self.bind("<Leave>",   self._on_leave)

    def _on_click(self, _=None):
        if self._command:
            self._command()

    def _on_enter(self, _=None):
        self.config(bg=_lighten(self._bg))

    def _on_leave(self, _=None):
        self.config(bg=self._bg)

    def set_command(self, cmd):
        self._command = cmd


def _lighten(hex_color: str, amount: int = 20) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = [int(hex_color[i:i+2], 16) for i in (0, 2, 4)]
    return "#{:02x}{:02x}{:02x}".format(
        min(255, r + amount), min(255, g + amount), min(255, b + amount))


class Spinner(tk.Canvas):
    """Simple animated arc spinner."""

    def __init__(self, parent, size=40, color=ACCENT, **kw):
        super().__init__(parent, width=size, height=size,
                         bg=kw.pop("bg", BG), highlightthickness=0, **kw)
        self._size = size
        self._color = color
        self._angle = 0
        self._running = False
        self._arc = None

    def start(self):
        self._running = True
        self._draw()

    def stop(self):
        self._running = False

    def _draw(self):
        if not self._running:
            return
        self.delete("all")
        m = 4
        s = self._size
        self.create_arc(m, m, s - m, s - m,
                        start=self._angle, extent=280,
                        outline=self._color, width=3, style="arc")
        self._angle = (self._angle + 8) % 360
        self.after(16, self._draw)


class ToastManager:
    """Shows small notification toasts in the top-right corner."""

    def __init__(self, root):
        self._root = root
        self._stack: list[tk.Toplevel] = []

    def show(self, message: str, kind: str = "info", duration: int = 3500):
        color = {
            "info":    ACCENT,
            "success": SUCCESS,
            "warning": WARNING,
            "error":   DANGER,
        }.get(kind, ACCENT)

        t = tk.Toplevel(self._root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=color)

        tk.Label(t, text=message, bg=color, fg=TEXT,
                 font=(FONT_FAMILY, 10), padx=16, pady=10,
                 wraplength=320, justify="left").pack()

        self._position(t)
        t.after(duration, lambda: self._dismiss(t))
        self._stack.append(t)

    def _position(self, t):
        self._root.update_idletasks()
        sw = self._root.winfo_screenwidth()
        t.update_idletasks()
        w = t.winfo_reqwidth()
        h = t.winfo_reqheight()
        offset = sum(w2.winfo_reqheight() + 8
                     for w2 in self._stack if w2.winfo_exists())
        x = sw - w - 20
        y = 60 + offset
        t.geometry(f"+{x}+{y}")

    def _dismiss(self, t):
        if t in self._stack:
            self._stack.remove(t)
        try:
            t.destroy()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Confirmation dialog (replaces stdin prompts from the backend)
# ─────────────────────────────────────────────────────────────────────────────

class SanitizeConfirmDialog(tk.Toplevel):
    """
    Modal dialog that collects the three confirmation inputs required by
    complete_sanitize and returns True/False.
    """

    def __init__(self, parent, disk: dict):
        super().__init__(parent)
        self.title("Confirm Sanitization")
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.grab_set()
        self.result = False

        self._disk = disk
        serial = disk.get("Serial", "")
        self._suffix = serial[-4:].upper() if len(serial) >= 4 else serial.upper()
        self._disk_num = str(disk.get("Disk#", ""))

        self._build()
        self._center(parent)

    def _center(self, parent):
        self.update_idletasks()
        pw = parent.winfo_rootx()
        py = parent.winfo_rooty()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        self.geometry(f"+{pw + (parent.winfo_width()-w)//2}+{py + (parent.winfo_height()-h)//2}")

    def _build(self):
        disk = self._disk
        size_gb = disk.get("Size (GB)", 0)

        # Header
        hdr = tk.Frame(self, bg=DANGER, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚠  DESTRUCTIVE ACTION — CANNOT BE UNDONE",
                 bg=DANGER, fg=TEXT, font=(FONT_FAMILY, 12, "bold")).pack()

        body = tk.Frame(self, bg=PANEL, padx=28, pady=20)
        body.pack(fill="both")

        # Disk info
        info = [
            ("Disk #",    self._disk_num),
            ("Model",     disk.get("Model", "Unknown")),
            ("Serial",    disk.get("Serial", "Unknown")),
            ("Size",      _fmt_size(size_gb)),
            ("Status",    disk.get("Status", "Unknown")),
        ]
        for label, val in info:
            row = tk.Frame(body, bg=PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"{label}:", bg=PANEL, fg=SUBTEXT,
                     font=(FONT_FAMILY, 10), width=10, anchor="w").pack(side="left")
            tk.Label(row, text=val, bg=PANEL, fg=TEXT,
                     font=(FONT_FAMILY, 10, "bold")).pack(side="left")

        sep = tk.Frame(body, bg=BORDER, height=1)
        sep.pack(fill="x", pady=14)

        def _field(label, placeholder):
            tk.Label(body, text=label, bg=PANEL, fg=TEXT,
                     font=(FONT_FAMILY, 10), anchor="w").pack(fill="x", pady=(6, 2))
            e = tk.Entry(body, bg=CARD, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=(FONT_FAMILY, 11),
                         highlightthickness=1, highlightcolor=ACCENT,
                         highlightbackground=BORDER)
            e.pack(fill="x", ipady=6)
            e.insert(0, placeholder)
            e.bind("<FocusIn>", lambda ev, ent=e, ph=placeholder: (
                ent.delete(0, "end") if ent.get() == ph else None))
            return e

        self._e_disk   = _field(f"Type the disk number to confirm:", self._disk_num)
        self._e_serial = _field(f"Type the last 4 characters of the serial  ({self._suffix}):", self._suffix)
        self._e_phrase = _field('Type exactly:  WIPE THIS DRIVE', "WIPE THIS DRIVE")

        sep2 = tk.Frame(body, bg=BORDER, height=1)
        sep2.pack(fill="x", pady=14)

        btns = tk.Frame(body, bg=PANEL)
        btns.pack(fill="x")
        FlatButton(btns, "Cancel", command=self.destroy,
                   bg=CARD, fg=SUBTEXT).pack(side="right", padx=(8, 0))
        FlatButton(btns, "Confirm & Wipe", command=self._confirm,
                   bg=DANGER).pack(side="right")

    def _confirm(self):
        disk_in   = self._e_disk.get().strip()
        serial_in = self._e_serial.get().strip().upper()
        phrase_in = self._e_phrase.get().strip()

        if disk_in != self._disk_num:
            messagebox.showerror("Mismatch", "Disk number does not match.", parent=self)
            return
        if serial_in != self._suffix:
            messagebox.showerror("Mismatch", "Serial suffix does not match.", parent=self)
            return
        if phrase_in != "WIPE THIS DRIVE":
            messagebox.showerror("Mismatch", 'You must type exactly "WIPE THIS DRIVE".', parent=self)
            return

        self.result = True
        self.destroy()


class DirSanitizeConfirmDialog(tk.Toplevel):
    """Confirmation dialog for directory sanitization."""

    def __init__(self, parent, path: str):
        super().__init__(parent)
        self.title("Confirm Directory Sanitization")
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.grab_set()
        self.result = False
        self._path = str(Path(path).resolve())
        self._build()
        self._center(parent)

    def _center(self, parent):
        self.update_idletasks()
        pw = parent.winfo_rootx()
        py = parent.winfo_rooty()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        self.geometry(f"+{pw + (parent.winfo_width()-w)//2}+{py + (parent.winfo_height()-h)//2}")

    def _build(self):
        hdr = tk.Frame(self, bg=DANGER, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚠  DIRECTORY SANITIZATION — ALL FILES WILL BE DESTROYED",
                 bg=DANGER, fg=TEXT, font=(FONT_FAMILY, 11, "bold")).pack()

        body = tk.Frame(self, bg=PANEL, padx=28, pady=20)
        body.pack(fill="both")

        tk.Label(body, text="Target directory:", bg=PANEL, fg=SUBTEXT,
                 font=(FONT_FAMILY, 10)).pack(anchor="w")
        tk.Label(body, text=self._path, bg=PANEL, fg=TEXT,
                 font=(FONT_FAMILY, 10, "bold"), wraplength=440).pack(anchor="w", pady=(2, 14))

        def _field(label, placeholder):
            tk.Label(body, text=label, bg=PANEL, fg=TEXT,
                     font=(FONT_FAMILY, 10), anchor="w").pack(fill="x", pady=(6, 2))
            e = tk.Entry(body, bg=CARD, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=(FONT_FAMILY, 11),
                         highlightthickness=1, highlightcolor=ACCENT,
                         highlightbackground=BORDER)
            e.pack(fill="x", ipady=6)
            e.insert(0, placeholder)
            e.bind("<FocusIn>", lambda ev, ent=e, ph=placeholder: (
                ent.delete(0, "end") if ent.get() == ph else None))
            return e

        self._e_path   = _field("Type the FULL directory path to confirm:", self._path)
        self._e_phrase = _field('Type exactly:  SANITIZE DIRECTORY', "SANITIZE DIRECTORY")

        sep = tk.Frame(body, bg=BORDER, height=1)
        sep.pack(fill="x", pady=14)

        btns = tk.Frame(body, bg=PANEL)
        btns.pack(fill="x")
        FlatButton(btns, "Cancel", command=self.destroy,
                   bg=CARD, fg=SUBTEXT).pack(side="right", padx=(8, 0))
        FlatButton(btns, "Confirm & Sanitize", command=self._confirm,
                   bg=DANGER).pack(side="right")

    def _confirm(self):
        path_in   = self._e_path.get().strip().strip('"')
        phrase_in = self._e_phrase.get().strip()

        try:
            typed_resolved = str(Path(path_in).resolve())
        except Exception:
            typed_resolved = path_in

        if typed_resolved.lower() != self._path.lower():
            messagebox.showerror("Mismatch", "Path does not match.", parent=self)
            return
        if phrase_in != "SANITIZE DIRECTORY":
            messagebox.showerror("Mismatch",
                                 'You must type exactly "SANITIZE DIRECTORY".', parent=self)
            return
        self.result = True
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Progress / log window (reusable for both recovery and sanitize)
# ─────────────────────────────────────────────────────────────────────────────

class ProgressWindow(tk.Toplevel):
    """
    Modal window with a log area + progress bar.
    Feed it via a queue with tuples:
        ("log",   text)
        ("progress", float 0-100)
        ("done",  message)
        ("error", message)
    """

    def __init__(self, parent, title: str, q: queue.Queue):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=PANEL)
        self.resizable(True, True)
        self.geometry("700x480")
        self.grab_set()
        self._q = q
        self._done = False
        self._build()
        self._poll()

    def _build(self):
        # Title bar area
        top = tk.Frame(self, bg=PANEL, padx=20, pady=14)
        top.pack(fill="x")
        tk.Label(top, text=self.title(), bg=PANEL, fg=TEXT,
                 font=(FONT_FAMILY, 13, "bold")).pack(side="left")

        self._spinner = Spinner(top, size=26, bg=PANEL)
        self._spinner.pack(side="right")
        self._spinner.start()

        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(fill="x")

        # Progress bar
        pb_frame = tk.Frame(self, bg=PANEL, padx=20, pady=10)
        pb_frame.pack(fill="x")

        self._pct_label = tk.Label(pb_frame, text="0%", bg=PANEL, fg=ACCENT,
                                   font=(FONT_FAMILY, 10, "bold"))
        self._pct_label.pack(anchor="e")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("DD.Horizontal.TProgressbar",
                        troughcolor=CARD, background=ACCENT,
                        bordercolor=BORDER, lightcolor=ACCENT,
                        darkcolor=ACCENT, thickness=8)
        self._pb = ttk.Progressbar(pb_frame, style="DD.Horizontal.TProgressbar",
                                   length=660, maximum=100)
        self._pb.pack(fill="x")

        # Log area
        log_frame = tk.Frame(self, bg=PANEL, padx=20, pady=4)
        log_frame.pack(fill="both", expand=True)

        self._log = tk.Text(log_frame, bg=CARD, fg=TEXT,
                            font=("Consolas", 9),
                            relief="flat", wrap="word",
                            state="disabled",
                            highlightthickness=1,
                            highlightbackground=BORDER)
        sb = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log.pack(fill="both", expand=True)

        # Configure text tags
        self._log.tag_config("ok",      foreground=SUCCESS)
        self._log.tag_config("err",     foreground=DANGER)
        self._log.tag_config("warn",    foreground=WARNING)
        self._log.tag_config("info",    foreground=ACCENT)
        self._log.tag_config("default", foreground=TEXT)

        # Close button (disabled until done)
        btn_row = tk.Frame(self, bg=PANEL, padx=20, pady=12)
        btn_row.pack(fill="x")
        self._close_btn = FlatButton(btn_row, "Close", command=self.destroy,
                                     bg=CARD, fg=SUBTEXT)
        self._close_btn.pack(side="right")
        self._close_btn.config(state="disabled")

    def _append(self, text: str, tag: str = "default"):
        self._log.config(state="normal")
        self._log.insert("end", text + "\n", tag)
        self._log.see("end")
        self._log.config(state="disabled")

    def _poll(self):
        try:
            while True:
                msg = self._q.get_nowait()
                kind = msg[0]

                if kind == "log":
                    text = msg[1]
                    tag = "default"
                    tl = text.lower()
                    if any(w in tl for w in ("ok", "success", "done", "complete", "recovered")):
                        tag = "ok"
                    elif any(w in tl for w in ("error", "failed", "fail", "abort")):
                        tag = "err"
                    elif any(w in tl for w in ("warning", "warn", "note", "important")):
                        tag = "warn"
                    elif text.startswith("[") or any(w in tl for w in ("scanning", "reading", "writing", "opening", "zeroing")):
                        tag = "info"
                    self._append(text, tag)

                elif kind == "progress":
                    val = float(msg[1])
                    self._pb["value"] = val
                    self._pct_label.config(text=f"{val:.0f}%")

                elif kind == "done":
                    self._spinner.stop()
                    self._append("\n" + msg[1], "ok")
                    self._pb["value"] = 100
                    self._pct_label.config(text="100%")
                    self._close_btn.config(state="normal", cursor="hand2")
                    self._done = True

                elif kind == "error":
                    self._spinner.stop()
                    self._append("\n" + msg[1], "err")
                    self._close_btn.config(state="normal", cursor="hand2")
                    self._done = True

        except queue.Empty:
            pass

        if not self._done:
            self.after(80, self._poll)


# ─────────────────────────────────────────────────────────────────────────────
# File browser panel (shown when user clicks "Open")
# ─────────────────────────────────────────────────────────────────────────────

class FileBrowserWindow(tk.Toplevel):
    """Browse files/folders on the selected drive (read-only, right-click sanitize)."""

    def __init__(self, parent, disk: dict, drive_letter: str, toast: ToastManager):
        super().__init__(parent)
        self.title(f"Browse — {disk.get('Model', 'USB Drive')}  ({drive_letter}:)")
        self.configure(bg=PANEL)
        self.geometry("820x540")
        self._parent_win = parent
        self._disk = disk
        self._drive = drive_letter
        self._root_path = f"{drive_letter}:\\"
        self._current_path = self._root_path
        self._history: list[str] = []
        self._toast = toast
        self._build()
        self._navigate(self._root_path)

    def _build(self):
        # Nav bar
        nav = tk.Frame(self, bg=CARD, padx=10, pady=8)
        nav.pack(fill="x")

        self._back_btn = FlatButton(nav, "◀", command=self._go_back,
                                    bg=PANEL, fg=SUBTEXT, pad_x=10, pad_y=4)
        self._back_btn.pack(side="left")

        self._path_var = tk.StringVar()
        path_entry = tk.Entry(nav, textvariable=self._path_var,
                              bg=BG, fg=TEXT, insertbackground=TEXT,
                              relief="flat", font=(FONT_FAMILY, 10),
                              highlightthickness=1,
                              highlightbackground=BORDER,
                              highlightcolor=ACCENT)
        path_entry.pack(side="left", fill="x", expand=True, padx=10, ipady=4)
        path_entry.bind("<Return>", lambda _: self._navigate(self._path_var.get()))

        FlatButton(nav, "Go", command=lambda: self._navigate(self._path_var.get()),
                   bg=ACCENT, pad_x=12, pad_y=4).pack(side="left")

        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(fill="x")

        # Tree
        tree_frame = tk.Frame(self, bg=PANEL)
        tree_frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.configure("FB.Treeview",
                        background=PANEL, fieldbackground=PANEL,
                        foreground=TEXT, rowheight=26,
                        font=(FONT_FAMILY, 10))
        style.configure("FB.Treeview.Heading",
                        background=CARD, foreground=SUBTEXT,
                        font=(FONT_FAMILY, 9, "bold"), relief="flat")
        style.map("FB.Treeview",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", TEXT)])

        self._tree = ttk.Treeview(tree_frame,
                                  columns=("type", "size", "modified"),
                                  show="tree headings",
                                  style="FB.Treeview",
                                  selectmode="browse")
        self._tree.heading("#0",       text="Name", anchor="w")
        self._tree.heading("type",     text="Type", anchor="w")
        self._tree.heading("size",     text="Size",     anchor="e")
        self._tree.heading("modified", text="Modified", anchor="w")
        self._tree.column("#0",       width=320, minwidth=180)
        self._tree.column("type",     width=80,  minwidth=60)
        self._tree.column("size",     width=90,  minwidth=60, anchor="e")
        self._tree.column("modified", width=150, minwidth=120)

        sb = ttk.Scrollbar(tree_frame, command=self._tree.yview)
        self._tree.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        self._tree.bind("<Double-1>",    self._on_double_click)
        self._tree.bind("<Button-3>",    self._on_right_click)

        # Right-click context menu
        self._ctx = tk.Menu(self, tearoff=False, bg=CARD, fg=TEXT,
                            activebackground=ACCENT, activeforeground=TEXT,
                            relief="flat", borderwidth=0,
                            font=(FONT_FAMILY, 10))
        self._ctx.add_command(label="🧹  Sanitize this directory",
                              command=self._sanitize_selected)

        # Status bar
        status_bar = tk.Frame(self, bg=CARD, padx=12, pady=5)
        status_bar.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="")
        tk.Label(status_bar, textvariable=self._status_var, bg=CARD,
                 fg=SUBTEXT, font=(FONT_FAMILY, 9)).pack(side="left")

    def _navigate(self, path: str):
        path = str(Path(path).resolve())
        if not os.path.isdir(path):
            self._toast.show(f"Not a directory: {path}", "error")
            return
        if self._current_path and path != self._current_path:
            self._history.append(self._current_path)
        self._current_path = path
        self._path_var.set(path)
        self._load(path)

    def _go_back(self):
        if self._history:
            prev = self._history.pop()
            self._current_path = prev
            self._path_var.set(prev)
            self._load(prev)

    def _load(self, path: str):
        for row in self._tree.get_children():
            self._tree.delete(row)

        items = _list_path(path)

        icons = {"folder": "📁", "file": "📄"}
        for item in items:
            icon = icons.get(item["type"], "📄")
            size_str = ""
            if item["type"] == "file":
                sz = item["size"]
                if sz < 1024:
                    size_str = f"{sz} B"
                elif sz < 1024**2:
                    size_str = f"{sz/1024:.1f} KB"
                elif sz < 1024**3:
                    size_str = f"{sz/1024**2:.1f} MB"
                else:
                    size_str = f"{sz/1024**3:.1f} GB"

            self._tree.insert("", "end",
                              text=f"  {icon}  {item['name']}",
                              values=(item["type"], size_str, item["modified"]),
                              tags=(item["path"],))

        self._status_var.set(f"{len(items)} items   ·   {path}")

    def _on_double_click(self, event):
        sel = self._tree.selection()
        if not sel:
            return
        item = self._tree.item(sel[0])
        itype = item["values"][0] if item["values"] else ""
        path = item["tags"][0] if item["tags"] else ""
        if itype == "folder" and path:
            self._navigate(path)

    def _on_right_click(self, event):
        row = self._tree.identify_row(event.y)
        if not row:
            return
        self._tree.selection_set(row)
        item = self._tree.item(row)
        itype = item["values"][0] if item["values"] else ""
        if itype == "folder":
            self._ctx.post(event.x_root, event.y_root)

    def _sanitize_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        item = self._tree.item(sel[0])
        path = item["tags"][0] if item["tags"] else ""
        if not path or not os.path.isdir(path):
            return

        dlg = DirSanitizeConfirmDialog(self, path)
        self.wait_window(dlg)
        if not dlg.result:
            return

        q: queue.Queue = queue.Queue()
        pw = ProgressWindow(self, f"Sanitizing Directory: {Path(path).name}", q)

        def run():
            _run_dir_sanitize_gui(path, q)

        threading.Thread(target=run, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Backend workers that post to a queue instead of stdout
# ─────────────────────────────────────────────────────────────────────────────

def _run_dir_sanitize_gui(path: str, q: queue.Queue):
    """Run directory sanitization and post progress to queue."""
    import ctypes
    import random
    import string

    DRIVE_REMOVABLE = 2

    def _get_drive_type(p):
        root = os.path.splitdrive(os.path.abspath(p))[0] + "\\"
        return ctypes.windll.kernel32.GetDriveTypeW(root)

    def _is_removable(p):
        try:
            return _get_drive_type(p) == DRIVE_REMOVABLE
        except Exception:
            return False

    def _is_root(p):
        p2 = Path(p).resolve()
        return p2.parent == Path(p2.anchor)

    directory = Path(path).resolve()

    if not directory.exists():
        q.put(("error", f"Directory does not exist: {directory}"))
        return
    if not directory.is_dir():
        q.put(("error", f"Not a directory: {directory}"))
        return
    if not _is_removable(directory):
        q.put(("error", "SAFETY BLOCK: Target is not on a removable USB drive."))
        return
    if _is_root(directory):
        q.put(("error", "SAFETY BLOCK: Cannot sanitize the root of a drive."))
        return

    q.put(("log", f"Scanning: {directory}"))
    files = [Path(root) / f
             for root, _, fnames in os.walk(directory)
             for f in fnames]
    total = len(files)
    q.put(("log", f"Files found: {total}"))

    if total == 0:
        q.put(("log", "No files found. Removing empty directory tree..."))
    
    done = 0
    passes = 2
    chunk = 1024 * 1024

    def _random_name(n=24):
        return "".join(random.choice(string.ascii_letters + string.digits)
                       for _ in range(n))

    for fp in files:
        fp = Path(fp)
        q.put(("log", f"  Sanitizing: {fp.name}"))
        try:
            size = fp.stat().st_size
            if size > 0:
                with open(fp, "r+b", buffering=0) as f:
                    for pass_num in range(passes):
                        f.seek(0)
                        remaining = size
                        while remaining > 0:
                            amount = min(chunk, remaining)
                            data = os.urandom(amount) if pass_num == 0 else b"\x00" * amount
                            f.write(data)
                            remaining -= amount
                        f.flush()
                        os.fsync(f.fileno())
            new_path = fp.with_name("." + _random_name() + ".tmp")
            fp.rename(new_path)
            new_path.unlink()
            q.put(("log", f"    ✓ Done"))
        except Exception as e:
            q.put(("log", f"    ✗ Error: {e}"))

        done += 1
        q.put(("progress", done / max(total, 1) * 90))

    # Remove empty directories
    q.put(("log", "Removing directory structure..."))
    for root, dirs, _ in os.walk(directory, topdown=False):
        for d in dirs:
            try:
                (Path(root) / d).rmdir()
            except OSError:
                pass
    try:
        directory.rmdir()
    except OSError as e:
        q.put(("log", f"WARNING: Could not remove root dir: {e}"))

    q.put(("progress", 100))
    q.put(("done", f"Directory sanitization complete. {total} files processed."))


def _run_complete_sanitize_gui(disk: dict, q: queue.Queue):
    """Run full disk sanitization posting progress to queue. No stdin used."""

    def log(msg):
        q.put(("log", msg))

    def prog(val):
        q.put(("progress", val))

    disk_number = disk.get("_number") or disk.get("Disk#")
    if disk_number is None:
        q.put(("error", "Invalid disk dict."))
        return

    drive_letter = "Z"
    steps = []

    try:
        log(f"Starting sanitization of Disk {disk_number} — {disk.get('Model','')}")
        log(f"Size: {disk.get('Size (GB)', 0)} GB")
        log("")

        # Step 1: Zero wipe
        log("▶ [1/4] Zero-wiping entire disk (diskpart clean all)...")
        log("  This writes zeroes to every sector. This will take a while...")
        prog(5)

        start = time.time()
        script_text = f"select disk {disk_number}\nclean all\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(script_text)
            script_path = f.name
        try:
            result = subprocess.run(["diskpart", "/s", script_path],
                                    capture_output=True, text=True)
            output = result.stdout
        finally:
            os.unlink(script_path)

        elapsed = round(time.time() - start, 1)
        success = "DiskPart succeeded" in output or "successfully" in output.lower()
        steps.append({"step": "clean_all", "success": success, "elapsed_sec": elapsed})
        log(f"  Zero wipe done in {elapsed}s — success={success}")
        prog(30)

        # Step 2: Random fill
        log("")
        log("▶ [2/4] Random-data fill pass...")

        start2 = time.time()
        _run_dp = lambda cmds: subprocess.run(
            ["diskpart", "/s",
             _tmp_script("\n".join(cmds) + "\n")],
            capture_output=True, text=True).stdout

        def _tmp_script(txt):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write(txt)
                return f.name

        dp_out = _run_dp([
            f"select disk {disk_number}",
            "create partition primary",
            "format fs=ntfs quick",
            f"assign letter={drive_letter}",
        ])
        time.sleep(2)
        log(f"  Volume created on {drive_letter}:")

        target = f"{drive_letter}:\\__sanitize_fill__.tmp"
        bytes_written = 0
        CHUNK = 64 * 1024 * 1024
        disk_size = disk.get("_size_bytes", 0) or 0

        try:
            with open(target, "wb") as f:
                while True:
                    try:
                        f.write(os.urandom(CHUNK))
                        bytes_written += CHUNK
                        gb = bytes_written / (1024**3)
                        log(f"  ...wrote {gb:.2f} GB of random data")
                        if disk_size > 0:
                            prog(30 + int((bytes_written / disk_size) * 20))
                    except OSError:
                        break
        except OSError:
            pass

        try:
            os.remove(target)
        except OSError:
            pass

        elapsed2 = round(time.time() - start2, 1)
        log(f"  Random fill done: {bytes_written/(1024**3):.2f} GB in {elapsed2}s")
        steps.append({"step": "random_fill", "success": bytes_written > 0,
                      "bytes_written": bytes_written, "elapsed_sec": elapsed2})
        prog(55)

        # Re-zero
        log("")
        log("▶ [2b/4] Re-zeroing after random fill...")
        start3 = time.time()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(f"select disk {disk_number}\nclean all\n")
            sp = f.name
        try:
            r2 = subprocess.run(["diskpart", "/s", sp], capture_output=True, text=True)
            o2 = r2.stdout
        finally:
            os.unlink(sp)
        e3 = round(time.time() - start3, 1)
        s2 = "DiskPart succeeded" in o2 or "successfully" in o2.lower()
        steps.append({"step": "re_zero", "success": s2, "elapsed_sec": e3})
        log(f"  Re-zero done in {e3}s — success={s2}")
        prog(75)

        # Verify
        log("")
        log("▶ [3/4] Verifying wipe by sampling raw sectors...")
        path_str = rf"\\.\PhysicalDrive{disk_number}"
        sample_count = 8
        sample_size  = 4096
        v_results = []
        try:
            with open(path_str, "rb", buffering=0) as f:
                f.seek(0, os.SEEK_END)
                sz = f.tell()
                for i in range(sample_count):
                    offset = int((sz - sample_size) * (i / max(sample_count - 1, 1)))
                    offset -= offset % 512
                    f.seek(offset)
                    data = f.read(sample_size)
                    zeroed = all(b == 0 for b in data)
                    has_sig = data[510:512] == b"\x55\xAA" if len(data) >= 512 else False
                    v_results.append({"offset": offset, "zeroed": zeroed,
                                      "partition_signature_found": has_sig})
            clean = sum(1 for r in v_results
                        if r["zeroed"] and not r["partition_signature_found"])
            rate = clean / len(v_results) if v_results else 0
            verification = {"verified": True, "sample_count": len(v_results),
                            "clean_sample_count": clean, "pass_rate": round(rate, 3)}
            log(f"  Verification: {clean}/{len(v_results)} sectors clean "
                f"(pass rate {rate*100:.0f}%)")
        except Exception as ve:
            verification = {"verified": False, "error": str(ve)}
            log(f"  Verification error: {ve}")
        prog(85)

        # Recreate volume
        log("")
        log("▶ [4/4] Recreating usable volume...")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(
                f"select disk {disk_number}\n"
                "create partition primary\n"
                "format fs=exfat quick\n"
                f"assign letter={drive_letter}\n"
            )
            sp4 = f.name
        try:
            r4 = subprocess.run(["diskpart", "/s", sp4], capture_output=True, text=True)
            o4 = r4.stdout
        finally:
            os.unlink(sp4)
        s4 = "successfully" in o4.lower()
        steps.append({"step": "recreate_volume", "success": s4})
        log(f"  Volume recreated (exFAT) — success={s4}")
        prog(95)

        # Score
        score_val = 0
        if success:  score_val += 40
        if bytes_written > 0: score_val += 20
        if verification.get("verified"):
            score_val += round(verification.get("pass_rate", 0) * 30)
        score_val = min(score_val, 90)

        # Audit log
        AUDIT_DIR = os.path.join(os.path.expanduser("~"), "usb_sanitizer_logs")
        os.makedirs(AUDIT_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_id = str(__import__("uuid").uuid4())
        record = {
            "log_id": log_id, "timestamp": ts,
            "operator": os.environ.get("USERNAME", "unknown"),
            "target_disk": disk, "steps": steps,
            "verification": verification,
            "confidence_score": score_val,
        }
        json_path = os.path.join(AUDIT_DIR, f"wipe_audit_{ts}_{log_id[:8]}.json")
        with open(json_path, "w") as jf:
            json.dump(record, jf, indent=2)
        with open(json_path, "rb") as jf:
            fh = hashlib.sha256(jf.read()).hexdigest()
        with open(json_path + ".sha256", "w") as jf:
            jf.write(f"{fh}  {os.path.basename(json_path)}\n")

        log("")
        log(f"  Audit log: {json_path}")
        prog(100)
        q.put(("done",
               f"✓ Sanitization complete!\n"
               f"  Confidence score: {score_val}/100\n"
               f"  Audit log saved to: {json_path}"))

    except Exception as exc:
        q.put(("error", f"Sanitization failed: {exc}"))


def _run_recovery_gui(disk: dict, file_types: list, output_dir: str, q: queue.Queue):
    """Run recovery posting file-found events to the queue."""

    disk_number = disk.get("_number") or disk.get("Disk#")
    physical_path = rf"\\.\PhysicalDrive{disk_number}"
    disk_size = disk.get("_size_bytes", 0) or 0

    _SIGNATURES = {
        "png":  {"start": b"\x89PNG\r\n\x1a\n",
                 "end":   b"\x00\x00\x00\x00IEND\xaeB`\x82",
                 "ext": ".png", "label": "PNG"},
        "jpeg": {"start": b"\xff\xd8\xff",
                 "end":   b"\xff\xd9",
                 "ext": ".jpg", "label": "JPEG"},
        "jpg":  {"start": b"\xff\xd8\xff",
                 "end":   b"\xff\xd9",
                 "ext": ".jpg", "label": "JPEG"},
        "text": {"start": None, "end": None, "ext": ".txt", "label": "TEXT"},
        "txt":  {"start": None, "end": None, "ext": ".txt", "label": "TEXT"},
    }

    requested = []
    for ft in file_types:
        k = ft.lower()
        if k in _SIGNATURES and k not in requested:
            requested.append(k)

    os.makedirs(output_dir, exist_ok=True)
    counters = {k: [1] for k in requested}

    CHUNK_SIZE = 4 * 1024 * 1024
    total_read = 0
    total_recovered = 0

    def carve_binary(data, sig, base_offset, key):
        nonlocal total_recovered
        pos = 0
        while True:
            start = data.find(sig["start"], pos)
            if start == -1:
                break
            end = data.find(sig["end"], start + len(sig["start"]))
            if end == -1:
                break
            end += len(sig["end"])
            fname = os.path.join(output_dir,
                                 f"recovered_{sig['label'].lower()}_{counters[key][0]:04d}{sig['ext']}")
            with open(fname, "wb") as f:
                f.write(data[start:end])
            q.put(("log", f"[{sig['label']}] {os.path.basename(fname)}  "
                          f"(offset 0x{base_offset + start:X})"))
            counters[key][0] += 1
            total_recovered += 1
            pos = end

    def carve_text(data, base_offset):
        nonlocal total_recovered
        pos = 0
        length = len(data)
        while pos < length:
            while pos < length and not (0x20 <= data[pos] <= 0x7E
                                        or data[pos] in (9, 10, 13)):
                pos += 1
            if pos >= length:
                break
            run_start = pos
            while pos < length and (0x20 <= data[pos] <= 0x7E
                                    or data[pos] in (9, 10, 13)):
                pos += 1
            run_end = pos
            if run_end - run_start >= 64:
                key = "text" if "text" in requested else "txt"
                fname = os.path.join(output_dir,
                                     f"recovered_text_{counters[key][0]:04d}.txt")
                with open(fname, "wb") as f:
                    f.write(data[run_start:run_end])
                q.put(("log", f"[TEXT] {os.path.basename(fname)}  "
                              f"(offset 0x{base_offset + run_start:X}, "
                              f"{run_end-run_start} B)"))
                counters[key][0] += 1
                total_recovered += 1

    q.put(("log", f"Opening: {physical_path}"))
    q.put(("log", f"Scanning for: {', '.join(requested)}"))
    q.put(("log", f"Output dir: {output_dir}"))
    q.put(("log", ""))

    try:
        with open(physical_path, "rb", buffering=0) as drive:
            while True:
                try:
                    data = drive.read(CHUNK_SIZE)
                except PermissionError:
                    q.put(("log", "Reached end of physical drive."))
                    break
                except OSError as e:
                    q.put(("log", f"Read error at offset {total_read}: {e}"))
                    break

                if not data:
                    break

                for key in requested:
                    sig = _SIGNATURES[key]
                    if sig["start"] is not None:
                        carve_binary(data, sig, total_read, key)
                    elif key in ("text", "txt"):
                        carve_text(data, total_read)

                total_read += len(data)
                gb = total_read / (1024**3)
                pct = (total_read / disk_size * 100) if disk_size > 0 else 0
                q.put(("log", f"  Scanned {gb:.2f} GB — {total_recovered} files recovered"))
                if disk_size > 0:
                    q.put(("progress", min(pct, 99)))

    except Exception as e:
        q.put(("error", f"Recovery failed: {e}"))
        return

    summary_lines = [f"Recovery scan complete."]
    for key in requested:
        label = _SIGNATURES[key]["label"]
        count = counters[key][0] - 1
        summary_lines.append(f"  {label} files recovered: {count}")
    summary_lines.append(f"  Output directory: {output_dir}")
    q.put(("done", "\n".join(summary_lines)))


# ─────────────────────────────────────────────────────────────────────────────
# Recovery setup dialog
# ─────────────────────────────────────────────────────────────────────────────

class RecoverySetupDialog(tk.Toplevel):
    def __init__(self, parent, disk: dict):
        super().__init__(parent)
        self.title("Recovery Setup")
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.grab_set()
        self._disk = disk
        self.result = None  # (file_types, output_dir) or None
        self._build()
        self._center(parent)

    def _center(self, parent):
        self.update_idletasks()
        pw = parent.winfo_rootx()
        py = parent.winfo_rooty()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        self.geometry(f"+{pw + (parent.winfo_width()-w)//2}+{py + (parent.winfo_height()-h)//2}")

    def _build(self):
        hdr = tk.Frame(self, bg=ACCENT2, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🔍  Configure Recovery",
                 bg=ACCENT2, fg=TEXT, font=(FONT_FAMILY, 13, "bold")).pack()

        body = tk.Frame(self, bg=PANEL, padx=28, pady=20)
        body.pack(fill="both")

        tk.Label(body, text="Select file types to recover:",
                 bg=PANEL, fg=TEXT, font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(0, 8))

        self._vars = {}
        types = [("JPEG / JPG images", "jpeg"),
                 ("PNG images",        "png"),
                 ("Text files",        "text")]
        for label, key in types:
            var = tk.BooleanVar(value=True)
            cb = tk.Checkbutton(body, text=label, variable=var,
                                bg=PANEL, fg=TEXT, activebackground=PANEL,
                                activeforeground=ACCENT, selectcolor=CARD,
                                font=(FONT_FAMILY, 10), cursor="hand2")
            cb.pack(anchor="w", pady=2)
            self._vars[key] = var

        sep = tk.Frame(body, bg=BORDER, height=1)
        sep.pack(fill="x", pady=14)

        tk.Label(body, text="Output directory (on your system, not on the USB):",
                 bg=PANEL, fg=TEXT, font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(0, 6))

        dir_row = tk.Frame(body, bg=PANEL)
        dir_row.pack(fill="x")
        self._out_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "recovered_files"))
        out_entry = tk.Entry(dir_row, textvariable=self._out_var,
                             bg=CARD, fg=TEXT, insertbackground=TEXT,
                             relief="flat", font=(FONT_FAMILY, 10),
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=ACCENT)
        out_entry.pack(side="left", fill="x", expand=True, ipady=6)
        FlatButton(dir_row, "Browse", command=self._browse,
                   bg=CARD, fg=TEXT, pad_x=12, pad_y=6).pack(side="left", padx=(8, 0))

        sep2 = tk.Frame(body, bg=BORDER, height=1)
        sep2.pack(fill="x", pady=14)

        btns = tk.Frame(body, bg=PANEL)
        btns.pack(fill="x")
        FlatButton(btns, "Cancel", command=self.destroy,
                   bg=CARD, fg=SUBTEXT).pack(side="right", padx=(8, 0))
        FlatButton(btns, "Start Recovery", command=self._start,
                   bg=SUCCESS, fg=BG).pack(side="right")

    def _browse(self):
        d = filedialog.askdirectory(title="Select output folder",
                                    initialdir=self._out_var.get())
        if d:
            self._out_var.set(d)

    def _start(self):
        selected = [k for k, v in self._vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("No types", "Select at least one file type.", parent=self)
            return
        out = self._out_var.get().strip()
        if not out:
            messagebox.showwarning("No output dir", "Choose an output directory.", parent=self)
            return
        self.result = (selected, out)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Main application window
# ─────────────────────────────────────────────────────────────────────────────

class DrDigitalApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Dr. Digital")
        self.configure(bg=BG)
        self.geometry("960x620")
        self.minsize(760, 480)
        self._set_icon()
        self._disks: list[dict] = []
        self._selected_disk: dict | None = None
        self._toast = ToastManager(self)
        self._build_ui()

    def _set_icon(self):
        try:
            # Create a simple canvas icon via a PhotoImage
            img = tk.PhotoImage(width=32, height=32)
            self.iconphoto(True, img)
        except Exception:
            pass

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        # ── Sidebar ──────────────────────────────────────────────────────
        self._sidebar = tk.Frame(self, bg=PANEL, width=220)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        # Logo
        logo_frame = tk.Frame(self._sidebar, bg=PANEL, pady=22)
        logo_frame.pack(fill="x")
        tk.Label(logo_frame, text="💾", bg=PANEL, font=(FONT_FAMILY, 28)).pack()
        tk.Label(logo_frame, text="Dr. Digital", bg=PANEL, fg=TEXT,
                 font=(FONT_FAMILY, 15, "bold")).pack()
        tk.Label(logo_frame, text="USB Toolkit", bg=PANEL, fg=SUBTEXT,
                 font=(FONT_FAMILY, 9)).pack()

        sep = tk.Frame(self._sidebar, bg=BORDER, height=1)
        sep.pack(fill="x", padx=16)

        # Scan button
        scan_frame = tk.Frame(self._sidebar, bg=PANEL, padx=16, pady=16)
        scan_frame.pack(fill="x")
        self._scan_btn = FlatButton(scan_frame, "🔍  Scan for Drives",
                                    command=self._start_scan,
                                    bg=ACCENT, fg=TEXT, pad_x=14, pad_y=10)
        self._scan_btn.pack(fill="x")

        self._scan_spinner = Spinner(scan_frame, size=28, bg=PANEL)
        self._scan_spinner.pack(pady=(6, 0))

        sep2 = tk.Frame(self._sidebar, bg=BORDER, height=1)
        sep2.pack(fill="x", padx=16)

        # Admin warning
        if not _is_admin():
            warn = tk.Frame(self._sidebar, bg="#3d2000", padx=12, pady=10)
            warn.pack(fill="x", padx=10, pady=10)
            tk.Label(warn, text="⚠ Not running as\nAdministrator.\nSome features\nmay fail.",
                     bg="#3d2000", fg=WARNING, font=(FONT_FAMILY, 9),
                     justify="center").pack()

        # ── Main content ──────────────────────────────────────────────────
        content = tk.Frame(self, bg=BG)
        content.pack(side="left", fill="both", expand=True)

        # Top bar
        topbar = tk.Frame(content, bg=CARD, height=52)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        tk.Label(topbar, text="Connected USB Drives",
                 bg=CARD, fg=TEXT, font=(FONT_FAMILY, 12, "bold"),
                 padx=20).pack(side="left", fill="y")
        self._count_label = tk.Label(topbar, text="",
                                     bg=CARD, fg=SUBTEXT,
                                     font=(FONT_FAMILY, 9))
        self._count_label.pack(side="left", fill="y")

        sep3 = tk.Frame(content, bg=BORDER, height=1)
        sep3.pack(fill="x")

        # Drive table
        table_frame = tk.Frame(content, bg=BG)
        table_frame.pack(fill="both", expand=True, padx=20, pady=16)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("DD.Treeview",
                        background=CARD, fieldbackground=CARD,
                        foreground=TEXT, rowheight=36,
                        font=(FONT_FAMILY, 10))
        style.configure("DD.Treeview.Heading",
                        background=PANEL, foreground=SUBTEXT,
                        font=(FONT_FAMILY, 9, "bold"),
                        relief="flat", borderwidth=0)
        style.map("DD.Treeview",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", TEXT)])

        cols = ("model", "serial", "size", "status")
        self._table = ttk.Treeview(table_frame, columns=cols,
                                   show="headings", style="DD.Treeview",
                                   selectmode="browse")
        self._table.heading("model",  text="Model",      anchor="w")
        self._table.heading("serial", text="Serial",     anchor="w")
        self._table.heading("size",   text="Size",       anchor="e")
        self._table.heading("status", text="Status",     anchor="w")
        self._table.column("model",  width=280, minwidth=160)
        self._table.column("serial", width=200, minwidth=120)
        self._table.column("size",   width=90,  minwidth=60, anchor="e")
        self._table.column("status", width=100, minwidth=80)

        tsb = ttk.Scrollbar(table_frame, command=self._table.yview)
        self._table.config(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self._table.pack(fill="both", expand=True)
        self._table.bind("<<TreeviewSelect>>", self._on_select)

        # Empty state label
        self._empty_label = tk.Label(table_frame,
                                     text="No USB drives detected.\nClick \"Scan for Drives\" to begin.",
                                     bg=BG, fg=SUBTEXT,
                                     font=(FONT_FAMILY, 11),
                                     justify="center")

        # ── Action panel (shown on selection) ────────────────────────────
        self._action_panel = tk.Frame(content, bg=PANEL, height=90)
        self._action_panel.pack(fill="x", side="bottom")
        self._action_panel.pack_propagate(False)

        ap_inner = tk.Frame(self._action_panel, bg=PANEL, padx=20)
        ap_inner.pack(fill="both", expand=True)

        # Disk info label
        self._disk_info_label = tk.Label(ap_inner, text="",
                                         bg=PANEL, fg=SUBTEXT,
                                         font=(FONT_FAMILY, 9),
                                         anchor="w")
        self._disk_info_label.pack(fill="x", pady=(10, 4))

        btn_row = tk.Frame(ap_inner, bg=PANEL)
        btn_row.pack(fill="x")

        self._open_btn = FlatButton(btn_row, "📂  Open",
                                    command=self._open_drive,
                                    bg=ACCENT2, pad_x=18, pad_y=9)
        self._open_btn.pack(side="left", padx=(0, 10))

        self._recover_btn = FlatButton(btn_row, "🔍  Recover",
                                       command=self._recover_drive,
                                       bg=SUCCESS, fg=BG, pad_x=18, pad_y=9)
        self._recover_btn.pack(side="left", padx=(0, 10))

        self._sanitize_btn = FlatButton(btn_row, "🧹  Complete Sanitize",
                                        command=self._sanitize_drive,
                                        bg=DANGER, pad_x=18, pad_y=9)
        self._sanitize_btn.pack(side="left")

        self._hide_action_panel()

        # Welcome state
        self._show_empty_state()

    # ── State helpers ─────────────────────────────────────────────────────

    def _show_empty_state(self):
        self._empty_label.place(relx=0.5, rely=0.4, anchor="center")

    def _hide_empty_state(self):
        self._empty_label.place_forget()

    def _show_action_panel(self):
        self._action_panel.pack(fill="x", side="bottom")

    def _hide_action_panel(self):
        self._action_panel.pack_forget()

    # ── Scan ──────────────────────────────────────────────────────────────

    def _start_scan(self):
        self._scan_btn.config(state="disabled")
        self._scan_spinner.start()
        self._hide_action_panel()
        self._selected_disk = None

        for row in self._table.get_children():
            self._table.delete(row)

        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            disks = detect_dir()
        except Exception as e:
            disks = []
            self.after(0, lambda: self._toast.show(f"Scan error: {e}", "error"))

        self.after(0, lambda: self._on_scan_done(disks))

    def _on_scan_done(self, disks: list):
        self._scan_spinner.stop()
        self._scan_btn.config(state="normal")
        self._disks = disks

        for row in self._table.get_children():
            self._table.delete(row)

        if not disks:
            self._count_label.config(text="")
            self._show_empty_state()
            self._toast.show("No USB drives found.", "warning")
            return

        self._hide_empty_state()
        self._count_label.config(text=f"  {len(disks)} drive{'s' if len(disks)!=1 else ''} found")

        for disk in disks:
            tag = "online" if "online" in str(disk.get("Status", "")).lower() else "offline"
            self._table.insert("", "end",
                               iid=str(disk["Disk#"]),
                               values=(
                                   disk.get("Model", "Unknown"),
                                   disk.get("Serial", "Unknown"),
                                   _fmt_size(disk.get("Size (GB)", 0)),
                                   disk.get("Status", "Unknown"),
                               ),
                               tags=(tag,))

        self._table.tag_configure("online",  foreground=TEXT)
        self._table.tag_configure("offline", foreground=SUBTEXT)
        self._toast.show(f"Found {len(disks)} USB drive(s).", "success")

    # ── Selection ─────────────────────────────────────────────────────────

    def _on_select(self, _=None):
        sel = self._table.selection()
        if not sel:
            self._hide_action_panel()
            return

        disk_num = int(sel[0])
        self._selected_disk = next((d for d in self._disks if d["Disk#"] == disk_num), None)
        if not self._selected_disk:
            return

        d = self._selected_disk
        info = (f"Disk {d['Disk#']}  ·  {d['Model']}  ·  "
                f"Serial: {d['Serial']}  ·  {_fmt_size(d.get('Size (GB)', 0))}  ·  {d.get('Status', '')}")
        self._disk_info_label.config(text=info)
        self._show_action_panel()

    # ── Open ──────────────────────────────────────────────────────────────

    def _open_drive(self):
        disk = self._selected_disk
        if not disk:
            return

        disk_number = disk.get("_number") or disk.get("Disk#")
        letter = _drive_letter_for_disk(disk_number)
        if not letter:
            self._toast.show("Could not find a drive letter for this disk.\n"
                             "It may not be partitioned or mounted.", "warning")
            return

        FileBrowserWindow(self, disk, letter, self._toast)

    # ── Recover ───────────────────────────────────────────────────────────

    def _recover_drive(self):
        disk = self._selected_disk
        if not disk:
            return

        dlg = RecoverySetupDialog(self, disk)
        self.wait_window(dlg)
        if not dlg.result:
            return

        file_types, output_dir = dlg.result

        q: queue.Queue = queue.Queue()
        pw = ProgressWindow(self,
                            f"Recovering from {disk.get('Model', 'USB Drive')}",
                            q)

        def run():
            _run_recovery_gui(disk, file_types, output_dir, q)

        threading.Thread(target=run, daemon=True).start()

    # ── Complete sanitize ─────────────────────────────────────────────────

    def _sanitize_drive(self):
        disk = self._selected_disk
        if not disk:
            return

        dlg = SanitizeConfirmDialog(self, disk)
        self.wait_window(dlg)
        if not dlg.result:
            self._toast.show("Sanitization cancelled.", "info")
            return

        q: queue.Queue = queue.Queue()
        pw = ProgressWindow(self,
                            f"Sanitizing {disk.get('Model', 'USB Drive')}",
                            q)

        def run():
            _run_complete_sanitize_gui(disk, q)

        threading.Thread(target=run, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = DrDigitalApp()
    app.mainloop()
