# KeytoXboxPS

KeytoXboxPS maps keyboard and mouse input to a virtual controller on Windows (Xbox-style/XInput or vJoy).

## Features

- Keyboard + mouse to virtual controller mapping
- Save/load bindings from `config.json`
- `xinput` backend (recommended for most games, including Roblox)
- `vjoy` backend (legacy DirectInput path)
- Light/Dark theme toggle (saved)
- Enable/Disable output button (disconnect/reconnect virtual device)
- Single-instance protection

## Driver Links (Required)

Install one of these depending on backend:

- **ViGEmBus** (for `xinput`, recommended):  
  https://github.com/ViGEm/ViGEmBus/releases
- **vJoy** (for `vjoy` backend):  
  https://github.com/shauleiz/vJoy/releases  
  Alternate project page: https://vjoystick.sourceforge.net/

## Quick Start (EXE)

1. Install **ViGEmBus** (recommended).
2. Run `KeytoXboxPS.exe`.
3. Pick profile (`xbox` or `playstation`).
4. Choose target (`Button` or axis direction).
5. Click `Capture Next Input`, press your key/mouse input, then click `Save`.

## Run From Source

```powershell
pip install -r requirements.txt
python main.py
```

## Example: Map L3 to Mouse Middle

1. Profile: `playstation`
2. Bind To: `Button`
3. Button: `L3`
4. Click `Capture Next Input`
5. Press middle mouse button
6. Click `Save`

## Common Input Tokens

- Keyboard: `w`, `a`, `s`, `d`, `enter`, `esc`, `shift_l`, `ctrl_l`
- Mouse: `mouse_left`, `mouse_right`, `mouse_middle`, `mouse_x1`, `mouse_x2`
- Wheel: `mouse_wheel_up`, `mouse_wheel_down`

## Config

File: `config.json`

Important fields:

- `backend` (`xinput` or `vjoy`)
- `controller_profile`
- `ui_theme` (`light` / `dark`)
- `bindings.axes`
- `bindings.buttons`

## Build EXE

```powershell
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --collect-all vgamepad --collect-all ttkbootstrap --add-data "assets\icon-KeytoXboxPS.png;assets" --add-data "assets\icon-KeytoXboxPS.ico;assets" --icon "assets\icon-KeytoXboxPS.ico" --name KeytoXboxPS main.py
Copy-Item -Force .\config.json .\dist\config.json
```

Output:

- `dist\KeytoXboxPS.exe`

## Notes

- For Roblox: use `xinput` backend.
- Some games switch UI to controller mode when virtual controller input is active.
