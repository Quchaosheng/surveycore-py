from __future__ import annotations

from importlib.resources import files


def get_resource_path(relative_path: str) -> str:
    """Return a packaged resource path for legacy helpers."""
    path = files("surveycore").joinpath(str(relative_path).replace("\\", "/"))
    return str(path)


__all__ = ["get_resource_path"]
