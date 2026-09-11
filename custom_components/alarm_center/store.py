"""Persistence for Alarm Center.

Config and runtime state go through Home Assistant's ``Store`` helper, which
writes to ``.storage/`` and is therefore included in Home Assistant's built-in
backups. History is appended to rotating JSONL files under
``<config>/alarm_center/`` - also backed up, but not loaded into memory.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_ARCHIVE_DELAY,
    DEFAULT_AUTO_RULE_LEVEL,
    DEFAULT_DIGEST_TIME,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    DEFAULT_REMINDER_INTERVALS,
    DEFAULT_TTS_STREAMS,
    HISTORY_SUBDIR,
    LEVEL_WARNING,
    SAVE_DELAY,
    STORAGE_VERSION,
    STORE_CONFIG_KEY,
    STORE_STATE_KEY,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "archive_delay": DEFAULT_ARCHIVE_DELAY,
    "auto_rules": {
        "enabled": True,
        "default_level": DEFAULT_AUTO_RULE_LEVEL,
        "start_enabled": True,
        "ignored": [],
    },
    "notify": {
        "enabled": True,
        "targets": [],
        "tts": {
            "enabled": False,
            "streams": dict(DEFAULT_TTS_STREAMS),
        },
        "reminders": {
            # A "these are still active" summary at a fixed time of day.
            "digest": {
                "enabled": False,
                "time": DEFAULT_DIGEST_TIME,
                "min_level": LEVEL_WARNING,
            },
            # Per-level repeat for alarms that are still active and
            # unacknowledged. Seconds; 0 turns that level off.
            "repeat": dict(DEFAULT_REMINDER_INTERVALS),
        },
        "quiet_hours": {
            "enabled": False,
            "start": DEFAULT_QUIET_START,
            "end": DEFAULT_QUIET_END,
            # Levels silenced during the window. Anything not listed still
            # gets through immediately.
            "levels": ["warning", "notice"],
            # Send what was held back once the window ends.
            "send_after": True,
        },
    },
    "rules": [],
    "trash": [],
}


class AlarmCenterStore:
    """Reads and writes everything the integration needs to survive a restart."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Set up the stores."""
        self.hass = hass
        self._config_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORE_CONFIG_KEY
        )
        self._state_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORE_STATE_KEY
        )
        self._history_dir = Path(hass.config.path(HISTORY_SUBDIR))
        self._history_lock = asyncio.Lock()
        self.config: dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))

    # -- config ----------------------------------------------------------

    async def async_load_config(self) -> dict[str, Any]:
        """Load config, merged over the defaults so new keys get values."""
        stored = await self._config_store.async_load()
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        if stored:
            for key, value in stored.items():
                if isinstance(value, dict) and isinstance(config.get(key), dict):
                    config[key].update(value)
                else:
                    config[key] = value
        self.config = config
        return config

    def async_save_config(self, *, immediate: bool = False) -> None:
        """Queue a config save. Debounced unless ``immediate``."""
        if immediate:
            self.hass.async_create_task(
                self._config_store.async_save(self.config), eager_start=False
            )
        else:
            self._config_store.async_delay_save(lambda: self.config, SAVE_DELAY)

    # -- runtime state ---------------------------------------------------

    async def async_load_state(self) -> dict[str, Any]:
        """Load open alarms from the last run."""
        return await self._state_store.async_load() or {}

    def async_save_state(self, data_func) -> None:
        """Queue a debounced save of the open alarm list."""
        self._state_store.async_delay_save(data_func, SAVE_DELAY)

    async def async_flush_state(self, data: dict[str, Any]) -> None:
        """Write open alarms right now, e.g. on shutdown."""
        await self._state_store.async_save(data)

    # -- history ---------------------------------------------------------

    def _history_path(self, when: datetime) -> Path:
        return self._history_dir / f"history-{when.strftime('%Y-%m')}.jsonl"

    async def async_append_history(self, record: dict[str, Any]) -> None:
        """Append one archived alarm to the current month's history file."""
        when = datetime.fromisoformat(record["archived_at"])
        path = self._history_path(when)
        line = json.dumps(record, default=str)
        async with self._history_lock:
            await self.hass.async_add_executor_job(_append_line, path, line)

    async def async_read_history(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Read history newest first."""
        return await self.hass.async_add_executor_job(
            _read_history, self._history_dir, limit, offset
        )

    async def async_history_stats(self) -> dict[str, Any]:
        """Return simple stats about the history files."""
        return await self.hass.async_add_executor_job(_history_stats, self._history_dir)


def _append_line(path: Path, line: str) -> None:
    """Append one line to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def _history_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(directory.glob("history-*.jsonl"), reverse=True)


def _read_history(directory: Path, limit: int, offset: int) -> list[dict[str, Any]]:
    """Read up to ``limit`` records, newest first, skipping ``offset``."""
    records: list[dict[str, Any]] = []
    skipped = 0
    for path in _history_files(directory):
        try:
            with path.open("r", encoding="utf-8") as file:
                lines = file.readlines()
        except OSError as err:  # pragma: no cover - defensive
            _LOGGER.warning("Could not read %s: %s", path, err)
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            if skipped < offset:
                skipped += 1
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
            if len(records) >= limit:
                return records
    return records


def _history_stats(directory: Path) -> dict[str, Any]:
    files = _history_files(directory)
    return {
        "files": [file.name for file in files],
        "bytes": sum(os.path.getsize(file) for file in files if file.exists()),
    }
