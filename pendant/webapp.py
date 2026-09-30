"""Local web interface: browse recorded dates, sync, and export a
transcript or combined audio by picking dates - no CLI commands to type.

Runs only on 127.0.0.1 (localhost) - never reachable from the network, no
accounts, nothing uploaded anywhere. It's a friendlier front end over the
exact same safe, already-audited functions the CLI uses (pendant/ble_client.py,
pendant/transcript_export.py, pendant/audio_export.py) - this file adds no
new way to talk to the Pendant, it only calls the existing sync_recordings(),
which is itself restricted to protocol.ALLOWED_COMMANDS.
"""

import asyncio
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from .config import RECORDINGS_DIR, get_pendant_address
from .jobs import Job, get_job, start_job

app = Flask(__name__)


def _available_dates() -> list[str]:
    if not RECORDINGS_DIR.exists():
        return []
    return sorted((p.name for p in RECORDINGS_DIR.iterdir() if p.is_dir()), reverse=True)


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
    <button onclick="runExport('transcript')">Export</button>
  </div>
  <div id="transcriptStatus" class="status"></div>
</div>

<div class="card">
  <h2>Export combined audio</h2>
  <p>Joins that day's (or range's) recordings into one playable file.</p>
  <div class="row">
    <label>From <input type="date" id="a_start"></label>
    <label>To (optional) <input type="date" id="a_end"></label>
    <button onclick="runExport('audio')">Export</button>
  </div>
  <div id="audioStatus" class="status"></div>
</div>

<div class="card">
  <h2>Recordings available</h2>
  <div class="dates">{{ dates_text }}</div>
</div>

<script>
function poll(jobId, statusEl, onDone) {
  fetch('/jobs/' + jobId).then(r => r.json()).then(data => {
    if (data.status === 'running') {
      statusEl.textContent = 'Working...';
      setTimeout(() => poll(jobId, statusEl, onDone), 1000);
    } else if (data.status === 'done') {
      onDone(statusEl, data.result, jobId);
    } else {
      statusEl.className = 'status err';
      statusEl.textContent = 'Failed: ' + data.error;
    }
  });
}

function runSync() {
  const btn = document.getElementById('syncBtn');
  const statusEl = document.getElementById('syncStatus');
  btn.disabled = true;
  statusEl.className = 'status';
  statusEl.textContent = 'Connecting...';
  fetch('/sync', { method: 'POST' }).then(r => r.json()).then(data => {
    poll(data.job_id, statusEl, (el, result) => {
      btn.disabled = false;
      el.className = 'status ok';
      el.textContent = 'Done. Pages: ' + result.pages_received + ' (' + result.pages_new + ' new). Recordings saved: ' + result.recordings_saved +
        (result.any_encrypted ? '\\n[!] Some recordings are encrypted - see the developer before doing anything else.' : '');
    });
  }).catch(() => { btn.disabled = false; statusEl.className = 'status err'; statusEl.textContent = 'Could not reach the local server.'; });
}

function runExport(kind) {
  const prefix = kind === 'transcript' ? 't_' : 'a_';
  const statusEl = document.getElementById(kind + 'Status');
  const start = document.getElementById(prefix + 'start').value;
  const end = document.getElementById(prefix + 'end').value;
  if (!start) { statusEl.className = 'status err'; statusEl.textContent = 'Pick a start date first.'; return; }
  const body = new URLSearchParams({ start_date: start, end_date: end || start });
  if (kind === 'transcript') body.append('format', document.getElementById('t_format').value);
  statusEl.className = 'status';
  statusEl.textContent = 'Working...';
  fetch('/export/' + kind, { method: 'POST', body }).then(r => r.json()).then(data => {
    poll(data.job_id, statusEl, (el, result, jobId) => {
      el.className = 'status ok';
      el.innerHTML = 'Done: ' + result.filename + '<br><a class="download" href="/download/' + jobId + '">Download</a>';
    });
  });
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

        return asyncio.run(run())

    return jsonify({"job_id": start_job(task)})


@app.route("/export/transcript", methods=["POST"])
def export_transcript_route():
    start_date = request.form["start_date"]
    end_date = request.form.get("end_date") or start_date
    output_format = request.form.get("format", "md")

    def task(job: Job) -> dict:
        if start_date == end_date:
            from .transcript_export import export_daily_transcript

            path = export_daily_transcript(start_date, output_format=output_format)
        else:
            from .transcript_export import export_transcript_range

            path = export_transcript_range(start_date, end_date, output_format=output_format)
        return {"path": str(path), "filename": path.name}

    return jsonify({"job_id": start_job(task)})


@app.route("/export/audio", methods=["POST"])
def export_audio_route():
    start_date = request.form["start_date"]
    end_date = request.form.get("end_date") or start_date

    def task(job: Job) -> dict:
        from .audio_export import combine_audio_range

        path = combine_audio_range(start_date, end_date)
        return {"path": str(path), "filename": path.name}

    return jsonify({"job_id": start_job(task)})


@app.route("/jobs/<job_id>")
def job_status_route(job_id):
    job = get_job(job_id)
    if job is None:
        return jsonify({"status": "error", "error": "Unknown job"}), 404
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
