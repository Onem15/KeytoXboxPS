"""KeytoXboxPS with a clean bindings-only UI."""

from __future__ import annotations

import ctypes
import json
import logging
import os
from queue import Empty, Queue
import sys
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable, Dict, Optional

import ttkbootstrap as ttk

from input_handler import InputHandler
from joystick_mapper import VirtualJoystickMapper

CONTROLLER_PROFILES: Dict[str, Dict[int, str]] = {
    "xbox": {
        1: "A",
        2: "B",
        3: "X",
        4: "Y",
        5: "LB",
        6: "RB",
        7: "Back/View",
        8: "Start/Menu",
        9: "L3",
        10: "R3",
        11: "Guide",
        12: "D-Pad Up",
        13: "D-Pad Down",
        14: "D-Pad Left",
        15: "D-Pad Right",
        16: "Share/Capture",
    },
    "playstation": {
        1: "Cross",
        2: "Circle",
        3: "Square",
        4: "Triangle",
        5: "L1",
        6: "R1",
        7: "Share",
        8: "Options",
        9: "L3",
        10: "R3",
        11: "PS",
        12: "D-Pad Up",
        13: "D-Pad Down",
        14: "D-Pad Left",
        15: "D-Pad Right",
        16: "Touchpad",
    },
    "generic": {},
}

PROFILE_LABELS = {
    "xbox": "Xbox",
    "playstation": "PlayStation",
    "generic": "Generic",
}

MODE_OPTIONS = {
    "Axis Negative (-)": "axis_negative",
    "Axis Positive (+)": "axis_positive",
    "Button": "button",
}

UI_THEME_OPTIONS = {
    "Light": "light",
    "Dark": "dark",
}

LIGHT_THEME_NAME = "flatly"
DARK_THEME_NAME = "darkly"
DARK_THEME_ACCENT = "#36B7BA"
APP_NAME = "KeytoXboxPS"
APP_VERSION = "1.0.2"
APP_USER_MODEL_ID = "KeytoXboxPS.App"

DEFAULT_CONFIG: Dict[str, Any] = {
    "backend": "xinput",
    "vjoy_device_id": 1,
    "auto_select_device": True,
    "button_count": 16,
    "controller_profile": "xbox",
    "ui_theme": "light",
    "bindings": {
        "axes": {
            "left_stick_x": {"negative": [], "positive": []},
            "left_stick_y": {"negative": [], "positive": []},
            "right_stick_x": {"negative": [], "positive": []},
            "right_stick_y": {"negative": [], "positive": []},
            "left_trigger": {"negative": [], "positive": []},
            "right_trigger": {"negative": [], "positive": []},
            "slider_0": {"negative": [], "positive": []},
            "slider_1": {"negative": [], "positive": []},
            "wheel": {"negative": [], "positive": []},
        },
        "buttons": {},
    },
}


class SingleInstanceLock:
    """Windows named mutex guard that allows only one running app instance."""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str = "Global\\KeytoXboxPSMutex") -> None:
        self.name = name
        self._handle: Optional[int] = None

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            return False
        err = kernel32.GetLastError()
        if err == self.ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = int(handle)
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        ctypes.windll.kernel32.CloseHandle(self._handle)
        self._handle = None


