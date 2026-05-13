"""OpenWandb - Open-source WandB-compatible server."""

try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("openwandb")
except Exception:
    __version__ = "0.0.0-dev"
