"""Command-line interface.

Usage:
    python -m pendant.cli scan
    python -m pendant.cli status
    python -m pendant.cli info
    python -m pendant.cli sync
    python -m pendant.cli decode <opus_file>
    python -m pendant.cli transcribe <YYYY-MM-DD> [--format md|txt|json]

All commands except `decode`/`transcribe` need PENDANT_ADDRESS set - run
`scan` first to find it.
"""

import asyncio
import sys

import click

from .ble_client import PendantClient, scan_for_pendants
from .config import get_pendant_address
from .logging_utils import SessionLog
from .sync_state import SyncState


@click.group()
def cli():
    """Local, cloud-independent tooling for the Limitless Pendant."""


@cli.command()
@click.option("--time", "-t", "duration", default=10.0, help="Scan duration in seconds")
def scan(duration):
    """Scan for nearby BLE devices and highlight likely Pendants."""
    with SessionLog("scan") as log:
        results = asyncio.run(scan_for_pendants(duration))

        pendants = [r for r in results if r.is_pendant]
        others = [r for r in results if not r.is_pendant]

        if pendants:
            log.echo("Pendant devices found:")
            for r in pendants:
                rssi = f" (RSSI {r.rssi})" if r.rssi is not None else ""
                log.echo(f"  {r.address}  {r.name or 'Unknown'}{rssi}  [{r.match_reason}]")
            log.echo("")
            log.echo(f"Set this before running other commands:")
            log.echo(f"  export PENDANT_ADDRESS=\"{pendants[0].address}\"")
        else:
            log.echo("No Pendant found in this scan.")
            log.echo(
                "Make sure it's powered on and awake (tap it), and that it isn't "
                "currently connected to a phone via the official Limitless app."
            )

        if others:
            log.echo("")
            log.echo(f"Other BLE devices seen ({len(others)}):")
            for r in others:
                rssi = f" (RSSI {r.rssi})" if r.rssi is not None else ""
                log.echo(f"  {r.address}  {r.name or 'Unknown'}{rssi}")


async def _connected_client(log) -> PendantClient:
    client = PendantClient(get_pendant_address(), log=log.echo)
    connected = await client.connect()
    if not connected:
        raise click.ClickException("Could not connect - see log above for details.")
    return client


@cli.command()
def status():
    """Read device status: recording state, storage %, battery."""
    with SessionLog("status") as log:
        async def run():
            client = await _connected_client(log)
            try:
                status = await client.get_status()
                log.echo("")
                log.echo(f"Recording: {status.get('is_recording')}")
                log.echo(f"Storage used: {status.get('storage_used_percent')}%")
                log.echo(f"Wifi connected: {status.get('wifi_connected')}")
                battery = status.get("battery")
                if battery:
                    log.echo(f"Battery: {battery.get('level')}% (charging={battery.get('charging')})")
            finally:
                await client.disconnect()

        asyncio.run(run())


@cli.command()
def info():
    """Read device info: firmware, hardware, serial number."""
    with SessionLog("info") as log:
        async def run():
            client = await _connected_client(log)
            try:
                info = await client.get_info()
                log.echo("")
                log.echo(f"Device name: {info.get('device_name')}")
                log.echo(f"Firmware: {info.get('firmware_version')}")
                log.echo(f"Hardware: {info.get('hardware_version')}")
                log.echo(f"Serial: {info.get('serial_number')}")
            finally:
                await client.disconnect()

        asyncio.run(run())


@cli.command()
def sync():
    """Download all NEW recordings from the device and save them locally,
    organized by date. Never deletes anything from the device."""
    with SessionLog("sync") as log:
        async def run():
            client = await _connected_client(log)
            try:
                log.echo("")
                await client.sync_time()
                log.echo("Clock synced.")

                sync_state = SyncState()
                result = await client.sync_recordings(sync_state)

                log.echo("")
                log.echo(f"Pages received: {result.pages_received}")
                log.echo(f"  new: {result.pages_new}  already downloaded: {result.pages_already_seen}")
                log.echo(f"Recordings saved: {len(result.recordings_saved)}")
                for saved in result.recordings_saved:
                    log.echo(
                        f"  session {saved['session']} run {saved['run']}: "
                        f"{saved['page_count']} pages -> {saved['opus_path'] or '(no plaintext audio)'}"
                    )
                    if saved["is_encrypted"]:
                        log.echo(
                            "    [!] this recording's audio is ENCRYPTED. Decrypting it requires "
                            "injecting a new key onto the device (a 'rekey'), which the project's "
                            "safety rules say NOT to do without discussing it with you first - "
                            "see CLAUDE.md Section 7.4 / Section 9. No audio was saved for it."
                        )

                if result.any_encrypted:
                    log.echo("")
                    log.echo(
                        "SUMMARY: at least one recording on this device is encrypted. "
                        "This is the key open question from the project plan (Section 7.4) - "
                        "please share this log so we can decide how to proceed."
                    )
            finally:
                await client.disconnect()

        asyncio.run(run())


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.argument("output_file", required=False)
def decode(input_file, output_file):
    """Decode a raw .opus recording to a playable .wav file."""
    from .opus_decoder import decode_opus_file

    if output_file is None:
        output_file = input_file.rsplit(".", 1)[0] + ".wav"

    stats = decode_opus_file(input_file, output_file)
    click.echo(f"Decoded {stats.frame_count} frames, {stats.duration_sec:.1f}s -> {output_file}")


@cli.command()
@click.argument("date", metavar="YYYY-MM-DD")
@click.option(
    "--format", "output_format", type=click.Choice(["md", "txt", "json"]), default="md"
)
def transcribe(date, output_format):
    """Transcribe a day's recordings into one clean transcript file."""
    from .transcript_export import export_daily_transcript

    out_path = export_daily_transcript(date, output_format=output_format)
    click.echo(f"Wrote {out_path}")


def main():
    cli()


if __name__ == "__main__":
    sys.exit(main())