class ConfigLoader:
    """Loads, migrates, and persists configuration."""

    @staticmethod
    def load(path: Path) -> Dict[str, Any]:
        if not path.exists():
            config = deepcopy(DEFAULT_CONFIG)
            ConfigLoader.save(path, config)
            return config

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON in {path.name}: {exc}") from exc

        merged = deepcopy(DEFAULT_CONFIG)
        ConfigLoader._deep_merge(merged, raw)
        merged["bindings"] = ConfigLoader._normalize_bindings(merged.get("bindings", {}))
        merged["button_count"] = min(max(int(merged.get("button_count", 16)), 1), 128)
        merged["controller_profile"] = ConfigLoader._normalize_profile(
            str(merged.get("controller_profile", "xbox"))
        )
        merged["ui_theme"] = ConfigLoader._normalize_ui_theme(str(merged.get("ui_theme", "light")))
        return merged

    @staticmethod
    def save(path: Path, config: Dict[str, Any]) -> None:
        data = deepcopy(config)
        data["bindings"] = ConfigLoader._normalize_bindings(data.get("bindings", {}))
        data["controller_profile"] = ConfigLoader._normalize_profile(
            str(data.get("controller_profile", "xbox"))
        )
        data["ui_theme"] = ConfigLoader._normalize_ui_theme(str(data.get("ui_theme", "light")))
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                ConfigLoader._deep_merge(base[key], value)
            else:
                base[key] = value

    @staticmethod
    def _normalize_profile(raw: str) -> str:
        profile = raw.strip().lower()
        return profile if profile in CONTROLLER_PROFILES else "xbox"

    @staticmethod
    def _normalize_ui_theme(raw: str) -> str:
        theme = raw.strip().lower()
        return theme if theme in ("light", "dark") else "light"

    @staticmethod
    def _normalize_bindings(raw: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            return deepcopy(DEFAULT_CONFIG["bindings"])

        if "axes" in raw:
            axes = raw.get("axes", {})
            buttons = raw.get("buttons", {})
            if not isinstance(axes, dict):
                axes = {}
            if not isinstance(buttons, dict):
                buttons = {}
        else:
            axes = {}
            for axis_name in DEFAULT_CONFIG["bindings"]["axes"]:
                axis_data = raw.get(axis_name)
                if isinstance(axis_data, dict):
                    axes[axis_name] = axis_data

            buttons = {}
            legacy_buttons = raw.get("buttons", {})
            if isinstance(legacy_buttons, dict):
                for _, entry in legacy_buttons.items():
                    if not isinstance(entry, dict):
                        continue
                    button_id = str(int(entry.get("vjoy_button", 1)))
                    keys = entry.get("keys", [])
                    if not isinstance(keys, list):
                        continue
                    buttons.setdefault(button_id, [])
                    for key in keys:
                        token = str(key).strip().lower()
                        if token and token not in buttons[button_id]:
                            buttons[button_id].append(token)

        for axis_name, axis_default in DEFAULT_CONFIG["bindings"]["axes"].items():
            axes.setdefault(axis_name, deepcopy(axis_default))

        return {"axes": axes, "buttons": buttons}


class Dashboard:
    """Bindings-focused UI."""

    REFRESH_MS = 40
    AXIS_LABELS = {
        "left_stick_x": "Left Stick X",
        "left_stick_y": "Left Stick Y",
        "right_stick_x": "Right Stick X",
        "right_stick_y": "Right Stick Y",
        "left_trigger": "Left Trigger",
        "right_trigger": "Right Trigger",
        "slider_0": "Slider 0",
        "slider_1": "Slider 1",
        "wheel": "Wheel",
    }

    TOKEN_LABELS = {
        "mouse_left": "Mouse Left",
        "mouse_right": "Mouse Right",
        "mouse_middle": "Mouse Middle",
        "mouse_x1": "Mouse X1",
        "mouse_x2": "Mouse X2",
        "mouse_wheel_up": "Mouse Wheel Up",
        "mouse_wheel_down": "Mouse Wheel Down",
        "shift_l": "Left Shift",
        "shift_r": "Right Shift",
        "ctrl_l": "Left Ctrl",
        "ctrl_r": "Right Ctrl",
        "alt_l": "Left Alt",
        "alt_r": "Right Alt",
        "esc": "Escape",
        "enter": "Enter",
        "space": "Space",
        "up": "Arrow Up",
        "down": "Arrow Down",
        "left": "Arrow Left",
        "right": "Arrow Right",
    }

    def __init__(
        self,
        root: tk.Tk,
        mapper: VirtualJoystickMapper,
        controller_profile: str,
        ui_theme: str,
        get_captured_input: Callable[[], Optional[str]],
        save_bindings: Callable[[Dict[str, Any]], tuple[bool, str]],
        set_profile: Callable[[str], tuple[bool, str]],
        set_ui_theme: Callable[[str], tuple[bool, str]],
        clear_all_bindings: Callable[[], tuple[bool, str]],
        set_output_enabled: Callable[[bool], tuple[bool, str]],
        is_output_enabled: Callable[[], bool],
        on_close: Callable[[], None],
    ) -> None:
        self.root = root
        self.mapper = mapper
        self.get_captured_input = get_captured_input
        self.save_bindings = save_bindings
        self.set_profile = set_profile
        self.set_ui_theme = set_ui_theme
        self.clear_all_bindings = clear_all_bindings
        self.set_output_enabled = set_output_enabled
        self.is_output_enabled = is_output_enabled
        self.on_close = on_close

        self.header_label: ttk.Label | None = None

        self._ui_theme = ConfigLoader._normalize_ui_theme(ui_theme)
        self.theme_display = tk.StringVar(value=self._ui_theme_display(self._ui_theme))
        self.controller_profile = tk.StringVar(value=controller_profile)
        self.target_mode_display = tk.StringVar(value="Button")
        self.axis_target_display = tk.StringVar(value="")
        self.button_target_display = tk.StringVar(value="")
        self.manual_input = tk.StringVar(value="")
        self.capture_active = False

        self.binding_listbox: tk.Listbox | None = None
        self.axis_combo: ttk.Combobox | None = None
        self.button_combo: ttk.Combobox | None = None
        self.theme_combo: ttk.Combobox | None = None
        self.capture_button: ttk.Button | None = None
        self.output_toggle_button: ttk.Button | None = None

        self._button_entry_to_id: Dict[str, int] = {}
        self._axis_entry_to_key: Dict[str, str] = {}
        self._current_raw_tokens: list[str] = []

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close)
        self._refresh()

    def _build(self) -> None:
        self.root.title("KeytoXboxPS")
        self.root.geometry("820x560")
        self.root.minsize(820, 560)

        style = ttk.Style()
        style.configure(".", font=("Segoe UI", 11))

        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="KeytoXboxPS", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        self.header_label = ttk.Label(main, text="", font=("Segoe UI", 11))
        self.header_label.pack(anchor="w", pady=(2, 10))
        self._refresh_header()

        self._build_bindings_panel(main)
        self._apply_ui_theme(self._ui_theme)

    def _build_bindings_panel(self, parent: ttk.Frame) -> None:
        controls = ttk.LabelFrame(parent, text="Bindings")
        controls.pack(fill="x", pady=(0, 10))

        ttk.Label(controls, text="Controller Profile:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        profile_combo = ttk.Combobox(
            controls,
            state="readonly",
            width=14,
            textvariable=self.controller_profile,
            values=list(PROFILE_LABELS.keys()),
        )
        profile_combo.grid(row=0, column=1, sticky="w", padx=(0, 14), pady=4)
        profile_combo.bind("<<ComboboxSelected>>", self._on_profile_changed)

        ttk.Label(controls, text="Bind To:").grid(row=0, column=2, sticky="w", padx=(0, 8), pady=4)
        mode_combo = ttk.Combobox(
            controls,
            state="readonly",
            width=16,
            textvariable=self.target_mode_display,
            values=list(MODE_OPTIONS.keys()),
        )
        mode_combo.grid(row=0, column=3, sticky="w", padx=(0, 14), pady=4)
        mode_combo.bind("<<ComboboxSelected>>", self._on_target_changed)

        ttk.Label(controls, text="Theme:").grid(row=0, column=4, sticky="w", padx=(0, 8), pady=4)
        self.theme_combo = ttk.Combobox(
            controls,
            state="readonly",
            width=10,
            textvariable=self.theme_display,
            values=list(UI_THEME_OPTIONS.keys()),
        )
        self.theme_combo.grid(row=0, column=5, sticky="w", padx=(0, 14), pady=4)
        self.theme_combo.bind("<<ComboboxSelected>>", self._on_theme_changed)

        controls.columnconfigure(6, weight=1)
        self.output_toggle_button = ttk.Button(
            controls,
            command=self._toggle_output,
            width=18,
        )
        self.output_toggle_button.grid(row=0, column=6, sticky="e", padx=(10, 0), pady=4)

        ttk.Label(controls, text="Axis:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.axis_combo = ttk.Combobox(
            controls,
            state="readonly",
            width=24,
            textvariable=self.axis_target_display,
            values=[],
        )
        self.axis_combo.grid(row=1, column=1, sticky="w", padx=(0, 14), pady=4)
        self.axis_combo.bind("<<ComboboxSelected>>", self._on_target_changed)

        ttk.Label(controls, text="Button:").grid(row=1, column=2, sticky="w", padx=(0, 8), pady=4)
        self.button_combo = ttk.Combobox(
            controls,
            state="readonly",
            width=24,
            textvariable=self.button_target_display,
            values=[],
        )
        self.button_combo.grid(row=1, column=3, sticky="w", padx=(0, 14), pady=4)
        self.button_combo.bind("<<ComboboxSelected>>", self._on_target_changed)

        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        list_frame = ttk.LabelFrame(body, text="Current Mapped Inputs")
        list_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.binding_listbox = tk.Listbox(
            list_frame,
            height=10,
            exportselection=False,
            font=("Segoe UI", 12),
            bg="#ffffff",
            fg="#111111",
            selectbackground="#d8ecff",
        )
        self.binding_listbox.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.binding_listbox.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.binding_listbox.configure(yscrollcommand=scroll.set)

        actions = ttk.Frame(body)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.capture_button = ttk.Button(
            actions,
            text="Capture Next Input",
            command=self._start_capture,
            width=18,
            bootstyle="primary",
        )
        self.capture_button.grid(row=0, column=0, padx=(0, 8), pady=3, sticky="w")

        ttk.Button(actions, text="Remove Selected", command=self._remove_selected_binding, width=18, bootstyle="secondary").grid(row=0, column=1, padx=(0, 8), pady=3, sticky="w")
        ttk.Button(actions, text="Clear Target", command=self._clear_target, width=14, bootstyle="danger").grid(row=0, column=2, padx=(0, 8), pady=3, sticky="w")
        ttk.Button(actions, text="Save", command=self._persist_bindings, width=8, bootstyle="success").grid(row=0, column=3, padx=(0, 8), pady=3, sticky="w")
        ttk.Button(actions, text="Clear All", command=self._clear_all_bindings, width=10, bootstyle="danger").grid(row=0, column=4, padx=(0, 8), pady=3, sticky="w")

        ttk.Label(actions, text="Manual Input Token:").grid(row=1, column=0, sticky="w", pady=4)
        entry = ttk.Entry(actions, textvariable=self.manual_input, width=28)
        entry.grid(row=1, column=1, sticky="w", padx=(0, 8), pady=4)
        entry.bind("<Return>", lambda _e: self._add_manual_binding())
        ttk.Button(actions, text="Add", command=self._add_manual_binding, width=8, bootstyle="secondary").grid(row=1, column=2, sticky="w", pady=4)

        help_text = (
            "Examples: Mouse Middle, Mouse Left, Left Shift, W, Enter. "
            "To map L3: set Profile to PlayStation, Bind To to Button, select L3, then click Capture Next Input."
        )
        ttk.Label(body, text=help_text, wraplength=780).grid(row=2, column=0, sticky="w")

        self._rebuild_axis_target_entries()
        self._rebuild_button_target_entries()
        self._refresh_output_toggle_button()
        self._on_target_changed()

    def _pretty_token(self, token: str) -> str:
        token = token.strip().lower()
        if token in self.TOKEN_LABELS:
            return self.TOKEN_LABELS[token]
        if token.startswith("vk_"):
            return f"VK {token[3:]}"
        return token.replace("_", " ").title()

    def _refresh(self) -> None:
        self._process_capture_queue()
        if self.root.winfo_exists():
            self.root.after(self.REFRESH_MS, self._refresh)

    def _refresh_header(self) -> None:
        if self.header_label is None:
            return
        profile_key = self.controller_profile.get().strip().lower()
        profile_text = PROFILE_LABELS.get(profile_key, "Xbox")
        output_text = "Enabled" if self.is_output_enabled() else "Disabled"
        theme_text = self._ui_theme_display(self._ui_theme)
        self.header_label.configure(
            text=(
                f"Backend: {self.mapper.backend.upper()}  |  Profile: {profile_text}  |  "
                f"Theme: {theme_text}  |  Output: {output_text}  |  {self.mapper.device_label}"
            )
        )

    def _ui_theme_display(self, theme: str) -> str:
        normalized = ConfigLoader._normalize_ui_theme(theme)
        return "Dark" if normalized == "dark" else "Light"

    def _display_to_ui_theme(self, display: str) -> str:
        return UI_THEME_OPTIONS.get(display.strip(), "light")

    def _on_theme_changed(self, _event: Any = None) -> None:
        selected = self._display_to_ui_theme(self.theme_display.get())
        self._apply_ui_theme(selected)
        ok, msg = self.set_ui_theme(selected)
        if not ok:
            messagebox.showerror("KeytoXboxPS", f"Theme update failed:\n\n{msg}")

    def _apply_ui_theme(self, theme: str) -> None:
        normalized = ConfigLoader._normalize_ui_theme(theme)
        style = ttk.Style()
        try:
            style.theme_use(DARK_THEME_NAME if normalized == "dark" else LIGHT_THEME_NAME)
            if normalized == "dark":
                style.colors.set("primary", DARK_THEME_ACCENT)
                style.colors.set("info", DARK_THEME_ACCENT)
        except Exception:
            pass

        self._ui_theme = normalized
        self.theme_display.set(self._ui_theme_display(normalized))
        self._apply_listbox_theme(normalized)
        self._refresh_header()
        self._refresh_output_toggle_button()

    def _apply_listbox_theme(self, theme: str) -> None:
        if self.binding_listbox is None:
            return
        if theme == "dark":
            self.binding_listbox.configure(
                bg="#1B1F24",
                fg="#E9F2F3",
                selectbackground=DARK_THEME_ACCENT,
                selectforeground="#0F1A1B",
            )
            return
        self.binding_listbox.configure(
            bg="#FFFFFF",
            fg="#111111",
            selectbackground="#D8ECFF",
            selectforeground="#111111",
        )

    def _refresh_output_toggle_button(self) -> None:
        if self.output_toggle_button is None:
            return
        enabled = self.is_output_enabled()
        if enabled:
            self.output_toggle_button.configure(
                text="Disable Output",
                bootstyle="danger",
            )
        else:
            self.output_toggle_button.configure(
                text="Enable Output",
                bootstyle="success",
            )

    def _toggle_output(self) -> None:
        target_state = not self.is_output_enabled()
        ok, msg = self.set_output_enabled(target_state)
        if not ok:
            messagebox.showerror("KeytoXboxPS", f"Could not change output state:\n\n{msg}")
            return
        self._refresh_output_toggle_button()
        self._refresh_header()

    def _button_label_for_id(self, button_id: int) -> str:
        profile_key = self.controller_profile.get().strip().lower()
        profile = CONTROLLER_PROFILES.get(profile_key, {})
        if button_id in profile:
            return profile[button_id]
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        idx = button_id - 1
        if 0 <= idx < len(letters):
            return f"Button {letters[idx]}"
        return f"Button {button_id}"

    def _axis_label_for_key(self, axis_key: str) -> str:
        return self.AXIS_LABELS.get(axis_key, axis_key.replace("_", " ").title())

    def _rebuild_axis_target_entries(self) -> None:
        self._axis_entry_to_key.clear()
        entries: list[str] = []
        for axis_key in self.mapper.get_axis_names():
            entry = self._axis_label_for_key(axis_key)
            entries.append(entry)
            self._axis_entry_to_key[entry] = axis_key
        if self.axis_combo is not None:
            self.axis_combo.configure(values=entries)
        if entries and self.axis_target_display.get() not in self._axis_entry_to_key:
            self.axis_target_display.set(entries[0])

    def _rebuild_button_target_entries(self) -> None:
        current_id = self._get_button_target_id(default=1)
        self._button_entry_to_id.clear()

        entries: list[str] = []
        for button_id in range(1, self.mapper.get_button_count() + 1):
            base = self._button_label_for_id(button_id)
            entry = base
            suffix = 2
            while entry in self._button_entry_to_id:
                entry = f"{base} ({suffix})"
                suffix += 1
            entries.append(entry)
            self._button_entry_to_id[entry] = button_id

        if self.button_combo is not None:
            self.button_combo.configure(values=entries)

        target_entry = None
        for text, button_id in self._button_entry_to_id.items():
            if button_id == current_id:
                target_entry = text
                break
        if target_entry is None and entries:
            target_entry = entries[0]
        if target_entry is not None:
            self.button_target_display.set(target_entry)

    def _current_mode(self) -> str:
        return MODE_OPTIONS.get(self.target_mode_display.get().strip(), "button")

    def _on_target_changed(self, _event: Any = None) -> None:
        mode = self._current_mode()

        if self.axis_combo is not None:
            self.axis_combo.configure(state="readonly" if mode.startswith("axis_") else "disabled")
        if self.button_combo is not None:
            self.button_combo.configure(state="readonly" if mode == "button" else "disabled")

        self.capture_active = False
        self._set_capture_button_text()
        self._refresh_target_binding_list()

    def _on_profile_changed(self, _event: Any = None) -> None:
        profile = self.controller_profile.get().strip().lower()
        ok, msg = self.set_profile(profile)
        if not ok:
            messagebox.showerror("KeytoXboxPS", f"Profile change failed:\n\n{msg}")
            return

        self._rebuild_button_target_entries()
        self._refresh_header()
        self._refresh_target_binding_list()

    def _set_capture_button_text(self) -> None:
        if self.capture_button is not None:
            self.capture_button.configure(text="Waiting..." if self.capture_active else "Capture Next Input")

    def _start_capture(self) -> None:
        self.capture_active = True
        self._set_capture_button_text()
        while self.get_captured_input() is not None:
            pass

    def _process_capture_queue(self) -> None:
        while True:
            token = self.get_captured_input()
            if token is None:
                break
            if not self.capture_active:
                continue
            added = self._add_binding_to_selected_target(token)
            if not added:
                messagebox.showwarning("KeytoXboxPS", "Input was captured but could not be added to this target.")
            self.capture_active = False
            self._set_capture_button_text()
            break

    def _add_manual_binding(self) -> None:
        token = self.manual_input.get().strip().lower()
        if not token:
            messagebox.showwarning("KeytoXboxPS", "Manual input token is empty.")
            return
        changed = self._add_binding_to_selected_target(token)
        if not changed:
            pretty = self._pretty_token(token)
            messagebox.showwarning("KeytoXboxPS", f"Could not add '{pretty}'.")
        if changed:
            self.manual_input.set("")

    def _get_axis_target_key(self) -> Optional[str]:
        entry = self.axis_target_display.get().strip()
        return self._axis_entry_to_key.get(entry)

    def _add_binding_to_selected_target(self, token: str) -> bool:
        mode = self._current_mode()
        if mode == "button":
            button_id = self._get_button_target_id()
            if button_id is None:
                return False
            changed = self.mapper.add_button_binding(button_id, token)
        elif mode == "axis_negative":
            axis_key = self._get_axis_target_key()
            if axis_key is None:
                return False
            changed = self.mapper.add_axis_binding(axis_key, "negative", token)
        elif mode == "axis_positive":
            axis_key = self._get_axis_target_key()
            if axis_key is None:
                return False
            changed = self.mapper.add_axis_binding(axis_key, "positive", token)
        else:
            return False

        if changed:
            self._refresh_target_binding_list()
            self._persist_bindings()
        return changed

    def _remove_selected_binding(self) -> None:
        if self.binding_listbox is None:
            return
        selection = self.binding_listbox.curselection()
        if not selection:
            messagebox.showwarning("KeytoXboxPS", "Select an input first.")
            return
        idx = int(selection[0])
        if idx < 0 or idx >= len(self._current_raw_tokens):
            return
        raw_token = self._current_raw_tokens[idx]
        mode = self._current_mode()

        if mode == "button":
            button_id = self._get_button_target_id()
            if button_id is None:
                messagebox.showerror("KeytoXboxPS", "Invalid button target.")
                return
            changed = self.mapper.remove_button_binding(button_id, raw_token)
        elif mode == "axis_negative":
            axis_key = self._get_axis_target_key()
            if axis_key is None:
                messagebox.showerror("KeytoXboxPS", "Invalid axis target.")
                return
            changed = self.mapper.remove_axis_binding(axis_key, "negative", raw_token)
        elif mode == "axis_positive":
            axis_key = self._get_axis_target_key()
            if axis_key is None:
                messagebox.showerror("KeytoXboxPS", "Invalid axis target.")
                return
            changed = self.mapper.remove_axis_binding(axis_key, "positive", raw_token)
        else:
            changed = False

        if not changed:
            pretty = self._pretty_token(raw_token)
            messagebox.showwarning("KeytoXboxPS", f"Could not remove '{pretty}'.")
        if changed:
            self._refresh_target_binding_list()
            self._persist_bindings()

    def _clear_target(self) -> None:
        mode = self._current_mode()
        if mode == "button":
            button_id = self._get_button_target_id()
            if button_id is None:
                messagebox.showerror("KeytoXboxPS", "Invalid button target.")
                return
            changed = self.mapper.clear_button_target(button_id)
        elif mode == "axis_negative":
            axis_key = self._get_axis_target_key()
            if axis_key is None:
                messagebox.showerror("KeytoXboxPS", "Invalid axis target.")
                return
            changed = self.mapper.clear_axis_target(axis_key, "negative")
        elif mode == "axis_positive":
            axis_key = self._get_axis_target_key()
            if axis_key is None:
                messagebox.showerror("KeytoXboxPS", "Invalid axis target.")
                return
            changed = self.mapper.clear_axis_target(axis_key, "positive")
        else:
            changed = False

        if not changed:
            messagebox.showinfo("KeytoXboxPS", "Target is already empty.")
        if changed:
            self._refresh_target_binding_list()
            self._persist_bindings()

    def _refresh_target_binding_list(self) -> None:
        if self.binding_listbox is None:
            return

        self.binding_listbox.delete(0, tk.END)
        self._current_raw_tokens = []

        bindings = self.mapper.export_bindings_config()
        mode = self._current_mode()

        tokens: list[str] = []
        if mode == "button":
            button_id = self._get_button_target_id()
            if button_id is not None:
                tokens = bindings.get("buttons", {}).get(str(button_id), [])
        else:
            axis_key = self._get_axis_target_key()
            if axis_key is not None:
                axis_data = bindings.get("axes", {}).get(axis_key, {})
                direction = "negative" if mode == "axis_negative" else "positive"
                tokens = axis_data.get(direction, [])

        self._current_raw_tokens = list(tokens)
        for token in tokens:
            self.binding_listbox.insert(tk.END, self._pretty_token(token))

    def _persist_bindings(self) -> None:
        ok, msg = self.save_bindings(self.mapper.export_bindings_config())
        if not ok:
            messagebox.showerror("KeytoXboxPS", f"Save failed:\n\n{msg}")

    def _clear_all_bindings(self) -> None:
        ok, msg = self.clear_all_bindings()
        if ok:
            self._refresh_target_binding_list()
        else:
            messagebox.showerror("KeytoXboxPS", f"Clear all failed:\n\n{msg}")

    def _get_button_target_id(self, default: Optional[int] = None) -> Optional[int]:
        text = self.button_target_display.get().strip()
        if text in self._button_entry_to_id:
            return self._button_entry_to_id[text]
        return default

    def _handle_close(self) -> None:
        self.on_close()
        if self.root.winfo_exists():
            self.root.destroy()


