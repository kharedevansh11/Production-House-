"""POST /talk {"image", "audio", "out"} -> runs SadTalker once, writes the talking-head mp4 to "out".

Paths are shared with the studio job through the /work volume. One request at a time, and the model is
loaded per request, so nothing stays on the 4 GB GPU between jobs.
"""

import json
import os
import shutil
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path("/work").resolve()


def inside_work(value: str) -> Path:
    path = Path(value).resolve()
    if ROOT not in path.parents:
        raise ValueError(f"{value} is outside /work")
    return path


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            image, audio, out = (inside_work(body[k]) for k in ("image", "audio", "out"))
            with tempfile.TemporaryDirectory() as tmp:
                command = [
                    "python", "inference.py", "--driven_audio", str(audio), "--source_image", str(image),
                    "--result_dir", tmp, "--preprocess", "full", "--still", "--enhancer", "gfpgan",
                    "--size", os.environ.get("SADTALKER_SIZE", "256"),
                ]
                if os.environ.get("SADTALKER_CPU") == "1":
                    command.append("--cpu")
                done = subprocess.run(command, capture_output=True, text=True)
                videos = sorted(Path(tmp).rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
                if done.returncode or not videos:
                    raise RuntimeError((done.stderr or done.stdout)[-1500:])
                shutil.move(str(videos[-1]), out)
            self._reply(200, {"out": str(out)})
        except Exception as exc:  # report every failure to the caller instead of dropping the connection
            self._reply(500, {"error": f"{exc.__class__.__name__}: {exc}"})

    def do_GET(self):
        self._reply(200, {"ok": True})

    def _reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
