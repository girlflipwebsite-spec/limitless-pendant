# Limitless Pendant Independence Project

**Goal:** Build a small macOS utility that connects directly to a Limitless Pendant over Bluetooth, downloads recordings, saves them locally, transcribes them, and produces a clean daily transcript, without depending on the Limitless cloud service (which is discontinuing Pendant support).

Target pipeline:

```
Limitless Pendant -> Mac (local BLE app) -> local audio files -> local transcript -> ChatGPT (manual upload)
```

Not this anymore:

```
Limitless Pendant -> Limitless servers -> export -> ChatGPT
```

---

## 1. Project Summary

The client owns a Limitless Pendant (no longer manufactured). Limitless is ending Pendant support. The client wants to keep using the physical hardware by talking to it directly over Bluetooth instead of through Limitless's app/cloud.

This is not a from-scratch reverse engineering project. Other developers have already reverse engineered the Pendant's BLE protocol. The job here is to adapt and build on that existing work, not to redo it.

## 2. What the Finished Tool Should Do

1. Open the app, Pendant shows as connected
2. Click "Sync Pendant"
3. Downloads all NEW recordings not already downloaded
4. Saves original audio locally, organized by date
5. Preserves accurate recording timestamps
6. Transcribes the recordings
7. Produces one clean daily transcript/export file (TXT, Markdown, or JSON) ready to paste/upload into ChatGPT

## 3. Explicit Non-Goals (do not build these)

- AI summaries inside the app
- A chatbot
- A cloud dashboard
- User accounts
- A social network
- A mobile app
- Fancy graphics/UI polish
- Anything resembling Omi

ChatGPT handles the intelligence layer after the transcript exists. This app's only job is: connect, download, organize, transcribe, export.

## 4. Hard Safety Rules (non-negotiable without explicit client discussion first)

The Pendant is discontinued hardware and effectively irreplaceable. Until told otherwise:

- Read-only wherever possible
- Do NOT factory reset the device
- Do NOT erase recordings from the device
- Do NOT flash or modify firmware
- Do NOT change the device's encryption key ("rekey") without stopping and discussing it with the client first
- Do NOT make destructive Bluetooth pairing changes
- Do NOT do anything that could stop the Pendant from continuing to work with the official Limitless app
- The client will keep using the official Limitless app during development, testing must not interfere with that

If any step in the plan below requires breaking one of these rules, stop and flag it instead of proceeding.

**How the code enforces this today:** `pendant/protocol.py` has an explicit
`ALLOWED_COMMANDS` allowlist (info/status/clock-sync/download only) and
`create_command()` refuses anything outside it with a `ValueError`. The CLI
(`pendant/cli.py`) never calls factory-reset, storage-clear, rekey, or
firmware-update commands. `proto/pendant.proto` still defines those message
types (needed to correctly parse/ignore them if the device ever sends
related fields), but nothing in this codebase constructs or sends them.

## 5. Team & Workflow Reality

- **Developer:** works on a Windows PC, uses Claude Code, does not own a Mac and does not have physical access to the Pendant.
- **Client:** owns the Mac and the physical Pendant, is the hardware tester. Will run builds, send screenshots/logs/screen recordings/error messages, and is available for a screen-share call when needed.
- **Implication:** Anything that needs actual Bluetooth communication with the actual Pendant can only be verified on the client's machine. Development should be structured to minimize how often that loop is needed (see Section 8).

### Practical setup

- Use **Python**, not Swift/native macOS, for the core engine (BLE, protocol, audio, transcript logic). Python is not compiled, so the exact same source the developer writes on Windows runs unchanged on the client's Mac. No Xcode, no Mac build machine needed for this part.
- Use a **private GitHub repo** as the handoff mechanism. Developer pushes changes; client runs `git pull` and re-runs the script. Cleaner than sending zip files back and forth.
- Client needs Python 3.11+ installed on the Mac (`python3 --version` to check, install via python.org or Homebrew if missing), then `pip install -r requirements.txt`, then run the script.
- For Phase 5's "one button" feel: a simple `.command` file (double-clickable on macOS, just runs a shell command) is enough. Building a full native `.app` bundle is not necessary and is not something the developer can produce without a Mac anyway.

