# Limitless Pendant - Local Tool

**A complete, step-by-step manual for setting up and testing this tool on your Mac.**

Connects directly to your Limitless Pendant over Bluetooth, downloads
recordings, saves them on your Mac organized by date, transcribes them, and
produces one clean daily transcript file you can paste or upload into
ChatGPT. No Limitless cloud account needed.

This tool is **read-only** with respect to the device: it never deletes
recordings, resets, or reconfigures the Pendant, and it never touches the
official Limitless app. See `CLAUDE.md` Section 4 for the full safety rules
this project follows if you want the details.

## Contents

1. [What you'll need](#1-what-youll-need)
2. [One-time setup](#2-one-time-setup)
3. [First run: connecting to the Pendant](#3-first-run-connecting-to-the-pendant)
4. [Downloading recordings](#4-downloading-recordings)
5. [Transcribing recordings](#5-transcribing-recordings)
6. [Everyday use (the one-button way)](#6-everyday-use-the-one-button-way)
7. [Command reference](#7-command-reference)
8. [Where your files live](#8-where-your-files-live)
9. [Troubleshooting](#9-troubleshooting)
10. [FAQ](#10-faq)
11. [Getting help](#11-getting-help)

---

## 1. What you'll need

- A Mac (any recent macOS version)
- Your Limitless Pendant, charged
- Access to this private repo: `https://github.com/girlflipwebsite-spec/limitless-pendant`
  (you'll need a GitHub account invited as a collaborator - ask if you don't have one yet)
- About 15 minutes for one-time setup

## 2. One-time setup

Open the **Terminal** app (Applications > Utilities > Terminal, or search
"Terminal" in Spotlight). Every command below is typed into Terminal and
followed by Enter.

### 2.1 Check Python

```bash
python3 --version
```

You need **3.11 or newer**. If it's missing or older:
- Easiest: install from [python.org/downloads](https://www.python.org/downloads/) (download the macOS installer, run it like any app)
- Alternative if you use Homebrew: `brew install python@3.12`

### 2.2 Get the code

```bash
git clone https://github.com/girlflipwebsite-spec/limitless-pendant.git
cd limitless-pendant
```

This creates a `limitless-pendant` folder and moves your Terminal into it.
**Stay in this folder for every command below** - if you close Terminal and
reopen it later, run `cd limitless-pendant` again first (or `cd path/to/limitless-pendant` if you're not in your home folder).

Whenever you're told there's an update, come back to this folder and run:
```bash
git pull
```

### 2.3 Install the audio library

```bash
brew install opus
```

(If you don't have Homebrew, install it first from [brew.sh](https://brew.sh) - it's one copy-pasted command on that page.)

### 2.4 Install the Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The `source .venv/bin/activate` step needs to be run **every time you open a
new Terminal window** before running any `python3 -m pendant.cli ...`
command below. You'll know it worked because your prompt line gets a
`(.venv)` prefix.

### 2.5 Pair the Pendant with your Mac

This is a **one-time** step, done the normal macOS way, not through this
tool:

1. Open **System Settings > Bluetooth**
2. Put the Pendant into pairing mode (check its manual or LED behavior for how)
3. When it shows up in the device list, click **Connect**

Do this even though the Pendant won't "stay connected" in that list
afterward - what matters is that macOS now has a Bluetooth bond with it,
which is what lets this tool talk to it later.

Setup is done. Move to Section 3.

---

## 3. First run: connecting to the Pendant

This is the most important part to test carefully - it confirms the basic
connection works before we try anything else. Do these one at a time, in
order, and don't skip ahead if one fails.

Make sure you're in the `limitless-pendant` folder with the virtual
environment active (prompt shows `(.venv)` - if not, run
`source .venv/bin/activate`).

### 3.1 Scan

```bash
python3 -m pendant.cli scan
```

**What should happen:** within about 10 seconds, you'll see a list of nearby
Bluetooth devices, with something like this for the Pendant:

```
Pendant devices found:
  XX:XX:XX:XX:XX:XX  Pendant  (RSSI -50)  [name match]

Set this before running other commands:
  export PENDANT_ADDRESS="XX:XX:XX:XX:XX:XX"
```

**What to do:** copy that `export PENDANT_ADDRESS="..."` line exactly and
run it in the same Terminal window. This tells the tool which device to talk
to for the rest of your session.

To make this permanent (so you don't retype it every time), also add that
same line to the end of your `~/.zshrc` file.

**If no Pendant is found:** make sure it's powered on and awake (tap it),
and that it isn't currently connected to your phone via the official
Limitless app - see [Troubleshooting](#9-troubleshooting).

### 3.2 Status

```bash
python3 -m pendant.cli status
```

**What should happen:** a short report like:

```
Recording: False
Storage used: 12%
Wifi connected: False
Battery: 84% (charging=False)
```

### 3.3 Info

```bash
python3 -m pendant.cli info
```

**What should happen:**

```
Device name: Pendant
Firmware: 2.1.6
Hardware: rev-b
Serial: XXXXXXXX
```

### 3.4 What to send back

Whatever happens - success, an error message, or it just hanging - **please
report back with:**
- Whether `scan` found the device
- Whether `status` and `info` printed real values, or hung, or errored
- Attach the newest 3 files under the `data/logs/` folder (every command
  saves its own log there automatically, so you don't need to copy-paste
  from Terminal - just find those files in Finder and send them)

This tells us whether pairing via System Settings alone is enough for the
Pendant to respond to commands - the first thing this project needs to
confirm.

---

## 4. Downloading recordings

Once `status` and `info` both work, you can download what's stored on the
device:

```bash
python3 -m pendant.cli sync
```

**What should happen:** it syncs the clock, downloads everything on the
device not already saved, and reports something like:

```
Pages received: 340
  new: 340  already downloaded: 0
Recordings saved: 3
  session 4 run 0: 120 pages -> data/recordings/2026-09-12/143201_s4r0.opus
  ...
```

Running `sync` again later only pulls new recordings since last time - it
never deletes anything from the device.

### If you see an "ENCRYPTED" warning

**Stop and send that log back before doing anything else.** It looks like
this:

```
    [!] this recording's audio is ENCRYPTED. Decrypting it requires
    injecting a new key onto the device (a 'rekey'), which the project's
    safety rules say NOT to do without discussing it with you first...
```

This means this specific Pendant has audio encryption turned on. Fixing that
requires a decision about the device (see `CLAUDE.md` Section 7.4/9) - please
don't run any further commands until that's been discussed.

### If it's not encrypted

You'll have `.opus` files under `data/recordings/<date>/`. Confirm one plays
back correctly:

```bash
python3 -m pendant.cli decode data/recordings/2026-09-12/143201_s4r0.opus
```

This creates a matching `.wav` file next to it - double-click it in Finder
to play it in QuickTime, and confirm the audio sounds right and roughly
matches when you actually recorded it.

---

## 5. Transcribing recordings

Once you've confirmed recordings download and play correctly:

```bash
python3 -m pendant.cli transcribe 2026-09-12
```

(replace the date with the one you want). The first time you run this it
will download a small speech-recognition model (one-time, needs internet;
after that, transcription itself runs fully offline on your Mac).

This writes one clean transcript file to `data/transcripts/2026-09-12.md`,
combining every recording from that day in order, with timestamps - ready to
paste or upload into ChatGPT.

---

## 6. Everyday use (the one-button way)

Once Sections 3-5 are all confirmed working, day-to-day use is one
double-click:

**Double-click `Sync Pendant.command`** in Finder (inside the
`limitless-pendant` folder). It downloads any new recordings and updates
today's transcript automatically, then tells you where to find it.

(The first time, macOS may warn "unidentified developer" - right-click the
file, choose **Open**, and confirm once; it will run normally after that.)

---

## 7. Command reference

All commands start with `python3 -m pendant.cli` and need the virtual
environment active (`source .venv/bin/activate`) and `PENDANT_ADDRESS` set
(from `scan`).

| Command | What it does | Touches the device? |
|---|---|---|
| `scan` | Lists nearby Bluetooth devices, flags the Pendant | No (listen-only) |
| `status` | Battery %, storage %, recording state | Read-only |
| `info` | Firmware/hardware/serial number | Read-only |
| `sync` | Downloads new recordings, saves to `data/recordings/` | Read-only download |
| `decode <file.opus>` | Converts one recording to a playable `.wav` | No (local file only) |
| `transcribe <YYYY-MM-DD>` | Builds that day's transcript file | No (local files only) |

None of these commands can delete, reset, or reconfigure the Pendant - that
capability doesn't exist in this tool at all (see `CLAUDE.md` Section 4).

---

## 8. Where your files live

Everything lives under a `data/` folder inside `limitless-pendant/` (created
automatically, never uploaded anywhere):

```
data/
  recordings/<YYYY-MM-DD>/    original .opus + .wav recordings, one folder per day
  transcripts/<YYYY-MM-DD>.md the daily transcript, ready for ChatGPT
  logs/                       one log file per command you've run
  sync_state.json             tracks what's already been downloaded
```

This whole `data/` folder is yours - back it up however you'd like (Time
Machine, iCloud Drive, copying it elsewhere). It's excluded from git, so it
never gets uploaded to the code repository.

---

## 9. Troubleshooting

- **"Device not found" during scan:** make sure the Pendant is powered on and
  awake (tap it), and isn't currently connected to your phone via the
  official Limitless app - only one device can hold the Bluetooth connection
  at a time.
- **`status`/`info` hang after `scan` succeeds:** this is exactly the kind
  of thing to report back (see [3.4](#34-what-to-send-back)) - it likely
  means pairing via System Settings needs an extra step we haven't
  accounted for yet.
- **Everything logs to `data/logs/`:** if anything goes wrong, the easiest
  way to report it is to attach the newest file(s) from that folder rather
  than copy-pasting Terminal output.
- **`opuslib` / decode errors:** confirm `brew install opus` was run - the
  Python `opuslib` package needs the system Opus library installed
  separately.
- **"command not found: python3"**: Python isn't installed or isn't on your
  PATH - revisit [2.1](#21-check-python).
- **Forgot to activate the virtual environment:** if you see
  `ModuleNotFoundError`, run `source .venv/bin/activate` again (must be done
  in every new Terminal window).
- **"unidentified developer" warning on `Sync Pendant.command`:**
  right-click it and choose **Open** instead of double-clicking, then
  confirm once - macOS only asks this the first time.

---

## 10. FAQ

**Does this stop me from using the official Limitless app?**
No changes are made to pairing or the device's configuration, so the
official app should keep working exactly as before. If you notice any
interference, stop and report it immediately.

**Can this delete my recordings from the Pendant?**
No. There is no delete/erase/factory-reset code path anywhere in this tool
- it's a permanent design decision, not a setting you could accidentally
change.

**What if my recordings come back encrypted?**
Stop and don't run further `sync` commands - see
[Section 4](#4-downloading-recordings). Decrypting requires a real decision
about the device that needs to be made together, not something the tool
does automatically.

**Where does the transcription happen - is my audio sent anywhere?**
Transcription runs locally on your Mac (via a local speech-recognition
model). Nothing is uploaded to any cloud service by this tool. You choose
when and what to paste into ChatGPT yourself.

**Do I need to keep the Terminal window open all the time?**
No - only while a command is actively running. You can close Terminal
between syncs.

---

## 11. Getting help

If anything doesn't work as described above:
1. Find the newest file(s) in `data/logs/` from the command that had a problem
2. Send those log files, plus a short description of what you expected vs.
   what happened
3. A screen-share call can also help for anything hard to describe in text
