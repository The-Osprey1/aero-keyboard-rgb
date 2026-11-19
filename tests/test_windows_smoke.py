"""Runs only on Windows: checks the Windows system calls work (no keyboard needed)."""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_usb_device_list_can_be_read():
    from aero_rgb.monitors.usb import windows_snapshot

    devices = windows_snapshot()
    assert isinstance(devices, dict)
    for device in devices.values():
        assert "&MI_" not in device.id.upper()


def test_window_titles_can_be_read():
    from aero_rgb.monitors.transfer import windows_window_titles

    titles = windows_window_titles()
    assert isinstance(titles, list)
    assert all(isinstance(t, str) for t in titles)
