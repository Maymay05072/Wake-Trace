"""WakeTrace: lightweight continuity for autonomous companion wake cycles."""

from .config import Settings
from .engine import WakeEngine
from .lifeworld import LifeWorld, build_lifeworld_tools
from .models import WakeResult, WakeSeed

__all__ = [
    "LifeWorld",
    "Settings",
    "WakeEngine",
    "WakeResult",
    "WakeSeed",
    "build_lifeworld_tools",
]
__version__ = "0.1.0a1"
