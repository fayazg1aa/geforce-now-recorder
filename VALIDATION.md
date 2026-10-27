GeForce NOW Recorder v1.3 - verification scope
===========================================

BUILD
Windows x64; Python 3.13; PyInstaller 6.22.3; standalone single-file EXE.

PASS - 21 automated regression tests.
New checks include preserving 125-microsecond timestamp intervals despite
identical coarse Windows timestamps, precise F8 cutoff, native Windows timer
cancellation, mouse-settings restoration, settings rollback after failure,
manual-setting preservation, watchdog journal restoration, and capture-error
cleanup. Input injection is mocked in the regression suite; the native timer
and ctypes data structures use actual Windows APIs.

PASS - real Windows mouse-setting roundtrip.
The temporary neutral input settings were applied and the original settings
were restored exactly.

PASS - real source-based crash watchdog test.
A controlled source process applied the temporary settings and exited without
cleanup. The watchdog restored the original settings. This test did not type
into or manipulate the user's game.

MEASURED - native timer, 200 deadlines spaced 1ms apart on this machine.
Median observed lateness: 0.4398ms.
95th percentile observed lateness: 0.9013ms.
Maximum observed lateness: 1.6073ms.
These are one local benchmark, not a guarantee of game frame timing.

PASS - standalone EXE startup self-test, process exit 0.
Raw Input registration: true.
Keyboard hook: installed.
Mouse hook: installed.
Hook error: none.
Default mode: GeForce NOW (raw movement).
1:1 temporary input option: enabled.
Five-second trim: disabled.
INPUT size: 40 bytes.
Required layout: 434 x 468 pixels; window: 510 x 510 pixels.

NOT COMPLETED - live Chrome Pointer Lock / actual GeForce NOW comparison.
The user's actual Chrome GeForce NOW window was located. Computer Use then
stopped the attempt because it could not determine the current Windows
browser URL with sufficient confidence to enforce its policy.
No successful live game result or pixel-exact movement claim is implied by
the automated tests, timer measurements, or executable startup check.

PRESERVED
The original ZIP and previous v1.2 outputs remain unchanged. The existing
user recording was backed up locally before development. No user recording
or keystroke log is included in this package.
