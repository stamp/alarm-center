"""Constants for the Alarm Center integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "alarm_center"
VERSION: Final = "0.2.0"

# Frontend / panel
PANEL_URL_PATH: Final = "alarm-center"
PANEL_TITLE: Final = "Alarm Center"
PANEL_ICON: Final = "mdi:alarm-light"
PANEL_COMPONENT_NAME: Final = "alarm-center-panel"
STATIC_URL: Final = "/alarm_center_static"

# Storage
STORAGE_VERSION: Final = 1
STORE_CONFIG_KEY: Final = f"{DOMAIN}.config"
STORE_STATE_KEY: Final = f"{DOMAIN}.state"
HISTORY_SUBDIR: Final = DOMAIN
SAVE_DELAY: Final = 10

# Levels, most severe first.
LEVEL_CRITICAL: Final = "critical"
LEVEL_ERROR: Final = "error"
LEVEL_WARNING: Final = "warning"
LEVEL_NOTICE: Final = "notice"
LEVELS: Final = [LEVEL_CRITICAL, LEVEL_ERROR, LEVEL_WARNING, LEVEL_NOTICE]
LEVEL_SEVERITY: Final = {level: len(LEVELS) - i for i, level in enumerate(LEVELS)}

# Rule kinds
KIND_PROBLEM: Final = "problem"
KIND_NUMERIC: Final = "numeric"
KIND_STATE: Final = "state"
KIND_TEMPLATE: Final = "template"
RULE_KINDS: Final = [KIND_PROBLEM, KIND_NUMERIC, KIND_STATE, KIND_TEMPLATE]

# Alarm keys
KEY_RULE_PREFIX: Final = "rule:"
KEY_MANUAL_PREFIX: Final = "manual:"

# Dispatcher signal used to push updates to the panel and entities.
SIGNAL_UPDATE: Final = f"{DOMAIN}_update"

# Bus events
EVENT_ALARM: Final = f"{DOMAIN}_event"
EVENT_ACTION_RAISED: Final = "raised"
EVENT_ACTION_REACTIVATED: Final = "reactivated"
EVENT_ACTION_CLEARED: Final = "cleared"
EVENT_ACTION_ACKNOWLEDGED: Final = "acknowledged"
EVENT_ACTION_ARCHIVED: Final = "archived"

# Defaults
DEFAULT_ARCHIVE_DELAY: Final = 60
DEFAULT_AUTO_RULE_LEVEL: Final = LEVEL_WARNING
DEFAULT_HISTORY_LIMIT: Final = 100
AUTO_RULE_PREFIX: Final = "auto_problem_"
AUTO_SYNC_INTERVAL_MINUTES: Final = 10

# Notification actions
NOTIFY_ACK_ACTION_PREFIX: Final = "ALARM_CENTER_ACK_"
NOTIFY_TAG_PREFIX: Final = "alarm_center_"
NOTIFY_TAG_DIGEST: Final = "alarm_center_digest"

# Reminders. Repeat intervals are seconds; 0 means no repeat for that level.
REMINDER_TICK_SECONDS: Final = 60
DEFAULT_REMINDER_INTERVALS: Final = {
    LEVEL_CRITICAL: 3600,
    LEVEL_ERROR: 0,
    LEVEL_WARNING: 0,
    LEVEL_NOTICE: 0,
}
DEFAULT_DIGEST_TIME: Final = "07:00"
DEFAULT_QUIET_START: Final = "22:00"
DEFAULT_QUIET_END: Final = "07:00"

# Android notification channels, one per level so they can be muted
# independently in the phone's own notification settings.
LEVEL_CHANNEL: Final = {
    LEVEL_CRITICAL: "Alarm Center - Critical",
    LEVEL_ERROR: "Alarm Center - Error",
    LEVEL_WARNING: "Alarm Center - Warning",
    LEVEL_NOTICE: "Alarm Center - Notice",
}
LEVEL_IMPORTANCE: Final = {
    LEVEL_CRITICAL: "high",
    LEVEL_ERROR: "high",
    LEVEL_WARNING: "default",
    LEVEL_NOTICE: "low",
}

# TTS / alarm-stream playback. "off" plays nothing.
TTS_STREAM_OFF: Final = "off"
TTS_STREAM_NORMAL: Final = "alarm_stream"
TTS_STREAM_MAX: Final = "alarm_stream_max"
TTS_STREAMS: Final = [TTS_STREAM_OFF, TTS_STREAM_NORMAL, TTS_STREAM_MAX]
DEFAULT_TTS_STREAMS: Final = {
    LEVEL_CRITICAL: TTS_STREAM_MAX,
    LEVEL_ERROR: TTS_STREAM_NORMAL,
    LEVEL_WARNING: TTS_STREAM_OFF,
    LEVEL_NOTICE: TTS_STREAM_OFF,
}

# Services
SERVICE_RAISE: Final = "raise_alarm"
SERVICE_CLEAR: Final = "clear_alarm"
SERVICE_ACKNOWLEDGE: Final = "acknowledge"
SERVICE_ACKNOWLEDGE_ALL: Final = "acknowledge_all"
