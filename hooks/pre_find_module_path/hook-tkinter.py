def pre_find_module_path(hook_api):
    # Override PyInstaller's default tkinter pre-find hook.
    # Some local Python builds report Tcl/Tk as unavailable during analysis,
    # which causes PyInstaller to exclude tkinter entirely.
    # We keep default search paths so tkinter modules are still bundled.
    return
