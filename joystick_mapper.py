"""Generic event-driven mapper with vJoy and XInput backends."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import threading
from typing import Any, Dict, Optional, Set

try:
    import pyvjoy
except Exception as exc:  # pragma: no cover - environment dependent
    pyvjoy = None  # type: ignore[assignment]
    _PYVJOY_IMPORT_ERROR = exc
else:
    _PYVJOY_IMPORT_ERROR = None

try:
    import vgamepad as vg
except Exception as exc:  # pragma: no cover - environment dependent
    vg = None  # type: ignore[assignment]
    _VGAMEPAD_IMPORT_ERROR = exc
else:
    _VGAMEPAD_IMPORT_ERROR = None


@dataclass(frozen=True)
class AxisBinding:
    negative: frozenset[str]
    positive: frozenset[str]


@dataclass(frozen=True)
class ButtonBinding:
    inputs: frozenset[str]


class VirtualJoystickMapper:
    """Maps normalized input tokens to virtual controller outputs."""

    AXIS_MIN = 0
    AXIS_MAX = 32768
    AXIS_NEUTRAL = 16384

    AXIS_USAGE_NAMES: Dict[str, str] = {
        "left_stick_x": "HID_USAGE_X",
        "left_stick_y": "HID_USAGE_Y",
        "right_stick_x": "HID_USAGE_RX",
        "right_stick_y": "HID_USAGE_RY",
        "left_trigger": "HID_USAGE_Z",
        "right_trigger": "HID_USAGE_RZ",
        "slider_0": "HID_USAGE_SL0",
        "slider_1": "HID_USAGE_SL1",
        "wheel": "HID_USAGE_WHL",
    }

    AXIS_ORDER = [
        "left_stick_x",
        "left_stick_y",
        "right_stick_x",
        "right_stick_y",
        "left_trigger",
        "right_trigger",
        "slider_0",
        "slider_1",
        "wheel",
    ]

    XUSB_BUTTON_MAP = {
        1: "XUSB_GAMEPAD_A",
        2: "XUSB_GAMEPAD_B",
        3: "XUSB_GAMEPAD_X",
        4: "XUSB_GAMEPAD_Y",
        5: "XUSB_GAMEPAD_LEFT_SHOULDER",
        6: "XUSB_GAMEPAD_RIGHT_SHOULDER",
        7: "XUSB_GAMEPAD_BACK",
        8: "XUSB_GAMEPAD_START",
        9: "XUSB_GAMEPAD_LEFT_THUMB",
        10: "XUSB_GAMEPAD_RIGHT_THUMB",
        11: "XUSB_GAMEPAD_GUIDE",
        12: "XUSB_GAMEPAD_DPAD_UP",
        13: "XUSB_GAMEPAD_DPAD_DOWN",
        14: "XUSB_GAMEPAD_DPAD_LEFT",
        15: "XUSB_GAMEPAD_DPAD_RIGHT",
    }

    TOKEN_ALIASES = {
        "key.enter": "enter",
        "key.return": "enter",
        "key.escape": "esc",
        "key.esc": "esc",
        "key.space": "space",
        "key.up": "up",
        "key.down": "down",
        "key.left": "left",
        "key.right": "right",
        "button.left": "mouse_left",
        "button.right": "mouse_right",
        "button.middle": "mouse_middle",
        "button.x1": "mouse_x1",
        "button.x2": "mouse_x2",
        "left shift": "shift_l",
        "right shift": "shift_r",
        "left ctrl": "ctrl_l",
        "right ctrl": "ctrl_r",
        "left alt": "alt_l",
        "right alt": "alt_r",
        "mouse middle": "mouse_middle",
        "mouse left": "mouse_left",
        "mouse right": "mouse_right",
    }

    _STATUS_OWN = 0
    _STATUS_FREE = 1
    _STATUS_BUSY = 2
    _STATUS_MISSING = 3
    _STATUS_UNKNOWN = 4

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = deepcopy(config)
        self.device_id = int(self.config.get("vjoy_device_id", 1))
        self.auto_select_device = bool(self.config.get("auto_select_device", True))
        self.button_count = int(self.config.get("button_count", 16))
        self.button_count = min(max(self.button_count, 1), 128)
        self.backend = str(self.config.get("backend", "xinput")).strip().lower()
        if self.backend not in ("xinput", "vjoy"):
            self.backend = "xinput"

        self._device: Any = None
        self._lock = threading.Lock()
        self._pressed_inputs: Set[str] = set()
        self._bound_inputs: Set[str] = set()
        self.axis_bindings: Dict[str, AxisBinding] = {}
        self.button_bindings: Dict[int, ButtonBinding] = {}

        self._axis_values = {axis_name: self.AXIS_NEUTRAL for axis_name in self.AXIS_ORDER}
        self._button_states = {button_id: False for button_id in range(1, self.button_count + 1)}
        self._last_axes_sent = dict(self._axis_values)
        self._last_buttons_sent = dict(self._button_states)

        self.set_bindings(self.config.get("bindings", {}), apply_immediately=False)

    @property
    def device_label(self) -> str:
        if self.backend == "xinput":
            return "Virtual Xbox 360 (ViGEm)"
        return f"vJoy Device {self.device_id}"

    def get_axis_names(self) -> list[str]:
        return list(self.AXIS_ORDER)

    def get_button_count(self) -> int:
        return self.button_count

    def get_active_button_ids(self) -> list[int]:
        return sorted(self.button_bindings.keys())

    def export_bindings_config(self) -> Dict[str, Any]:
        with self._lock:
            axes = {}
            for axis_name in self.AXIS_ORDER:
                binding = self.axis_bindings.get(axis_name, AxisBinding(frozenset(), frozenset()))
                axes[axis_name] = {
                    "negative": sorted(binding.negative),
                    "positive": sorted(binding.positive),
                }

            buttons: Dict[str, list[str]] = {}
            for button_id in sorted(self.button_bindings):
                buttons[str(button_id)] = sorted(self.button_bindings[button_id].inputs)

            return {"axes": axes, "buttons": buttons}

    def set_bindings(self, raw_bindings: Dict[str, Any], apply_immediately: bool = True) -> None:
        normalized = self._normalize_bindings(raw_bindings)
        bound_inputs: Set[str] = set()

        axis_bindings: Dict[str, AxisBinding] = {}
        for axis_name in self.AXIS_ORDER:
            axis_data = normalized["axes"].get(axis_name, {})
            negative = frozenset(self._normalize_tokens(axis_data.get("negative", [])))
            positive = frozenset(self._normalize_tokens(axis_data.get("positive", [])))
            bound_inputs.update(negative)
            bound_inputs.update(positive)
            axis_bindings[axis_name] = AxisBinding(
                negative=negative,
                positive=positive,
            )

        button_bindings: Dict[int, ButtonBinding] = {}
        for button_id_text, token_list in normalized["buttons"].items():
            try:
                button_id = int(button_id_text)
            except (TypeError, ValueError):
                continue
            if not (1 <= button_id <= self.button_count):
                continue
            inputs = frozenset(self._normalize_tokens(token_list))
            bound_inputs.update(inputs)
            button_bindings[button_id] = ButtonBinding(
                inputs=inputs
            )

        with self._lock:
            self.axis_bindings = axis_bindings
            self.button_bindings = button_bindings
            self._bound_inputs = set(bound_inputs)
            # Remove stale pressed entries that are no longer bound.
            self._pressed_inputs.intersection_update(self._bound_inputs)
            self._recompute_state_locked()

        if apply_immediately:
            self._apply_outputs(force=False)

    def add_axis_binding(self, axis_name: str, direction: str, input_token: str) -> bool:
        axis_name = str(axis_name).lower()
        direction = str(direction).lower()
        input_token = self._canonical_token(str(input_token))

        if axis_name not in self.AXIS_ORDER or direction not in ("negative", "positive") or not input_token:
            return False

        with self._lock:
            current = self.axis_bindings.get(axis_name, AxisBinding(frozenset(), frozenset()))
            negative = set(current.negative)
            positive = set(current.positive)
            if direction == "negative":
                negative.add(input_token)
            else:
                positive.add(input_token)
            self.axis_bindings[axis_name] = AxisBinding(
                negative=frozenset(sorted(negative)),
                positive=frozenset(sorted(positive)),
            )
            self._bound_inputs.add(input_token)
            self._recompute_state_locked()

        self._apply_outputs(force=False)
        return True

    def add_button_binding(self, button_id: int, input_token: str) -> bool:
        input_token = self._canonical_token(str(input_token))
        if not input_token or not (1 <= button_id <= self.button_count):
            return False

        with self._lock:
            current = self.button_bindings.get(button_id, ButtonBinding(frozenset()))
            new_inputs = set(current.inputs)
            new_inputs.add(input_token)
            self.button_bindings[button_id] = ButtonBinding(inputs=frozenset(sorted(new_inputs)))
            self._bound_inputs.add(input_token)
            self._recompute_state_locked()

        self._apply_outputs(force=False)
        return True

    def remove_axis_binding(self, axis_name: str, direction: str, input_token: str) -> bool:
        axis_name = str(axis_name).lower()
        direction = str(direction).lower()
        input_token = self._canonical_token(str(input_token))

        if axis_name not in self.AXIS_ORDER or direction not in ("negative", "positive"):
            return False

        changed = False
        with self._lock:
            current = self.axis_bindings.get(axis_name, AxisBinding(frozenset(), frozenset()))
            negative = set(current.negative)
            positive = set(current.positive)
            if direction == "negative" and input_token in negative:
                negative.remove(input_token)
                changed = True
            if direction == "positive" and input_token in positive:
                positive.remove(input_token)
                changed = True
            if changed:
                self.axis_bindings[axis_name] = AxisBinding(
                    negative=frozenset(sorted(negative)),
                    positive=frozenset(sorted(positive)),
                )
                self._rebuild_bound_inputs_locked()
                self._recompute_state_locked()

        if changed:
            self._apply_outputs(force=False)
        return changed

    def remove_button_binding(self, button_id: int, input_token: str) -> bool:
        if not (1 <= button_id <= self.button_count):
            return False
        input_token = self._canonical_token(str(input_token))

        changed = False
        with self._lock:
            current = self.button_bindings.get(button_id)
            if current is None:
                return False
            new_inputs = set(current.inputs)
            if input_token in new_inputs:
                new_inputs.remove(input_token)
                changed = True
            if changed:
                if new_inputs:
                    self.button_bindings[button_id] = ButtonBinding(inputs=frozenset(sorted(new_inputs)))
                else:
                    self.button_bindings.pop(button_id, None)
                self._rebuild_bound_inputs_locked()
                self._recompute_state_locked()

        if changed:
            self._apply_outputs(force=False)
        return changed

    def clear_axis_target(self, axis_name: str, direction: str) -> bool:
        axis_name = str(axis_name).lower()
        direction = str(direction).lower()
        if axis_name not in self.AXIS_ORDER or direction not in ("negative", "positive"):
            return False

        with self._lock:
            current = self.axis_bindings.get(axis_name, AxisBinding(frozenset(), frozenset()))
            negative = set(current.negative)
            positive = set(current.positive)
            if direction == "negative":
                if not negative:
                    return False
                negative.clear()
            else:
                if not positive:
                    return False
                positive.clear()
            self.axis_bindings[axis_name] = AxisBinding(
                negative=frozenset(sorted(negative)),
                positive=frozenset(sorted(positive)),
            )
            self._rebuild_bound_inputs_locked()
            self._recompute_state_locked()

        self._apply_outputs(force=False)
        return True

    def clear_button_target(self, button_id: int) -> bool:
        if not (1 <= button_id <= self.button_count):
            return False

        with self._lock:
            if button_id not in self.button_bindings:
                return False
            self.button_bindings.pop(button_id, None)
            self._rebuild_bound_inputs_locked()
            self._recompute_state_locked()

        self._apply_outputs(force=False)
        return True

    def connect(self) -> None:
        if self._device is not None:
            return

        if self.backend == "xinput":
            self._connect_xinput()
        else:
            self._connect_vjoy()

        self.reset_outputs()

    def _connect_xinput(self) -> None:
        if vg is None:
            raise RuntimeError(
                "XInput backend unavailable. Install `vgamepad` and ViGEmBus driver.\n"
                f"Import error: {_VGAMEPAD_IMPORT_ERROR}"
            )
        try:
            self._device = vg.VX360Gamepad()
        except Exception as exc:
            raise RuntimeError(
                "Failed to create virtual Xbox controller.\n"
                "Install ViGEmBus driver, then restart this app."
            ) from exc

    def _connect_vjoy(self) -> None:
        if pyvjoy is None:
            raise RuntimeError(
                "pyvjoy is unavailable. Install dependencies and verify pyvjoy can import.\n"
                f"Import error: {_PYVJOY_IMPORT_ERROR}"
            )

        sdk = getattr(pyvjoy, "_sdk", None)
        if sdk is not None:
            try:
                sdk.vJoyEnabled()
            except Exception as exc:
                raise RuntimeError(
                    "vJoy driver is not enabled.\n"
                    "Install vJoy, reboot if required, and verify it in Configure vJoy."
                ) from exc

        if self.auto_select_device:
            self.device_id = self._pick_device_id(self.device_id)

        try:
            self._device = pyvjoy.VJoyDevice(self.device_id)
        except Exception as exc:
            self._device = None
            raise RuntimeError(self._format_connect_error(exc)) from exc

    def disconnect(self) -> None:
        self.reset_outputs()
        self._device = None

    def handle_input_event(self, input_name: str, is_pressed: bool) -> None:
        input_name = self._canonical_token(str(input_name))
        if not input_name:
            return
        changed = False

        with self._lock:
            # Ignore inputs that are not part of any binding.
            if input_name not in self._bound_inputs and input_name not in self._pressed_inputs:
                return

            if is_pressed:
                if input_name not in self._pressed_inputs:
                    self._pressed_inputs.add(input_name)
                    changed = True
            else:
                if input_name in self._pressed_inputs:
                    self._pressed_inputs.remove(input_name)
                    changed = True

            if changed:
                self._recompute_state_locked()

        if changed:
            self._apply_outputs(force=False)

    def reset_outputs(self) -> None:
        with self._lock:
            self._pressed_inputs.clear()
            self._axis_values = {axis_name: self.AXIS_NEUTRAL for axis_name in self.AXIS_ORDER}
            self._button_states = {button_id: False for button_id in range(1, self.button_count + 1)}
        self._apply_outputs(force=True)

    def get_state_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            active_buttons = self.get_active_button_ids()
            if not active_buttons:
                active_buttons = [1, 2, 7, 8, 9, 10]
            active_buttons = [button for button in active_buttons if 1 <= button <= self.button_count]
            return {
                "axes": dict(self._axis_values),
                "buttons": {str(button): self._button_states[button] for button in active_buttons},
                "pressed_inputs": sorted(self._pressed_inputs),
            }

    def _recompute_state_locked(self) -> None:
        pressed = self._pressed_inputs

        for axis_name in self.AXIS_ORDER:
            binding = self.axis_bindings.get(axis_name, AxisBinding(frozenset(), frozenset()))
            negative_on = any(token in pressed for token in binding.negative)
            positive_on = any(token in pressed for token in binding.positive)
            if negative_on == positive_on:
                direction = 0
            else:
                direction = -1 if negative_on else 1
            self._axis_values[axis_name] = self._direction_to_axis_value(direction)

        new_buttons = {button_id: False for button_id in range(1, self.button_count + 1)}
        for button_id, binding in self.button_bindings.items():
            new_buttons[button_id] = any(token in pressed for token in binding.inputs)
        self._button_states = new_buttons

    @classmethod
    def _direction_to_axis_value(cls, direction: int) -> int:
        if direction < 0:
            return cls.AXIS_MIN
        if direction > 0:
            return cls.AXIS_MAX
        return cls.AXIS_NEUTRAL

    def _apply_outputs(self, force: bool = False) -> None:
        if self._device is None:
            return

        with self._lock:
            axes = dict(self._axis_values)
            buttons = dict(self._button_states)

        if self.backend == "xinput":
            self._apply_xinput_outputs(axes, buttons, force)
        else:
            self._apply_vjoy_outputs(axes, buttons, force)

    def _apply_vjoy_outputs(self, axes: Dict[str, int], buttons: Dict[int, bool], force: bool) -> None:
        if pyvjoy is None:
            return

        for axis_name, axis_value in axes.items():
            if not force and self._last_axes_sent.get(axis_name) == axis_value:
                continue
            usage = getattr(pyvjoy, self.AXIS_USAGE_NAMES[axis_name])
            self._device.set_axis(usage, axis_value)
            self._last_axes_sent[axis_name] = axis_value

        for button_id, pressed in buttons.items():
            if not force and self._last_buttons_sent.get(button_id) == pressed:
                continue
            self._device.set_button(button_id, int(pressed))
            self._last_buttons_sent[button_id] = pressed

    def _apply_xinput_outputs(self, axes: Dict[str, int], buttons: Dict[int, bool], force: bool) -> None:
        state_changed = force

        left_x = self._axis_to_xinput_stick(axes["left_stick_x"])
        left_y = -self._axis_to_xinput_stick(axes["left_stick_y"])
        right_x = self._axis_to_xinput_stick(axes["right_stick_x"])
        right_y = -self._axis_to_xinput_stick(axes["right_stick_y"])

        # Triggers map to 0..255.
        left_trigger = self._axis_to_xinput_trigger(axes["left_trigger"])
        right_trigger = self._axis_to_xinput_trigger(axes["right_trigger"])

        last_lx = self._last_axes_sent.get("left_stick_x")
        last_ly = self._last_axes_sent.get("left_stick_y")
        last_rx = self._last_axes_sent.get("right_stick_x")
        last_ry = self._last_axes_sent.get("right_stick_y")
        last_lt = self._last_axes_sent.get("left_trigger")
        last_rt = self._last_axes_sent.get("right_trigger")

        prev_left_x = self._axis_to_xinput_stick(last_lx if last_lx is not None else self.AXIS_NEUTRAL)
        prev_left_y = -self._axis_to_xinput_stick(last_ly if last_ly is not None else self.AXIS_NEUTRAL)
        prev_right_x = self._axis_to_xinput_stick(last_rx if last_rx is not None else self.AXIS_NEUTRAL)
        prev_right_y = -self._axis_to_xinput_stick(last_ry if last_ry is not None else self.AXIS_NEUTRAL)
        prev_left_trigger = self._axis_to_xinput_trigger(last_lt if last_lt is not None else self.AXIS_NEUTRAL)
        prev_right_trigger = self._axis_to_xinput_trigger(last_rt if last_rt is not None else self.AXIS_NEUTRAL)

        if force or left_x != prev_left_x or left_y != prev_left_y:
            self._device.left_joystick(x_value=left_x, y_value=left_y)
            state_changed = True
        if force or right_x != prev_right_x or right_y != prev_right_y:
            self._device.right_joystick(x_value=right_x, y_value=right_y)
            state_changed = True
        if force or left_trigger != prev_left_trigger:
            self._device.left_trigger(value=left_trigger)
            state_changed = True
        if force or right_trigger != prev_right_trigger:
            self._device.right_trigger(value=right_trigger)
            state_changed = True

        for button_id, pressed in buttons.items():
            if not force and self._last_buttons_sent.get(button_id) == pressed:
                continue
            xusb_name = self.XUSB_BUTTON_MAP.get(button_id)
            if xusb_name is None:
                self._last_buttons_sent[button_id] = pressed
                continue
            xusb_button = getattr(vg.XUSB_BUTTON, xusb_name)
            if pressed:
                self._device.press_button(button=xusb_button)
            else:
                self._device.release_button(button=xusb_button)
            self._last_buttons_sent[button_id] = pressed
            state_changed = True

        if not state_changed:
            return

        # Remember axes for diff checks only when an update was sent.
        self._last_axes_sent.update(axes)
        self._device.update()

    @classmethod
    def _axis_to_xinput_stick(cls, axis_value: int) -> int:
        value = int(max(cls.AXIS_MIN, min(cls.AXIS_MAX, axis_value)))
        normalized = (value - cls.AXIS_NEUTRAL) / cls.AXIS_NEUTRAL
        normalized = max(-1.0, min(1.0, normalized))
        return int(round(normalized * 32767))

    @classmethod
    def _axis_to_xinput_trigger(cls, axis_value: int) -> int:
        value = int(max(cls.AXIS_MIN, min(cls.AXIS_MAX, axis_value)))
        # Keep trigger idle at 0 at neutral midpoint. Only positive direction
        # (neutral -> max) maps to trigger 0..255.
        normalized = (value - cls.AXIS_NEUTRAL) / cls.AXIS_NEUTRAL
        normalized = max(0.0, min(1.0, normalized))
        return int(round(max(0.0, min(1.0, normalized)) * 255))

    @staticmethod
    def _normalize_tokens(items: Any) -> list[str]:
        tokens: list[str] = []
        if not isinstance(items, list):
            return tokens
        for item in items:
            token = VirtualJoystickMapper._canonical_token(str(item))
            if token and token not in tokens:
                tokens.append(token)
        return tokens

    @classmethod
    def _canonical_token(cls, token: str) -> str:
        normalized = str(token).strip().lower().replace("-", "_")
        normalized = " ".join(normalized.split())
        if not normalized:
            return ""
        if normalized in cls.TOKEN_ALIASES:
            return cls.TOKEN_ALIASES[normalized]
        if normalized.startswith("key.") and len(normalized) > 4:
            tail = normalized[4:]
            return cls.TOKEN_ALIASES.get(normalized, tail)
        if normalized.startswith("vk_"):
            try:
                code = int(normalized[3:])
            except ValueError:
                return normalized
            if 65 <= code <= 90:
                return chr(code + 32)
            if 48 <= code <= 57:
                return chr(code)
            return normalized
        return normalized.replace(" ", "_")

    def _normalize_bindings(self, raw_bindings: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(raw_bindings, dict):
            return {"axes": {}, "buttons": {}}

        if "axes" in raw_bindings:
            axes = raw_bindings.get("axes", {})
            buttons = raw_bindings.get("buttons", {})
            if not isinstance(axes, dict):
                axes = {}
            if not isinstance(buttons, dict):
                buttons = {}
            return {"axes": axes, "buttons": buttons}

        axes: Dict[str, Any] = {}
        for axis_name in self.AXIS_ORDER:
            if axis_name in raw_bindings and isinstance(raw_bindings[axis_name], dict):
                axes[axis_name] = raw_bindings[axis_name]

        buttons: Dict[str, list[str]] = {}
        legacy_buttons = raw_bindings.get("buttons", {})
        if isinstance(legacy_buttons, dict):
            for _, data in legacy_buttons.items():
                if not isinstance(data, dict):
                    continue
                button_id = str(int(data.get("vjoy_button", 1)))
                button_tokens = self._normalize_tokens(data.get("keys", []))
                if button_id not in buttons:
                    buttons[button_id] = []
                for token in button_tokens:
                    if token not in buttons[button_id]:
                        buttons[button_id].append(token)

        return {"axes": axes, "buttons": buttons}

    def _rebuild_bound_inputs_locked(self) -> None:
        bound_inputs: Set[str] = set()
        for axis_name in self.AXIS_ORDER:
            binding = self.axis_bindings.get(axis_name, AxisBinding(frozenset(), frozenset()))
            bound_inputs.update(binding.negative)
            bound_inputs.update(binding.positive)
        for binding in self.button_bindings.values():
            bound_inputs.update(binding.inputs)
        self._bound_inputs = bound_inputs
        self._pressed_inputs.intersection_update(self._bound_inputs)

    def _safe_get_device_status(self, device_id: int) -> Optional[int]:
        if pyvjoy is None:
            return None
        sdk = getattr(pyvjoy, "_sdk", None)
        if sdk is None:
            return None
        try:
            return int(sdk.GetVJDStatus(device_id))
        except Exception:
            return None

    def _pick_device_id(self, preferred_id: int) -> int:
        preferred_status = self._safe_get_device_status(preferred_id)
        if preferred_status in (self._STATUS_FREE, self._STATUS_OWN):
            return preferred_id

        for candidate_id in range(1, 17):
            status = self._safe_get_device_status(candidate_id)
            if status in (self._STATUS_FREE, self._STATUS_OWN):
                return candidate_id

        return preferred_id

    def _format_connect_error(self, exc: Exception) -> str:
        status = self._safe_get_device_status(self.device_id)
        status_text = self._status_to_text(status)
        exc_name = type(exc).__name__

        if exc_name == "vJoyNotEnabledException":
            return (
                "vJoy driver is not enabled.\n"
                "Install vJoy and verify driver health in Configure vJoy."
            )

        if exc_name == "vJoyFailedToAcquireException":
            if status == self._STATUS_BUSY:
                return (
                    f"vJoy device {self.device_id} is busy (already owned by another app).\n"
                    "Close other controller mappers, then retry."
                )
            if status == self._STATUS_MISSING:
                return (
                    f"vJoy device {self.device_id} is missing.\n"
                    "Create/enable the device in Configure vJoy."
                )
            return (
                f"Failed to acquire vJoy device {self.device_id}.\n"
                f"Current device status: {status_text}."
            )

        return (
            f"Failed to open vJoy device {self.device_id} ({exc_name}).\n"
            f"Current device status: {status_text}."
        )

    def _status_to_text(self, status: Optional[int]) -> str:
        if status is None:
            return "Unknown"
        if status == self._STATUS_OWN:
            return "Owned by this app"
        if status == self._STATUS_FREE:
            return "Free"
        if status == self._STATUS_BUSY:
            return "Busy"
        if status == self._STATUS_MISSING:
            return "Missing"
        if status == self._STATUS_UNKNOWN:
            return "Unknown"
        return f"Unknown ({status})"
