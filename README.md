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

File:

- Source run: `.\config.json`
- Installed app: `%LOCALAPPDATA%\KeytoXboxPS\config.json`

Important fields:

- `backend` (`xinput` or `vjoy`)
- `controller_profile`
- `ui_theme` (`light` / `dark`)
- `bindings.axes`
- `bindings.buttons`

## Build App Bundle

```powershell
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean KeytoXboxPS.spec
```

Output:

- `dist\KeytoXboxPS\KeytoXboxPS.exe`

## Build Installer

Requirements:

- Python
- Inno Setup 6 (`iscc` on `PATH`)

Command:

```powershell
.\build-release.ps1
```

Outputs:

- App bundle: `dist\KeytoXboxPS\`
- Installer: `dist\installer\KeytoXboxPS-Setup.exe`

## GitHub Release Automation

This repo includes a GitHub Actions workflow at `.github/workflows/release.yml`.

It runs on Windows when you push a tag like `v1.0.3` and will:

- build the PyInstaller app bundle
- build the Inno Setup installer
- create `dist\KeytoXboxPS-portable.zip`
- attach the installer and portable zip to the GitHub release

Release flow:

```powershell
git tag v1.0.3
git push origin v1.0.3
```

If the release draft is not created automatically yet, create the GitHub release for that tag and rerun the workflow or push a new tag.

## Windows Trust / SmartScreen

An installer does **not** stop Windows from showing "unknown app" or "make sure you trust this app" prompts by itself.

To reduce or eliminate those warnings in real-world distribution you need:

1. A valid **code-signing certificate** from a trusted CA.
2. To sign **both** `KeytoXboxPS.exe` and `KeytoXboxPS-Setup.exe`.
3. To build release reputation over time, or use an **EV code-signing certificate** for faster SmartScreen trust.

Practical notes:

- Unsigned PyInstaller executables are commonly flagged as suspicious.
- `onefile` and UPX-compressed builds are more likely to trigger heuristics than a normal installed `onedir` app.
- This project now uses an installer-friendly `onedir` build and disables UPX to reduce false positives, but code signing is still required for proper trust.

## Notes

- For Roblox: use `xinput` backend.
- Some games switch UI to controller mode when virtual controller input is active.
