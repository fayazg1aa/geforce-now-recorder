# GeForce NOW Recorder

An independent Windows 10/11 x64 desktop macro recorder for keyboard and mouse input, with raw relative mouse recording and repeat playback.

## Current status

This is source for the existing v1.3 tool. It has not been published as a public repository before. No GitHub stars, downloads, or user counts are claimed. The live Chrome/GeForce NOW camera comparison is still incomplete; see [VALIDATION.md](VALIDATION.md).

## Features

- F8 starts and stops a recording; F9 starts and stops repeat playback.
- Raw relative mouse packets, keyboard input, button edges, and high-resolution receipt timestamps are retained.
- Playback uses a Windows high-resolution waitable timer and stops if the target window loses focus.
- Optional temporary 1:1 Windows pointer settings are restored when recording or playback stops, on normal exit, and after errors. A watchdog handles unexpected process exit.
- Recordings are stored in `%LOCALAPPDATA%\GeForceNOWRecorder\recording.json`; the previous recording is backed up locally.

## Requirements

- Windows 10 or 11, x64.
- Python 3.10+ with Tkinter to run from source.
- PyInstaller 6.22.3 is used only to build the optional standalone EXE.

The application source uses Python's standard library, Tkinter, and Windows ctypes APIs.

## Run from source

```powershell
py -3 main.py
```

`RUN_APP.bat` starts the bundled EXE if present; otherwise, it starts the Python source.

## Build a standalone EXE

```text
BUILD_EXE.bat
```

The script creates an isolated `.build-venv`, installs the pinned build dependency, and writes the EXE under `dist/`.

## Regression checks

```powershell
py -3 test_regressions.py
```

The existing validation record reports 21 regression tests passing, plus Windows settings restoration, watchdog recovery, and EXE startup checks. Those checks do not establish live-game camera accuracy. See [VALIDATION.md](VALIDATION.md) for scope and limitations.

## Limitations

- The recorder cannot read or reset cloud-game camera, character, or server state.
- Windows scheduling, browser input dispatch, cloud latency, and game camera behavior can affect playback.
- A completed live comparison in Chrome with GeForce NOW is not currently documented.

## Trademark

GeForce NOW and NVIDIA are trademarks of NVIDIA Corporation. This independent project is not affiliated with, endorsed by, or sponsored by NVIDIA.

## License

MIT. See [LICENSE](LICENSE).
