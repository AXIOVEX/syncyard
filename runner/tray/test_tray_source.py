#!/usr/bin/env python3
"""Static battery for the Syncyard tray source (spec 007).

Guards the 2026-11-01 field crash: the tray re-rendered its icon on
every 5 s supervision tick and leaked the bitmap and the icon handle
each render (an undisposed Bitmap, plus an Icon.FromHandle whose
Dispose releases nothing). Roughly 7,500 ticks exhausted the
per-process GDI quota, and the tray died with a System.Drawing
OutOfMemoryException while constructing its own error dialog.

These are source-shape checks (CI has no .NET Framework compiler):
they fail if the leak patterns or the missing exception guards ever
come back.
"""
import pathlib
import re
import sys

SRC = pathlib.Path(__file__).with_name("SyncyardTray.cs").read_text(
    encoding="utf-8")


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    return ok


def seticon_body():
    m = re.search(r"private void SetIcon\(int state\)\n(.*?)\n        \}\n",
                  SRC, re.S)
    return m.group(1) if m else ""


def main():
    body = seticon_body()
    results = [
        check("SetIcon exists", bool(body)),
        # The icon renders only when the state actually changes.
        check("SetIcon caches by state",
              "if (state == _iconState && _currentIcon != null) return;"
              in body),
        # The rendered bitmap is released.
        check("SetIcon disposes the bitmap", "bmp.Dispose();" in body),
        # The borrowed HICON is destroyed, not leaked through
        # Icon.FromHandle (whose Dispose is a no-op for the handle).
        check("SetIcon destroys the borrowed HICON",
              "DestroyIcon(hIcon);" in body),
        check("SetIcon clones the icon",
              "(Icon)borrowed.Clone();" in body),
        check("no bare FromHandle assignment remains",
              "_currentIcon = Icon.FromHandle(" not in SRC),
        # The per-tick menu rebuild disposes the previous menu.
        check("RebuildMenu disposes the previous menu",
              "oldMenu.Dispose();" in SRC),
        # Supervision ticks are guarded: log, never the modal dialog.
        check("OnTick guards TickCore",
              "try { TickCore(); }" in SRC
              and "tick error (caught)" in SRC),
        # The UI thread exception mode is catch-and-log, set in Main.
        check("Main sets CatchException mode",
              "UnhandledExceptionMode.CatchException" in SRC
              and "Application.ThreadException +=" in SRC),
    ]
    print("TRAY_SOURCE %s" % ("OK" if all(results) else "FAILURES"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