## 6. Budget & Timeline

- Rate: $5/hour
- Hard cap: 30 hours / $150 total, do not exceed without asking first
- **Checkpoint at hour 16:** by this point, either (a) at least one real recording has been successfully downloaded and turned into a playable audio file, or (b) there is a very clear, specific understanding of exactly what is blocking that. If neither, stop and reassess before continuing.
- Note: this rate is low for the specialized skill mix this project actually needs (BLE protocol work, encryption, cross-platform Bluetooth debugging). Worth keeping in mind if scope creeps.

## 7. Research Findings (already done, don't redo this)

### 7.1 Reference implementation

**https://github.com/sdelcore/pendant-cli**

Python CLI tool that already reverse-engineered the Pendant's BLE protocol from the Limitless Android app (v2.1.6). Treated as the primary reference for this project (cloned locally under `.reference/pendant-cli`, gitignored - not part of this repo's own history). This project's code is a fresh, macOS/bleak-only implementation informed by that research, not a copy of their Linux/D-Bus-based code.

Full protocol is documented in that repo's `PROTOCOL.md` (BLE characteristic UUIDs, protobuf message definitions, message fragmentation format).

### 7.2 Platform gap

`pendant-cli` targets **Linux** (uses `bluetoothctl`/BlueZ via `dbus-python` and `PyGObject` for pairing). Its BLE library, `bleak`, is cross-platform and does support macOS (via CoreBluetooth). This project uses bleak directly with no Linux-specific dependencies. Pairing/bonding on macOS is expected to happen once via System Settings > Bluetooth before the script connects (see `pendant/ble_client.py` module docstring) - **this needs to be verified on the client's actual Mac**, it's the first open question for Phase 1.

### 7.3 Excluded alternative: firmware-based approach

**https://github.com/shade-familiar/limitless-libre** exists (open-source firmware for the Pendant's nRF5340 chip). Not used here, it requires flashing new firmware, which violates the safety rules in Section 4. Mentioned here only so it's not "rediscovered" and accidentally pursued later.

### 7.4 The single biggest open question: audio encryption

Per the protocol docs, the Pendant supports **optional** audio encryption (X25519 key exchange + ChaCha20-Poly1305). The audio payload can arrive in one of two protobuf fields:

- `codec_beamforming_data` - plain Opus, directly decodable, no issue
- `encrypted_codec_beamforming_data` - locked, needs a private key to decrypt

