from importlib.metadata import PackageNotFoundError, version

from .breakpoint import Breakpoint
from .metrics_patch import MetricsPatch
from .sim_manager import Lens
from .tracking_patch import TrackingPatch

try:
    __version__ = version("simpylens")
except PackageNotFoundError:
    # Local source checkout without installed package metadata.
    __version__ = "0.0.0+local"

__all__ = ["Lens", "Breakpoint", "TrackingPatch", "MetricsPatch", "__version__"]
