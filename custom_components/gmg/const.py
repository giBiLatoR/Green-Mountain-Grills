"""Constants for the GMG integration."""
from __future__ import annotations

import logging

from homeassistant.const import Platform

DOMAIN = "gmg"
LOGGER = logging.getLogger(__package__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]

DEFAULT_PORT = 8080
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 600

CONF_SERIAL = "serial"
CONF_SCAN_INTERVAL = "scan_interval"

# Auto-cook options-flow keys (opt-in, all default OFF).
CONF_AUTO_COOK_ENABLED = "auto_cook_enabled"
CONF_AUTO_COOK_DEV_MODE = "auto_cook_dev_mode"
CONF_AUTO_COOK_PUSH = "auto_cook_push_notifications"

MANUFACTURER = "Green Mountain Grills"

MIN_GRILL_TEMP_F = 150
MAX_GRILL_TEMP_F = 550
GRILL_TEMP_STEP_F = 5
MIN_PROBE_TARGET_F = 32
MAX_PROBE_TARGET_F = 257

# Auto-cook helper bounds.
MIN_COOK_WEIGHT_KG = 0.2
MAX_COOK_WEIGHT_KG = 12.0
COOK_WEIGHT_STEP_KG = 0.1
MIN_FINISH_IN_HOURS = 1.0
MAX_FINISH_IN_HOURS = 30.0