class KeytoXboxPSApp:
    """Coordinates config, mapper, input capture, and dashboard lifecycle."""

    def __init__(self, config_path: Path, assets_dir: Path) -> None:
        self.config_path = config_path
        self.assets_dir = assets_dir
        self.config: Dict[str, Any] = {}
        self.mapper: VirtualJoystickMapper | None = None
        self.input_handler: InputHandler | None = None
        self._window_icon: tk.PhotoImage | None = None
        self._output_enabled = True
        self._shutdown_called = False
        self._captured_input_queue: Queue[str] = Queue()
        self._instance_lock = SingleInstanceLock()

    def run(self) -> int:
        if not self._instance_lock.acquire():
            self._show_error("Another KeytoXboxPS instance is already running.\n\nClose it before starting a new one.")
            return 1

        try:
            self.config = ConfigLoader.load(self.config_path)
            self.mapper = VirtualJoystickMapper(self.config)
            self.mapper.connect()
            self.mapper.set_bindings(self.config.get("bindings", {}), apply_immediately=True)
            self._output_enabled = True

            self.input_handler = InputHandler(
                on_input_event=self._on_input_event,
                on_input_detected=self._on_input_detected,
            )
            self.input_handler.start()
        except Exception as exc:
            self._show_error(f"Initialization failed.\n\n{exc}")
            return 1

        theme_name = DARK_THEME_NAME if self.config.get("ui_theme") == "dark" else LIGHT_THEME_NAME
        # Helps Windows use our app-specific icon in taskbar/titlebar reliably.
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
        root = ttk.Window(themename=theme_name)
        self._apply_window_icon(root)
        root.after(300, lambda: self._apply_window_icon(root))
        Dashboard(
            root=root,
            mapper=self.mapper,
            controller_profile=self.config.get("controller_profile", "xbox"),
            ui_theme=str(self.config.get("ui_theme", "light")),
            get_captured_input=self._pop_captured_input,
            save_bindings=self._save_bindings,
            set_profile=self._set_profile,
            set_ui_theme=self._set_ui_theme,
            clear_all_bindings=self._clear_all_bindings,
            set_output_enabled=self._set_output_enabled,
            is_output_enabled=self._is_output_enabled,
            on_close=self.shutdown,
        )
        root.after(200, self._post_start_sync)
        root.mainloop()
        return 0

    def _post_start_sync(self) -> None:
        """
        One-time startup re-sync.
        Ensures bindings and input state are fully active even on systems where
        low-level hook startup lags behind window creation.
        """
        try:
            if self.input_handler is not None:
                self.input_handler.reset_state()
            if self.mapper is not None and self._output_enabled:
                self.mapper.reset_outputs()
                self.mapper.set_bindings(self.config.get("bindings", {}), apply_immediately=True)
        except Exception:
            pass

    def _on_input_event(self, input_token: str, is_pressed: bool) -> None:
        if not self._output_enabled or self.mapper is None:
            return
        self.mapper.handle_input_event(input_token, is_pressed)

    def _on_input_detected(self, input_token: str) -> None:
        self._captured_input_queue.put(input_token)

    def _pop_captured_input(self) -> Optional[str]:
        try:
            return self._captured_input_queue.get_nowait()
        except Empty:
            return None

    def _save_bindings(self, bindings: Dict[str, Any]) -> tuple[bool, str]:
        try:
            self.config["bindings"] = bindings
            ConfigLoader.save(self.config_path, self.config)
            return True, "Bindings saved to config.json."
        except Exception as exc:
            return False, str(exc)

    def _set_ui_theme(self, theme: str) -> tuple[bool, str]:
        normalized = ConfigLoader._normalize_ui_theme(theme)
        try:
            self.config["ui_theme"] = normalized
            ConfigLoader.save(self.config_path, self.config)
            return True, f"Theme set to {normalized}."
        except Exception as exc:
            return False, str(exc)

    def _set_profile(self, profile: str) -> tuple[bool, str]:
        normalized = ConfigLoader._normalize_profile(profile)
        try:
            self.config["controller_profile"] = normalized
            ConfigLoader.save(self.config_path, self.config)
            return True, f"Controller profile set to {PROFILE_LABELS.get(normalized, normalized)}."
        except Exception as exc:
            return False, str(exc)

    def _apply_window_icon(self, root: tk.Tk) -> None:
        png_icon = self.assets_dir / "icon-KeytoXboxPS.png"
        ico_icon = self.assets_dir / "icon-KeytoXboxPS.ico"
        exe_icon = Path(sys.executable) if getattr(sys, "frozen", False) else None

        ico_candidates = []
        if exe_icon is not None and exe_icon.exists():
            ico_candidates.append(exe_icon)
        if ico_icon.exists():
            ico_candidates.append(ico_icon)

        for candidate in ico_candidates:
            try:
                root.iconbitmap(str(candidate))
                break
            except Exception:
                try:
                    root.iconbitmap(default=str(candidate))
                    break
                except Exception:
                    continue

        if png_icon.exists():
            try:
                icon_image = tk.PhotoImage(file=str(png_icon))
                root.iconphoto(True, icon_image)
                self._window_icon = icon_image
            except Exception:
                pass

    def _clear_all_bindings(self) -> tuple[bool, str]:
        try:
            empty_bindings = {"axes": {}, "buttons": {}}
            if self.mapper is not None:
                self.mapper.set_bindings(empty_bindings, apply_immediately=True)
            self.config["bindings"] = empty_bindings
            ConfigLoader.save(self.config_path, self.config)
            return True, "All bindings cleared and saved."
        except Exception as exc:
            return False, str(exc)

    def _is_output_enabled(self) -> bool:
        return self._output_enabled

    def _set_output_enabled(self, enabled: bool) -> tuple[bool, str]:
        if self.mapper is None:
            return False, "Mapper is not initialized."

        target = bool(enabled)
        if target == self._output_enabled:
            return True, "No change."

        try:
            if target:
                self.mapper.connect()
                if self.input_handler is not None:
                    self.input_handler.reset_state()
                self.mapper.reset_outputs()
                # Apply whatever bindings are currently in memory.
                self.mapper.set_bindings(self.mapper.export_bindings_config(), apply_immediately=True)
                self._output_enabled = True
                return True, "Output enabled."

            if self.input_handler is not None:
                self.input_handler.reset_state()
            self.mapper.reset_outputs()
            self.mapper.disconnect()
            self._output_enabled = False
            return True, "Output disabled."
        except Exception as exc:
            return False, str(exc)

    def shutdown(self) -> None:
        if self._shutdown_called:
            return
        self._shutdown_called = True

        if self.mapper is not None:
            try:
                self.config["bindings"] = self.mapper.export_bindings_config()
                ConfigLoader.save(self.config_path, self.config)
            except Exception:
                pass

        if self.input_handler is not None:
            self.input_handler.stop()

        if self.mapper is not None:
            try:
                self.mapper.disconnect()
            except Exception:
                pass

        self._instance_lock.release()

    @staticmethod
    def _show_error(message: str) -> None:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("KeytoXboxPS", message)
            root.destroy()
        except Exception:
            print(message, file=sys.stderr)


def get_app_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME
    return Path.home() / "AppData" / "Local" / APP_NAME


def resolve_runtime_paths() -> tuple[Path, Path]:
    if getattr(sys, "frozen", False):
        config_dir = get_app_data_dir()
        resource_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        config_dir = Path(__file__).resolve().parent
        resource_dir = config_dir

    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir, resource_dir


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config_dir, resource_dir = resolve_runtime_paths()
    app = KeytoXboxPSApp(config_dir / "config.json", resource_dir / "assets")
    try:
        return app.run()
    finally:
        app.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
