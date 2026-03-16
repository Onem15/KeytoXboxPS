from __future__ import annotations

import os
import sys
from pathlib import Path


def _set_tk_paths() -> None:
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    tcl_library = root / "_tcl_data"
    tk_library = root / "_tk_data"
    if tcl_library.exists():
        os.environ.setdefault("TCL_LIBRARY", str(tcl_library))
    if tk_library.exists():
        os.environ.setdefault("TK_LIBRARY", str(tk_library))


_set_tk_paths()
