"""
Small UI helpers for CubePet popups.

Currently contains the Credits popup (requested to show Discord names).
"""

from __future__ import annotations

import tkinter as tk


CREDITS_BODY = "Assets: lausertake\nCode: Stone441"


def _clamp_popup_xy(
    *,
    px: int,
    py: int,
    win_w: int,
    win_h: int,
    screen_w: int,
    screen_h: int,
) -> tuple[int, int]:
    max_x = max(0, int(screen_w) - int(win_w))
    max_y = max(0, int(screen_h) - int(win_h))
    px = max(0, min(int(px), max_x))
    py = max(0, min(int(py), max_y))
    return (px, py)


def show_credits_popup(
    root: tk.Misc,
    *,
    anchor_x: int,
    anchor_y: int,
    screen_w: int,
    screen_h: int,
) -> tk.Toplevel:
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg="#fff7ed")

    frame = tk.Frame(win, bg="#fff7ed", bd=2, relief="solid")
    frame.pack(fill="both", expand=True)

    title = tk.Label(
        frame,
        text="Credits",
        bg="#fff7ed",
        fg="#7c2d12",
        font=("Segoe UI", 10, "bold"),
        padx=10,
        pady=6,
    )
    title.pack()

    body = tk.Label(
        frame,
        text=CREDITS_BODY,
        bg="#fff7ed",
        fg="#111827",
        font=("Consolas", 10),
        justify="left",
        padx=10,
        pady=4,
    )
    body.pack()

    btn = tk.Button(
        frame,
        text="OK",
        width=8,
        command=win.destroy,
        bg="#ffffff",
        fg="#111111",
        relief="flat",
    )
    btn.pack(pady=(0, 8))

    win.update_idletasks()
    px, py = _clamp_popup_xy(
        px=anchor_x,
        py=anchor_y,
        win_w=win.winfo_width(),
        win_h=win.winfo_height(),
        screen_w=screen_w,
        screen_h=screen_h,
    )
    win.geometry(f"+{px}+{py}")
    return win

