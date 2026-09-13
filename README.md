# Limitless Pendant - Local Tool

Connects directly to your Limitless Pendant over Bluetooth, downloads
recordings, saves them on your Mac organized by date, transcribes them, and
produces one clean daily transcript file you can paste or upload into
ChatGPT. No Limitless cloud account needed.

This tool is **read-only** with respect to the device: it never deletes
recordings, resets, or reconfigures the Pendant. See `CLAUDE.md` Section 4
for the full safety rules this project follows.

## One-time setup (on your Mac)

1. Check your Python version:
   ```
   python3 --version
   ```
   Need 3.11 or newer. If it's missing or older, install from
   [python.org](https://www.python.org/downloads/) or via Homebrew
   (`brew install python@3.12`).

2. Get this code:
   ```
   git clone <the private repo URL you were given> limitless-pendant
   cd limitless-pendant
   ```
   (Later updates: `git pull` from inside that folder.)

3. Install the Opus audio library (needed to decode recordings):
   ```
   brew install opus
   ```

4. Create a virtual environment and install the Python dependencies:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

5. Pair the Pendant with your Mac **once**, the normal macOS way:
   - Open **System Settings > Bluetooth**
   - Put the Pendant in pairing mode (check its manual/LED behavior)
   - Click **Connect** next to it when it appears

   Do this even though nothing will "stay connected" afterward - it's what
   creates the Bluetooth bond your Mac needs to talk to it later.

## First run on your Mac (Phase 1 - what we need to verify together)

With the virtual environment active (`source .venv/bin/activate` if not
already):

```
python3 -m pendant.cli scan
```

This lists nearby Bluetooth devices and tries to flag the Pendant. If found,
it prints an `export PENDANT_ADDRESS="..."` line - run that command (or add
it to `~/.zshrc` so it's set automatically in new terminals).

Then try, in order:

```
python3 -m pendant.cli status
python3 -m pendant.cli info
```

**Please send back:**
- Whatever these three commands print (they also save a copy under
  `data/logs/`, so you can just attach those files)
- Whether `status`/`info` succeeded or hung/errored after `scan` found the
  device

This tells us whether pairing via System Settings alone is enough for the
device to respond to commands, which is the first open question for this
project (see `CLAUDE.md` Section 7.2).

## Downloading recordings (Phase 2/3)

Once `status`/`info` work:

```
python3 -m pendant.cli sync
```

This downloads everything currently stored on the Pendant that we haven't
already saved, and writes it to `data/recordings/<date>/`. Running it again
later only pulls new recordings - it will not delete anything from the
device.

**Important:** if `sync` prints a warning that a recording is **encrypted**,
stop there and send that log back. That means this Pendant has audio
encryption turned on, and decrypting it requires a device "rekey" that we
need to discuss first, per `CLAUDE.md` Section 7.4/9 - please don't run any
further commands until we've talked about it.

If it's not encrypted, you'll see a `.opus` file per recording. Decode one
manually to confirm it plays:

```
python3 -m pendant.cli decode data/recordings/<date>/<file>.opus
```

That produces a `.wav` file next to it - double-click to play in QuickTime.

## Everyday use (Phase 4/5)

Once Phase 1-3 are confirmed working, day to day you can just:

```
python3 -m pendant.cli sync
python3 -m pendant.cli transcribe 2026-09-13
```

(replace the date with today's), or simpler, double-click **Sync
Pendant.command** in Finder - it does both steps and tells you where the
transcript landed (`data/transcripts/<date>.md`).

## Troubleshooting

- **"Device not found" during scan:** make sure the Pendant is powered on and
  awake (tap it), and isn't currently connected to your phone via the
  official Limitless app - only one device can hold the BLE connection at a
  time.
- **Everything logs to `data/logs/`** - if something goes wrong, the easiest
  way to report it is to attach the newest file from that folder.
- **`opuslib` / decode errors:** confirm `brew install opus` was run - the
  Python `opuslib` package needs the system Opus library.
