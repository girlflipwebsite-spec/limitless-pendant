"""Shared constants: BLE UUIDs, timestamps, and local storage paths."""

import os
from pathlib import Path

# Device addressing. On macOS, bleak identifies peripherals by a CoreBluetooth
# UUID (not a MAC address) - whatever this is set to, `pendant scan` will help
# you find it.
PENDANT_ADDRESS = os.environ.get("PENDANT_ADDRESS")

# BLE UUIDs (from the reverse-engineered protocol, see PROTOCOL.md)
AUDIO_SERVICE_UUID = "632de001-604c-446b-a80f-7963e950f3fb"
CONTROL_CHAR_UUID = "632de002-604c-446b-a80f-7963e950f3fb"   # Phone -> Pendant (write)
AUDIO_DATA_CHAR_UUID = "632de003-604c-446b-a80f-7963e950f3fb"  # Pendant -> Phone (notify)

PENDANT_SERVICE_UUIDS = {
    AUDIO_SERVICE_UUID: "Pendant Audio Service",
    "8d53dc1d-1db7-4cd3-868b-8a527460aa84": "Pendant Data Channel",
}
PENDANT_CHARACTERISTIC_UUIDS = {
    CONTROL_CHAR_UUID: "Control (write)",
    AUDIO_DATA_CHAR_UUID: "Audio Data (notify)",
    "da2e7828-fbce-4e01-ae9e-261174997c48": "Bidirectional Data",
}

# A timestamp below this is almost certainly device uptime / unsynced clock,
# not a real wall-clock time (Jan 1, 2020).
MIN_VALID_TIMESTAMP_MS = 1577836800000

# Local storage layout, all under the project root unless overridden.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PENDANT_DATA_DIR", PROJECT_ROOT / "data"))
RECORDINGS_DIR = DATA_DIR / "recordings"       # recordings/<YYYY-MM-DD>/*.opus,*.wav
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"     # transcripts/<YYYY-MM-DD>.md
LOGS_DIR = DATA_DIR / "logs"                   # diagnostic logs to send back to the developer
SYNC_STATE_PATH = DATA_DIR / "sync_state.json"


def get_pendant_address() -> str:
    if not PENDANT_ADDRESS:
        raise RuntimeError(
            "PENDANT_ADDRESS environment variable is not set. "
            "Run `python -m pendant.cli scan` to find your device, then "
            "export PENDANT_ADDRESS=<address-or-uuid> before running other commands."
        )
    return PENDANT_ADDRESS
