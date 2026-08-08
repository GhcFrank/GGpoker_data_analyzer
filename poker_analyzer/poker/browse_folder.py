"""Standalone folder picker process. Usage:

    python browse_folder.py <output_file> [initial_dir]

Writes the chosen path (UTF-8) to output_file, or empty string if cancelled.
Do not capture this process's stdout — GUI dialogs need a normal console.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: browse_folder.py <output_file> [initial_dir]", file=sys.stderr)
        return 2

    out_file = Path(sys.argv[1])
    initial = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else Path.home()
    if not initial.exists():
        initial = Path.home()
    elif initial.is_file():
        initial = initial.parent

    try:
        chosen = _pick_tk(initial)
    except Exception as exc:  # noqa: BLE001
        out_file.write_text(f"__ERROR__:{exc}", encoding="utf-8")
        return 1

    out_file.write_text(chosen, encoding="utf-8")
    return 0


def _pick_tk(initial: Path) -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.title("选择牌谱数据目录")
    root.withdraw()
    root.update_idletasks()
    try:
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
    except tk.TclError:
        pass

    path = filedialog.askdirectory(
        parent=root,
        title="选择牌谱数据目录",
        initialdir=str(initial),
        mustexist=True,
    )
    try:
        root.destroy()
    except tk.TclError:
        pass
    return path or ""


if __name__ == "__main__":
    raise SystemExit(main())
