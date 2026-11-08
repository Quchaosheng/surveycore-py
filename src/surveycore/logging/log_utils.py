from __future__ import annotations

import logging
from typing import Optional


def log_suppressed_exception(context: str, exc: Optional[BaseException] = None, *, level: int = logging.INFO) -> None:
    logging.log(level, "[Suppressed] %s%s", context, f": {exc}" if exc else "")


__all__ = ["log_suppressed_exception"]