If this specific Pendant has encryption turned on (tied to Limitless's own server key):

- Downloaded recordings will be unreadable ciphertext, not playable audio
- The only way to decrypt is to inject a new key pair onto the device (a "rekey"), which Section 4 says not to do without discussion
- Rekeying makes ALL existing recordings on the device permanently undecryptable (Limitless's private key is never available to us), only recordings made after the rekey would be readable
- It's unconfirmed whether rekeying would break the official Limitless app's ability to sync future recordings, this needs to be treated as a real risk, not assumed away

**This is exactly what the hour-16 checkpoint is for.** Phase 1 should determine which of the two fields is actually populated on this Pendant before any further time is spent. If encrypted, that's a decision point for the client (Section 9), not a coding problem to solve unilaterally.

**Current implementation status:** `pendant/protocol.py`'s `extract_audio_from_flash_page()` detects and reports which field is populated per chunk, and `pendant sync` prints an explicit warning + summary if any recording comes back encrypted. No decryption or key-injection code exists in this repo at all - that's deliberately left unimplemented pending a client decision.

## 8. Phased Build Plan

Work that can be built and tested on Windows without the client (no hardware needed):

- Protobuf message construction/parsing (using the `.proto` definitions from `pendant-cli`)
- Opus-to-WAV decoding logic (test against sample/dummy Opus files)
- Timestamp math and date-based folder organization
- Transcript formatting/export (TXT/Markdown/JSON)
- Sync-state tracking (remembering what's already downloaded)

Work that can only be tested on the client's Mac with the real Pendant:

- BLE scan/pair/connect on macOS
- Reading device info/status
- Downloading real flash pages
- Checking which audio field is populated (the encryption question, Section 7.4)
- Anything involving actual timing/reliability of the real device

### Phase 1: Detection & Diagnostics

- Clone and study `pendant-cli`
- Port scan/connect logic toward macOS (via `bleak`)
- Get device info/status reading working (battery, firmware, storage, recording state)
- Generate detailed logs for the client to send back
- Read-only only

### Phase 2: Critical Milestone, One Recording

- Client makes a short test recording
- Download it, determine encrypted vs plain audio field
- If plain: decode to a playable WAV file, confirm approximate timestamp
- If encrypted: STOP, report findings, bring the rekey tradeoff to the client for a decision (do not decide unilaterally)

### Phase 3: Reliable Sync

- Track already-downloaded recordings (avoid re-downloading)
- Save originals locally, organized into date folders

### Phase 4: Transcription

- Add transcription (local Whisper/whisper.cpp or an API, developer's call based on cost/quality)
- One clean daily transcript with timestamps

### Phase 5: Simple Interface

- One-button "Sync Pendant" experience
- A `.command` launcher or minimal GUI is enough, no need for a compiled native app

## 9. Decision Points Reserved for the Client

Do not resolve these unilaterally in code, surface them and wait for an answer:

- Whether to rekey the device if recordings turn out to be encrypted (Section 7.4), including accepting that old recordings become permanently unreadable and that the official app's future behavior is uncertain
- Any pairing change that risks disrupting current use of the official Limitless app
- Any step that isn't strictly read-only

## 10. Working Agreement for Claude Code

- Read this entire file before writing code.
- Treat Section 4 (Hard Safety Rules) as absolute. If a task seems to require violating one, stop and explain the tradeoff instead of proceeding.
- Build and test everything in Section 8's "no hardware needed" list independently first.
- For anything needing the real Pendant, prepare clear step-by-step instructions and specific log output to request from the client, then wait for their reply before continuing.
- Track rough hours spent per session against the 30-hour cap and flag it if getting close.
- Report the Section 7.4 encryption finding clearly and explicitly as soon as it's known, this changes the rest of the project's scope.

## 11. Current Status (update this as work progresses)

**Phase 1 code complete, not yet hardware-tested.** Built and unit-tested on Windows (no Pendant available here):

- `proto/pendant.proto` + generated `proto/pendant_pb2.py` - full wire protocol
- `pendant/protocol.py` - BLE envelope framing, restricted command builder (see Section 4 above), response parsing, flash-page audio extraction with encryption detection
- `pendant/ble_client.py` - bleak-based scan/connect/status/info/sync client for macOS
- `pendant/opus_decoder.py` - raw Opus frame boundary detection + decode to WAV
- `pendant/audio_store.py` - groups downloaded pages into recordings, saves them into `data/recordings/<YYYY-MM-DD>/`
- `pendant/sync_state.py` - tracks already-downloaded pages so re-running sync doesn't re-save them
- `pendant/transcribe.py` + `pendant/transcript_export.py` - local Whisper transcription (Phase 4), daily Markdown/TXT/JSON export
- `pendant/cli.py` - `scan`, `status`, `info`, `sync`, `decode`, `transcribe` commands, each writing a session log to `data/logs/`
- `Sync Pendant.command` - Phase 5 one-button launcher
- `tests/` - protocol, sync-state, and audio-store unit tests all pass on Windows with no hardware; an Opus round-trip test is included but skips unless real libopus is installed (it will run on the client's Mac)

**Not yet known:** whether macOS bonding via System Settings is sufficient for the device to respond to commands (Section 7.2), and whether this Pendant's recordings are encrypted (Section 7.4). Both require the client's Mac - see README.md "First run on your Mac" for the exact steps and what to send back.

**Hours so far:** ~1 session of initial build-out (proto/protocol/BLE client/audio pipeline/tests/docs). Nowhere near the 30-hour cap yet; the hour-16 checkpoint has not been reached because no hardware test has happened yet.
