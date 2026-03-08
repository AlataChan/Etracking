from __future__ import annotations

import sys

from loguru import logger

from src.core.paths import RuntimePaths


def setup_logger(paths: RuntimePaths, level: str = "INFO") -> None:
    paths.ensure()
    logger.remove()
    logger.add(sys.stderr, level=level, colorize=True)
    logger.add(
        str(paths.logs_dir / "etracking.log"),
        rotation="10 MB",
        level=level,
        compression="zip",
        encoding="utf-8",
    )
