import pytest

from aero_rgb.backends import DryRunBackend
from aero_rgb.engine import LightEngine
from aero_rgb.state import LightState


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def backend():
    return DryRunBackend(echo=None)


@pytest.fixture
def engine(backend, clock):
    return LightEngine(backend, LightState("static", (255, 255, 255), 6), min_interval=0.0, clock=clock)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AERO_RGB_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("AERO_RGB_CONFIG", raising=False)
