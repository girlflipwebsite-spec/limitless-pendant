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

`pendant-cli` targets **Linux** (uses `bluetoothctl`/BlueZ via `dbus-python` and `PyGObject` for pairing). Its BLE library, `bleak`, is cross-platform and does support macOS (via CoreBluetooth). This project uses bleak directly with no Linux-specific dependencies.

**Resolved (2026-09-27):** confirmed on real hardware. `scan()` + `connect()` alone are sufficient - no pairing/bonding step of any kind, manual or automatic, is needed. The client also confirmed the Pendant never appears in System Settings > Bluetooth at all (it's BLE-only, not a classic audio/HID device), so manual pairing was never available as an option anyway. The actual blocker that looked like a bonding/pairing issue (commands sent successfully but no response ever came back) turned out to be unrelated: the Control characteristic needed a real GATT Write Request (`response=True`) rather than write-without-response, which the device's application layer was silently never receiving. See `pendant/ble_client.py::_send()`.

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

**Resolved:** a direct BLE connection from a Mac (scan + connect, no pairing of any kind) is sufficient for the device to respond to commands - confirmed on the client's real hardware (see the 2026-09-27 entries below). **Still not known:** whether this Pendant's recordings are encrypted (Section 7.4) - that's the next thing Phase 2 needs to check once `sync` is confirmed working.

**2026-09-18 update:** client relayed Limitless's own support content confirming the Pendant is BLE-only and isn't manually paired via System Settings like a normal Bluetooth device (see Section 7.2). Removed the incorrect "pair via System Settings first" instruction from README.md and the corresponding assumption from `pendant/ble_client.py`'s docstring - the tool now relies on `scan` + `connect` alone, with any bonding expected to happen automatically (possibly via a one-time macOS pairing popup). Still unverified on real hardware.

**2026-09-27 update - first real hardware test:** client ran `python -m pendant.cli status` on their actual Mac and Pendant. Good news: `scan` + `connect` succeeded on the first real attempt - no manual System Settings pairing was needed, no exception, `start_notify` enabled fine. That resolves the Section 7.2 question in the "no pairing needed" direction.

New finding: after connecting, `get_device_status` was sent (write succeeded, no GATT error) but no `device_status` response ever came back within the 15s timeout, raising `asyncio.TimeoutError` in `pendant/ble_client.py::_request`. Per PROTOCOL.md's explicit warning ("The Pendant will NOT respond to any commands until it is properly bonded"), the leading theory is that the GATT-level connection succeeded but the device's firmware is still waiting on a lower-level bond/encryption handshake that a plain `connect()` doesn't trigger on macOS - CoreBluetooth only prompts for pairing when a characteristic explicitly requires it, and apparently this one doesn't in a way that's forcing that here. Not yet confirmed; could also be a missing handshake step (e.g. needing `SetCurrentTime` first) rather than bonding specifically.

Added in response, all pushed:
- `pendant/ble_client.py`: logs every sent command and every received notification (type + byte length), including partial fragments - previously silent, so the next log will show definitively whether the device replies with *anything* at all
- `pendant/cli.py`: `status`/`info`/`sync` now attempt a best-effort clock sync first (matching the documented flow) and, on a timeout, print concrete next steps (try pairing via System Settings as a fallback despite the above, tap the device awake, make sure it's not connected to the phone app) instead of a raw Python traceback

**2026-09-27 follow-up - confirmed with the debug logging:** client re-ran `status` with the updated code. MTU negotiated at 498, matching pendant-cli's documented `PREFERRED_MTU` ("matches Limitless app") - a good sign the BLE link itself behaves identically to the official app. Both `set_current_time` (18 bytes) and `get_device_status` (14 bytes) were sent successfully (no write error), but the new per-notification logging shows **zero** `[debug] received response...` or `[debug] received BLE fragment...` lines for either one - meaning literally nothing came back over the notify characteristic at all, for two different commands in a row. This is strong (not yet 100% certain) evidence for the bonding theory over a framing/encoding bug: our own protocol round-trip tests already pass, and PROTOCOL.md documents exactly this silent-ignore-until-bonded behavior.

Next step (on the client): try pairing the Pendant once via System Settings > Bluetooth (even though Section 7.2 says it may not show up there) and report exactly what happens - does it appear in the device list at all, under what name/section, and what happens on clicking Connect/Pair - then re-run `status`. This is now the most likely unblock; if the device doesn't even appear in System Settings, that's equally important information and means we need a different way to force bonding (there is no portable "pair now" call in bleak on macOS, unlike Android's `createBond()` that pendant-cli relies on for Linux).

**2026-09-27 follow-up 2 - System Settings dead end confirmed:** client checked - the Pendant does not appear in System Settings > Bluetooth at all, confirming it can't be manually paired that way (bleak's `pair()` is also a no-op/unimplemented on the macOS/CoreBluetooth backend, so there's no code-level "pair now" call either). Added `pendant explore` (`pendant/cli.py` + `PendantClient.explore_services()` in `pendant/ble_client.py`): a fully read-only command with no protocol commands sent at all, that lists every GATT service/characteristic the device actually exposes and attempts to read any standard (Bluetooth SIG) ones present, particularly the standard Battery Level characteristic (`0x2A19`) - PROTOCOL.md notes battery is read "reliably" from the standard Battery Service, and reading a characteristic that requires encryption is one of the few ways CoreBluetooth can be made to negotiate bonding automatically without an explicit pair API. Waiting on the client to run `explore` and send back its log - that tells us what's really on the device instead of guessing further from documentation alone.

**2026-09-27 follow-up 3 - explore results, and a real lead:** client ran `explore`. Findings:

- The device exposes a standard Battery Service (`0x180F`) with a readable Battery Level characteristic (`0x2A19`) - reading it **succeeded** with no pairing prompt and no error, returning `0x62` = 98%. This proves the BLE link and GATT layer are completely healthy; it also means reading a standard characteristic did *not* trigger bonding (it apparently doesn't require encryption either), so that specific idea didn't pan out.
- The custom service/characteristic layout matches PROTOCOL.md exactly: `632de001` (audio service) with `632de002` `[write, write-without-response]` (Control) and `632de003` `[notify]` (Data); plus the alternate data channel `8d53dc1d`/`da2e7828` `[notify, write-without-response]`.
- Manually re-verified our wire encoding byte-for-byte against the earlier log's exact sizes (18 bytes for `set_current_time`, 14 bytes for `get_device_status`) - both match a correct encoding exactly, field by field. This rules out a framing/encoding bug with very high confidence.

Combined, this narrows the problem precisely: the BLE connection, GATT discovery, and our message encoding are all confirmed correct; only the custom application-layer commands (via the `632de002`/`632de003` characteristics) get silently ignored. This is consistent with PROTOCOL.md's documented bonding gate applying specifically to the custom command processing, not to standard GATT services (which are likely handled by the BLE stack itself, independent of the Pendant's application firmware).

**Live lead, flagged rather than acted on:** `proto/pendant.proto` defines `SetBLEPair { bool enable = 1; }` (field 5 in `ServerCommandMsg`) - a command PROTOCOL.md documents in the schema but does NOT list among its "Verified Working Commands," and pendant-cli never needed it since Linux bonding was handled externally via `bluetoothctl`. This could plausibly be the exact handshake the Android app sends to get the Pendant to accept bonding/commands over BLE. **Not implemented or sent** - per Section 9 ("Any pairing change that risks disrupting current use of the official Limitless app" is a client decision point, not something to resolve unilaterally), this needs the client's go-ahead first, since we don't have confirmed semantics for this field beyond its name. Presented to the client as a question rather than shipped as code.

**2026-09-27 follow-up 4 - restart didn't help, testing write-with-response:** client restarted the Pendant and re-ran `info` - identical timeout, same as `status`. Rules out "stale connection state" and confirms this isn't command-specific (both `get_device_status` and `get_device_info` fail the same way).

Before touching anything pairing-related, tried one more pairing-neutral experiment: `explore` showed the Control characteristic (`632de002`) supports both `write` and `write-without-response`. Changed `PendantClient._send()` in `pendant/ble_client.py` to use `response=True` (a real GATT Write Request, which requires the peripheral's GATT server to acknowledge receipt) instead of `write-without-response` (fire-and-forget, no delivery confirmation). If this now raises an error, that's new information about delivery itself; if it succeeds but we still get no notification, it further confirms the gap is in command *processing* on the device, not delivery. Waiting on the client to re-run `info` with this change.

The developer separately raised trying `SetBLEPair` (a command in the protocol schema that may be the missing handshake) - **explicitly deferred pending the client's own go-ahead**, since it touches Bluetooth pairing behavior per Section 9, and the client hasn't been asked directly yet (this write-response experiment was tried first as a safer, pairing-neutral option).

**2026-09-27 follow-up 5 - PHASE 1 UNBLOCKED, `SetBLEPair` no longer needed:** the write-with-response change worked immediately. `info` now gets real responses back: `device_status`, `battery_status`, `set_current_time_response`, and `device_info` (200 bytes) all arrived. Bonding/pairing was never the actual problem - see the corrected Section 7.2 above. `SetBLEPair` does not need to be raised with the client at all; withdrawing that question.

One new, smaller bug found: the printed `info` output was wrong - `Device name`, `Firmware`, and `Hardware` all came back empty, while `Serial` showed `"1.1.20 b312ca1efaaa"`, which looks like a firmware-version-plus-build-hash string, not a serial number. This means `DeviceInfoMsg`'s field numbers in `proto/pendant.proto` (inherited as-is from pendant-cli's PROTOCOL.md) likely don't match this device's real firmware. Added raw hex-dump logging for every non-bulk response type in `pendant/ble_client.py::_notification_handler` (skips `storage_buffer` to avoid flooding the log during real downloads) specifically so the actual `device_info` bytes can be hand-decoded against the wire format and the schema corrected. Waiting on the client to re-run `info` once more so we get that raw hex.

Phase 1's core question (does a direct BLE connection from a Mac work at all) is now answered: **yes**.

**2026-09-27 follow-up 6 - device_info field mapping fixed:** hand-decoded the raw hex from the client's log (protobuf tag/wiretype walk) and confirmed pendant-cli's documented `DeviceInfoMsg` schema doesn't match this Pendant's real firmware (1.1.20) at all - most of PROTOCOL.md's assumed fields for this message either don't appear on the wire or appear with a different wire type than declared (e.g. the old field 4 `mac_address` shows up as a small varint, not bytes). Confirmed by direct decode: field 3 is a string containing `"1.1.20 b312ca1efaaa"` (firmware version + build hash) and field 9 is 6 raw bytes shaped like a MAC address. Updated `proto/pendant.proto`'s `DeviceInfoMsg` to only declare these two confirmed/best-guess fields (regenerated `pendant_pb2.py`), updated `pendant/protocol.py::parse_response` and `pendant/cli.py`'s `info` command to match, and verified against the actual captured payload - `info` now correctly prints the real firmware version and MAC. The rest of this message's real content (several more fields exist on the wire, including what looks like a nested status-shaped submessage and a 65-byte blob resembling an uncompressed EC public key) is left undeciphered since it doesn't block the mission-critical path.

Next: run `sync` for real and find out whether this Pendant's audio is encrypted (Section 7.4) - the hour-16-equivalent checkpoint.

**Hours so far:** ~2 sessions (initial build-out, then this round of hardware-informed fixes). Still nowhere near the 30-hour cap. The hour-16 checkpoint is not yet met - we have a real, verified-correct connection but no successful custom command response yet, so neither "a recording downloaded" nor "a fully clear picture of the blocker" is fully true yet - though the picture is now very narrow (see above).
