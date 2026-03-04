"""Global input capture for keyboard + mouse."""

from __future__ import annotations

import threading
from typing import Callable, Dict, Optional, Set

from pynput import keyboard, mouse


class InputHandler:
    """Captures keyboard and mouse events and emits normalized input tokens."""

    _KEY_ALIASES = {
        "return": "enter",
        "escape": "esc",
    }
    _VK_ALIASES = {
        # A-Z
        **{i: chr(i + 32) for i in range(65, 91)},
        # 0-9
        **{i: chr(i) for i in range(48, 58)},
        # Common keys
        13: "enter",
        27: "esc",
        32: "space",
        37: "left",
        38: "up",
        39: "right",
        40: "down",
    }

    _MOUSE_BUTTON_ALIASES = {
        "button.left": "mouse_left",
        "button.right": "mouse_right",
        "button.middle": "mouse_middle",
        "button.x1": "mouse_x1",
        "button.x2": "mouse_x2",
    }
    _MOUSE_FORCE_RELEASE_SECONDS = 0.12
    _FORCE_RELEASE_MOUSE_INPUTS = {"mouse_middle", "mouse_x1", "mouse_x2"}

    def __init__(
        self,
        on_input_event: Callable[[str, bool], None],
        on_input_detected: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_input_event = on_input_event
        self._on_input_detected = on_input_detected
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._mouse_listener: Optional[mouse.Listener] = None
        self._pressed_inputs: Set[str] = set()
        self._mouse_release_timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        """Starts non-blocking keyboard and mouse listeners."""
        if self._keyboard_listener is None:
            self._keyboard_listener = keyboard.Listener(
                on_press=self._on_key_press,
                on_release=self._on_key_release,
                suppress=False,
            )
            self._keyboard_listener.start()

        if self._mouse_listener is None:
            self._mouse_listener = mouse.Listener(
                on_click=self._on_mouse_click,
                on_scroll=self._on_mouse_scroll,
                suppress=False,
            )
            self._mouse_listener.start()

    def stop(self) -> None:
        """Stops listeners and clears local pressed-state cache."""
        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()
            self._keyboard_listener.join(timeout=1.0)
            self._keyboard_listener = None

        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener.join(timeout=1.0)
            self._mouse_listener = None

        with self._lock:
            self._pressed_inputs.clear()
            timers = list(self._mouse_release_timers.values())
            self._mouse_release_timers.clear()
        for timer in timers:
            try:
                timer.cancel()
            except Exception:
                pass

    def reset_state(self) -> None:
        """Clears pressed-state cache to avoid stale startup key states."""
        with self._lock:
            self._pressed_inputs.clear()

    def set_detection_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        """Replaces the capture callback used by the binding UI."""
        self._on_input_detected = callback

    def _on_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        key_name = self.normalize_key(key)
        if key_name:
            self._emit_input(key_name, True)

    def _on_key_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        key_name = self.normalize_key(key)
        if key_name:
            self._emit_input(key_name, False)

    def _on_mouse_click(self, _x: int, _y: int, button: mouse.Button, pressed: bool) -> None:
        button_name = self.normalize_mouse_button(button)
        if button_name:
            if pressed and button_name in self._FORCE_RELEASE_MOUSE_INPUTS:
                self._arm_mouse_release_fallback(button_name)
            elif not pressed:
                self._cancel_mouse_release_fallback(button_name)
            self._emit_input(button_name, pressed)

    def _on_mouse_scroll(self, _x: int, _y: int, _dx: int, dy: int) -> None:
        if dy == 0:
            return
        token = "mouse_wheel_up" if dy > 0 else "mouse_wheel_down"
        # Wheel events are transient pulses.
        self._emit_transient_input(token)

    def _emit_input(self, input_name: str, is_pressed: bool) -> None:
        input_name = input_name.lower()
        should_emit = False

        with self._lock:
            if is_pressed:
                if input_name not in self._pressed_inputs:
                    self._pressed_inputs.add(input_name)
                    should_emit = True
            else:
                if input_name in self._pressed_inputs:
                    self._pressed_inputs.remove(input_name)
                    should_emit = True

        if not should_emit:
            return

        self._safe_event_callback(input_name, is_pressed)
        if is_pressed:
            self._safe_detect_callback(input_name)

    def _emit_transient_input(self, input_name: str) -> None:
        input_name = input_name.lower()
        self._safe_event_callback(input_name, True)
        self._safe_detect_callback(input_name)
        self._safe_event_callback(input_name, False)

    def _safe_event_callback(self, input_name: str, is_pressed: bool) -> None:
        try:
            self._on_input_event(input_name, is_pressed)
        except Exception:
            pass

    def _safe_detect_callback(self, input_name: str) -> None:
        callback = self._on_input_detected
        if callback is None:
            return
        try:
            callback(input_name)
        except Exception:
            pass

    def _arm_mouse_release_fallback(self, input_name: str) -> None:
        timer: Optional[threading.Timer] = None
        with self._lock:
            existing = self._mouse_release_timers.pop(input_name, None)
            if existing is not None:
                try:
                    existing.cancel()
                except Exception:
                    pass
            timer = threading.Timer(
                self._MOUSE_FORCE_RELEASE_SECONDS,
                lambda: self._force_release_input(input_name),
            )
            timer.daemon = True
            self._mouse_release_timers[input_name] = timer
        if timer is not None:
            timer.start()

    def _cancel_mouse_release_fallback(self, input_name: str) -> None:
        timer = None
        with self._lock:
            timer = self._mouse_release_timers.pop(input_name, None)
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _force_release_input(self, input_name: str) -> None:
        with self._lock:
            self._mouse_release_timers.pop(input_name, None)
        self._emit_input(input_name, False)

    @classmethod
    def normalize_key(cls, key: keyboard.Key | keyboard.KeyCode) -> Optional[str]:
        """Converts pynput keyboard objects into stable token names."""
        try:
            if isinstance(key, keyboard.KeyCode):
                if key.char is not None:
                    return key.char.lower()
                if key.vk is not None:
                    return cls._VK_ALIASES.get(int(key.vk), f"vk_{key.vk}")
                return None

            key_text = str(key).lower()
            if key_text.startswith("key."):
                key_name = key_text[4:]
            else:
                key_name = key_text
            return cls._KEY_ALIASES.get(key_name, key_name)
        except Exception:
            return None

    @classmethod
    def normalize_mouse_button(cls, button: mouse.Button) -> Optional[str]:
        """Converts pynput mouse button objects into stable token names."""
        try:
            return cls._MOUSE_BUTTON_ALIASES.get(str(button).lower())
        except Exception:
            return None
