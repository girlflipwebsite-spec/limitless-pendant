"""Local web interface: browse recorded dates, sync, and export a
transcript or combined audio by picking dates - no CLI commands to type.

Runs only on 127.0.0.1 (localhost) - never reachable from the network, no
accounts, nothing uploaded anywhere. It's a friendlier front end over the
exact same safe, already-audited functions the CLI uses (pendant/ble_client.py,
pendant/transcript_export.py, pendant/audio_export.py) - this file adds no
new way to talk to the Pendant, it only calls the existing sync_recordings(),
which is itself restricted to protocol.ALLOWED_COMMANDS.

Exports run the real CLI commands (`transcribe`, `combine-audio`) in a
separate process rather than in a thread of this server - see pendant/jobs.py.
"""

import asyncio
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from .ble_errors import friendly_ble_error
from .config import RECORDINGS_DIR, get_pendant_address
from .jobs import Job, cli_command, get_job, start_job, start_process_job

app = Flask(__name__)


def _available_dates() -> list[str]:
    if not RECORDINGS_DIR.exists():
        return []
    return sorted((p.name for p in RECORDINGS_DIR.iterdir() if p.is_dir()), reverse=True)


def _start_cli_job(key: str, params: dict, *cli_args: str):
    """Run a CLI command (transcribe / combine-audio) as a separate process.
    A function of its own so tests can swap in an in-process runner."""
    return start_process_job(cli_command(*cli_args), key=key, params=params)


def _job_response(job_id: str, started_new: bool):
    """Response for starting a job. If a job of the same kind was already
    running we hand back that job (and what it's doing) instead of a new one."""
    body = {"job_id": job_id, "already_running": not started_new}
    if not started_new:
        existing = get_job(job_id)
        body["params"] = existing.params if existing is not None else None
    return jsonify(body)


PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Limitless Pendant</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; color: #222; }
  h1 { font-size: 1.4rem; }
  h2 { font-size: 1.1rem; margin-top: 2rem; }
  button { background: #222; color: #fff; border: none; padding: 0.6rem 1.2rem; border-radius: 6px; cursor: pointer; font-size: 0.95rem; }
  button:disabled { background: #999; cursor: default; }
  input[type=date], select { padding: 0.4rem; border-radius: 6px; border: 1px solid #ccc; }
  .row { display: flex; gap: 0.75rem; align-items: center; margin: 0.75rem 0; flex-wrap: wrap; }
  .card { border: 1px solid #ddd; border-radius: 10px; padding: 1rem 1.25rem; margin-top: 1rem; }
  .status { font-size: 0.9rem; color: #555; white-space: pre-wrap; }
  .log { display: none; font-size: 0.75rem; color: #555; background: #f6f6f6; border-radius: 6px; padding: 0.5rem; max-height: 10rem; overflow: auto; white-space: pre-wrap; }
  .ok { color: #1a7f37; }
  .err { color: #c0392b; }
  a.download { display: inline-block; margin-top: 0.5rem; }
  .dates { font-size: 0.85rem; color: #666; }
</style>
</head>
<body>
<h1>Limitless Pendant</h1>

<div class="card">
  <h2>Sync</h2>
  <p>Downloads any new recordings from the Pendant. Never deletes anything from the device.</p>
  <button id="syncBtn" onclick="runSync()">Sync Pendant</button>
  <div id="syncStatus" class="status"></div>
  <pre id="syncLog" class="log"></pre>
</div>

<div class="card">
  <h2>Export transcript</h2>
  <p>Pick a date, or a date range for a whole week/month combined.</p>
  <div class="row">
    <label>From <input type="date" id="t_start"></label>
    <label>To (optional) <input type="date" id="t_end"></label>
    <select id="t_format">
      <option value="md">Markdown (.md)</option>
      <option value="txt">Plain text (.txt)</option>
      <option value="json">JSON (.json)</option>
    </select>
    <button id="transcriptBtn" onclick="runExport('transcript')">Export</button>
  </div>
  <div id="transcriptStatus" class="status"></div>
  <pre id="transcriptLog" class="log"></pre>
</div>

<div class="card">
  <h2>Export combined audio</h2>
  <p>Joins that day's (or range's) recordings into one playable file.</p>
  <div class="row">
    <label>From <input type="date" id="a_start"></label>
    <label>To (optional) <input type="date" id="a_end"></label>
    <button id="audioBtn" onclick="runExport('audio')">Export</button>
  </div>
  <div id="audioStatus" class="status"></div>
  <pre id="audioLog" class="log"></pre>
</div>

<div class="card">
  <h2>Recordings available</h2>
  <div class="dates">{{ dates_text }}</div>
</div>

<script>
const LOST = 'Lost connection to the local server. Check that the Terminal window running the app is still open, then reload this page.';

function getJson(url, options) {
  return fetch(url, options).then(r => r.json());
}

function showLog(logEl, lines) {
  if (!logEl) return;
  logEl.textContent = (lines || []).join('\\n');
  logEl.style.display = lines && lines.length ? 'block' : 'none';
  logEl.scrollTop = logEl.scrollHeight;
}

function lastProgress(lines) {
  // Newest line that isn't an indented stack-trace line.
  for (let i = (lines || []).length - 1; i >= 0; i--) {
    if (!/^\\s/.test(lines[i])) return lines[i];
  }
  return '';
}

function poll(jobId, statusEl, logEl, onDone, onFail, note) {
  getJson('/jobs/' + jobId).then(data => {
    showLog(logEl, data.log);
    if (data.status === 'running') {
      statusEl.className = 'status';
      statusEl.textContent = (note ? note + '\\n' : '') + 'Working... ' + lastProgress(data.log);
      setTimeout(() => poll(jobId, statusEl, logEl, onDone, onFail, note), 1000);
    } else if (data.status === 'done') {
      onDone(statusEl, data.result, jobId);
    } else {
      statusEl.className = 'status err';
      statusEl.textContent = 'Failed: ' + data.error;
      onFail();
    }
  }).catch(() => {
    statusEl.className = 'status err';
    statusEl.textContent = LOST;
    onFail();
  });
}

function describe(p) {
  if (!p || !p.start_date) return 'another request';
  return p.start_date + (p.end_date && p.end_date !== p.start_date ? ' to ' + p.end_date : '');
}

function runSync() {
  const btn = document.getElementById('syncBtn');
  const statusEl = document.getElementById('syncStatus');
  const logEl = document.getElementById('syncLog');
  btn.disabled = true;
  statusEl.className = 'status';
  statusEl.textContent = 'Connecting...';
  const enable = () => { btn.disabled = false; };
  getJson('/sync', { method: 'POST' }).then(data => {
    poll(data.job_id, statusEl, logEl, (el, result) => {
      enable();
      el.className = 'status ok';
      el.textContent = 'Done. Pages: ' + result.pages_received + ' (' + result.pages_new + ' new). Recordings saved: ' + result.recordings_saved +
        (result.any_encrypted ? '\\n[!] Some recordings are encrypted - see the developer before doing anything else.' : '');
    }, enable);
  }).catch(() => { enable(); statusEl.className = 'status err'; statusEl.textContent = LOST; });
}

function runExport(kind) {
  const prefix = kind === 'transcript' ? 't_' : 'a_';
  const statusEl = document.getElementById(kind + 'Status');
  const logEl = document.getElementById(kind + 'Log');
  const btn = document.getElementById(kind + 'Btn');
  const start = document.getElementById(prefix + 'start').value;
  const end = document.getElementById(prefix + 'end').value;
  if (!start) { statusEl.className = 'status err'; statusEl.textContent = 'Pick a start date first.'; return; }
  const body = new URLSearchParams({ start_date: start, end_date: end || start });
  if (kind === 'transcript') body.append('format', document.getElementById('t_format').value);
  btn.disabled = true;
  showLog(logEl, []);
  statusEl.className = 'status';
  statusEl.textContent = 'Working...';
  const enable = () => { btn.disabled = false; };
  getJson('/export/' + kind, { method: 'POST', body }).then(data => {
    if (data.error) { enable(); statusEl.className = 'status err'; statusEl.textContent = data.error; return; }
    const note = data.already_running
      ? 'An export for ' + describe(data.params) + ' is already running - showing its progress.'
      : '';
    poll(data.job_id, statusEl, logEl, (el, result, jobId) => {
      enable();
      el.className = 'status ok';
      el.textContent = 'Done: ' + result.filename + '  ';
      const a = document.createElement('a');
      a.className = 'download';
      a.href = '/download/' + jobId;
      a.textContent = 'Download';
      el.appendChild(a);
    }, enable, note);
  }).catch(() => { enable(); statusEl.className = 'status err'; statusEl.textContent = LOST; });
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    dates = _available_dates()
    dates_text = ", ".join(dates) if dates else "None yet - run Sync first."
    return PAGE.replace("{{ dates_text }}", dates_text)


@app.route("/sync", methods=["POST"])
def sync_route():
    def task(job: Job) -> dict:
        from .ble_client import PendantClient
        from .sync_state import SyncState

        address = get_pendant_address()
        client = PendantClient(address, log=job.log_line)

        async def run():
            connected = await client.connect()
            if not connected:
                raise RuntimeError("Could not connect to the Pendant - see the log for details.")
            try:
                await client.sync_time()
                state = SyncState()
                result = await client.sync_recordings(state)
                return {
                    "pages_received": result.pages_received,
                    "pages_new": result.pages_new,
                    "recordings_saved": len(result.recordings_saved),
                    "any_encrypted": result.any_encrypted,
                }
            finally:
                await client.disconnect()

        try:
            return asyncio.run(run())
        except Exception as exc:
            help_text = friendly_ble_error(exc)
            if help_text is None:
                raise
            raise RuntimeError(help_text) from exc

    job_id, started_new = start_job(task, key="sync", params={})
    return _job_response(job_id, started_new)


def _export_dates():
    start_date = request.form.get("start_date", "")
    end_date = request.form.get("end_date") or start_date
    return start_date, end_date


@app.route("/export/transcript", methods=["POST"])
def export_transcript_route():
    start_date, end_date = _export_dates()
    output_format = request.form.get("format", "md")
    if not start_date:
        return jsonify({"error": "Pick a start date first."}), 400
    if output_format not in ("md", "txt", "json"):
        return jsonify({"error": f"Unknown format {output_format!r}"}), 400

    params = {"start_date": start_date, "end_date": end_date, "format": output_format}
    args = ["transcribe", start_date, "--format", output_format]
    if end_date != start_date:
        args += ["--to", end_date]
    job_id, started_new = _start_cli_job("export:transcript", params, *args)
    return _job_response(job_id, started_new)


@app.route("/export/audio", methods=["POST"])
def export_audio_route():
    start_date, end_date = _export_dates()
    if not start_date:
        return jsonify({"error": "Pick a start date first."}), 400

    params = {"start_date": start_date, "end_date": end_date}
    job_id, started_new = _start_cli_job(
        "export:audio", params, "combine-audio", start_date, "--to", end_date
    )
    return _job_response(job_id, started_new)


@app.route("/jobs/<job_id>")
def job_status_route(job_id):
    job = get_job(job_id)
    if job is None:
        return jsonify({"status": "error", "error": "Unknown job", "log": []}), 404
    return jsonify({"status": job.status, "result": job.result, "error": job.error, "log": job.log})


@app.route("/download/<job_id>")
def download_route(job_id):
    """Serves the file a completed export job produced. The path always
    comes from the job's own result (computed server-side by our own export
    functions), never from user input, so there's no path-traversal risk."""
    job = get_job(job_id)
    if job is None or job.status != "done" or not job.result or "path" not in job.result:
        return "File not found", 404
    path = Path(job.result["path"])
    if not path.exists():
        return "File not found", 404
    return send_file(path, as_attachment=True, download_name=path.name)


def run(host: str = "127.0.0.1", port: int = 5151) -> None:
    app.run(host=host, port=port, debug=False)
