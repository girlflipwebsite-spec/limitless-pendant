"""Turns known low-level Bluetooth errors into plain-English advice.

This only translates error text for display - it doesn't touch the device or
any BLE logic, and unrecognized errors are always passed through unchanged.
"""

from typing import Optional

STALE_PAIRING_MARKER = "Peer removed pairing information"

STALE_PAIRING_HELP = """\
macOS and the Pendant disagree about their saved Bluetooth connection
("Peer removed pairing information"). This happens when the Pendant has
since been connected to another device, usually your phone. Nothing is wrong
with the Pendant or your recordings. To fix it:

  1. Turn off Bluetooth on your phone (or fully quit the Limitless app).
  2. In Terminal, restart the Mac's Bluetooth service (it comes back on its own;
     other Bluetooth devices reconnect after a few seconds):
         sudo pkill bluetoothd
  3. Tap the Pendant to wake it, then run:
         python3 -m pendant.cli scan
  4. Try again."""


def friendly_ble_error(exc: BaseException) -> Optional[str]:
    """Plain-English explanation for a recognized error, else None."""
    if STALE_PAIRING_MARKER in str(exc):
        return STALE_PAIRING_HELP
    return None
