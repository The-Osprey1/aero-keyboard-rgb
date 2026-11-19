# Hardware backend follow-up

The first CLI improvement keeps the existing Gigabyte DLL backend. It does not
claim independent HID support or newly verified laptop compatibility.

Reference: https://github.com/ejempty/aero-keyboard-fan at
802d4fe17f274c5b9796ae1a7f75c90ed0f8f44e.
Its README identifies USB 0414:8104 and LampArray keyboard control.
Its `probe/lamparray_read.py` reads report 1 on a hard-coded MI_04 device path,
decoding lamp count, kind and minimum update interval. This is a useful lead,
not evidence that every matching laptop exposes the same physical lights.
Our protocol notes describe the interface as an auxiliary notification lamp.

Before replacing the backend:

1. Enumerate the target machine's interfaces dynamically; record model and IDs.
2. Read descriptors and LampArray attributes without modifying hardware.
3. Confirm which physical lights the interface controls in an explicit hardware test.
4. Verify color, brightness, ownership conflicts and wake recovery.
5. Keep model-specific capabilities and verified results separate from assumptions.

No external implementation code has been copied. Fan control is outside this
lighting change. A tray controller, event arbitration, idle/wake behavior and
an independent backend remain follow-up work.
