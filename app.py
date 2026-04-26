"""
app.py — Vanity Wallet UI backend
Flask server for the vanity_wallet UI.
Run: python app.py   →  http://localhost:5003
"""

import json
import os
import sys
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

sys.path.insert(0, os.path.dirname(__file__))
import vanity_wallet as vw

app = Flask(__name__, static_folder="frontend")

# Allow inscribator (port 5001) to call the vanity_wallet API from an iframe.
_CORS_ORIGINS = {"http://localhost:5001", "http://127.0.0.1:5001"}

@app.after_request
def _cors(response):
    origin = request.headers.get("Origin", "")
    if origin in _CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"]  = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/api/<path:path>", methods=["OPTIONS"])
def _preflight(path):
    """CORS preflight handler for API routes."""
    origin = request.headers.get("Origin", "")
    resp = app.make_default_options_response()
    if origin in _CORS_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"]  = origin
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

_DESKTOP       = Path.home() / "Desktop"
_CKPT_FILE     = _DESKTOP / "vanity_wallet_checkpoint.json"
_RESULT_FILE   = _DESKTOP / "vanity_wallet_result.json"

# ── Active session state ──────────────────────────────────────────────────
_session = {
    "running":    False,
    "stop_event": None,
    "result":     None,       # dict when found
    "config":     None,
    "progress":   None,       # latest progress event from vw.run()
}
_session_lock = threading.Lock()

# ── Frontend serving ──────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory("frontend", filename)

@app.route("/readme")
def serve_readme():
    return send_from_directory(os.path.dirname(__file__), "README.md", mimetype="text/plain; charset=utf-8")

# ── API: benchmark ────────────────────────────────────────────────────────

@app.route("/api/benchmark")
def benchmark():
    words = int(request.args.get("words", 12))
    workers = os.cpu_count()
    rate1 = vw._benchmark("", 0, words, 20)
    return jsonify({"rate_per_core": round(rate1), "cores": workers,
                    "rate_total": round(rate1 * workers)})

# ── API: checkpoint ───────────────────────────────────────────────────────

@app.route("/api/checkpoint")
def get_checkpoint():
    if _CKPT_FILE.exists():
        try:
            with open(_CKPT_FILE, encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception:
            pass
    return jsonify(None)

@app.route("/api/checkpoint/clear", methods=["POST"])
def clear_checkpoint():
    try:
        if _CKPT_FILE.exists():
            _CKPT_FILE.unlink()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})

# ── API: start / stop ─────────────────────────────────────────────────────

@app.route("/api/start", methods=["POST"])
def start():
    with _session_lock:
        if _session["running"]:
            return jsonify({"error": "already running"}), 409

    data = request.get_json(force=True)
    patterns = data.get("patterns", [])
    if not patterns:
        return jsonify({"error": "no patterns"}), 400

    prefixes, suffixes, nopref, pairs = [], [], [], []
    bc1q_prefixes, bc1q_suffixes, bc1q_nopref, bc1q_pairs = [], [], [], []
    for pat in patterns:
        lead      = (pat.get("leading") or "").strip().lower()
        trail     = (pat.get("trailing") or "").strip().lower()
        or_mode   = bool(pat.get("or_mode"))
        addr_type = pat.get("addr_type", "bc1p")

        target_pfx  = bc1q_prefixes if addr_type == "bc1q" else prefixes
        target_sfx  = bc1q_suffixes if addr_type == "bc1q" else suffixes
        target_np   = bc1q_nopref   if addr_type == "bc1q" else nopref
        target_pair = bc1q_pairs    if addr_type == "bc1q" else pairs

        if lead and trail and not or_mode:
            target_pair.append([lead, trail])
        elif lead and trail and or_mode:
            # OR mode with both → each end independently
            nopref_style = pat.get("nopref_style", False)
            if nopref_style:
                target_np.append(lead)
                target_np.append(trail)
            else:
                target_pfx.append(lead)
                target_sfx.append(trail)
        elif lead and or_mode:
            target_np.append(lead)
        elif lead:
            target_pfx.append(lead)
        elif trail:
            target_sfx.append(trail)

    # de-dup
    prefixes      = list(dict.fromkeys(prefixes))
    suffixes      = list(dict.fromkeys(suffixes))
    nopref        = list(dict.fromkeys(nopref))
    bc1q_prefixes = list(dict.fromkeys(bc1q_prefixes))
    bc1q_suffixes = list(dict.fromkeys(bc1q_suffixes))
    bc1q_nopref   = list(dict.fromkeys(bc1q_nopref))

    if not prefixes and not suffixes and not nopref and not pairs \
            and not bc1q_prefixes and not bc1q_suffixes and not bc1q_nopref and not bc1q_pairs \
            and not data.get("only_digits") and not data.get("only_letters"):
        return jsonify({"error": "no valid patterns after parsing"}), 400

    # validate chars (same bech32/bech32m charset for both bc1p and bc1q)
    all_chars = "".join(prefixes + suffixes + nopref + [c for p in pairs for c in p]
                        + bc1q_prefixes + bc1q_suffixes + bc1q_nopref + [c for p in bc1q_pairs for c in p])
    bad = [c for c in all_chars if c not in vw.BECH32M_CHARSET]
    if bad:
        return jsonify({"error": f"Invalid bech32m characters: {''.join(sorted(set(bad)))}"}), 400

    config = {
        "prefixes":      prefixes,
        "suffixes":      suffixes,
        "nopref":        nopref,
        "pairs":         pairs,
        "bc1q_prefixes": bc1q_prefixes,
        "bc1q_suffixes": bc1q_suffixes,
        "bc1q_nopref":   bc1q_nopref,
        "bc1q_pairs":    bc1q_pairs,
        "passphrase":    data.get("passphrase", ""),
        "wallet_index":  int(data.get("wallet_index", 0)),
        "words_count":   int(data.get("words_count", 12)),
        "workers":       data.get("workers") or None,
        "checkpoint_file":     str(_CKPT_FILE),
        "checkpoint_interval": 60,
    }

    # only-digits / only-letters: pass as flags, do NOT add to nopref
    config["only_digits"]  = bool(data.get("only_digits"))
    config["only_letters"] = bool(data.get("only_letters"))

    stop_event = threading.Event()

    with _session_lock:
        _session["running"]    = True
        _session["stop_event"] = stop_event
        _session["result"]     = None
        _session["config"]     = config
        _session["progress"]   = None

    def _progress_cb(ev):
        with _session_lock:
            _session["progress"] = ev

    def _run():
        result = vw.run(config, stop_event=stop_event, progress_cb=_progress_cb)
        with _session_lock:
            _session["running"] = False
            if result:
                _session["result"] = result
                # persist to desktop
                try:
                    out = dict(result)
                    out["WARNING"] = "SHRED THIS FILE after importing mnemonic into wallet"
                    with open(_RESULT_FILE, "w") as f:
                        json.dump(out, f, indent=2)
                except Exception:
                    pass

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def stop():
    with _session_lock:
        ev = _session.get("stop_event")
        if ev:
            ev.set()
    return jsonify({"ok": True})


# ── API: SSE stream ───────────────────────────────────────────────────────

@app.route("/api/stream")
def stream():
    """SSE: push progress, found, stopped events."""

    def _gen():
        last_state = None
        # wait up to 3s for session to start
        for _ in range(30):
            with _session_lock:
                running = _session["running"]
                result  = _session["result"]
            if running or result:
                break
            time.sleep(0.1)
            yield f"data: {json.dumps({'type': 'wait'})}\n\n"

        # Stream progress while running
        stop_ev = None
        with _session_lock:
            stop_ev = _session.get("stop_event")

        while True:
            with _session_lock:
                running = _session["running"]
                result  = _session["result"]
                config  = _session["config"]

            if result and (last_state != "found"):
                last_state = "found"
                # Never send mnemonic over SSE — client will fetch /api/result
                safe = {k: v for k, v in result.items() if k != "mnemonic"}
                yield f"data: {json.dumps({'type': 'found', 'result': safe})}\n\n"
                break

            if not running and last_state != "found":
                yield f"data: {json.dumps({'type': 'stopped'})}\n\n"
                break

            with _session_lock:
                prog = _session["progress"]

            if prog and prog.get("type") == "progress":
                yield f"data: {json.dumps({'type': 'progress', 'total': prog.get('total', 0), 'rate': prog.get('rate', 0), 'pct': prog.get('pct', 0), 'eta_sec': prog.get('eta_s', 0)})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'progress', 'total': 0, 'rate': 0, 'pct': 0, 'eta_sec': 0})}\n\n"
            time.sleep(2)

    return Response(_gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── API: result (mnemonic — never via SSE) ────────────────────────────────

@app.route("/api/result")
def get_result():
    with _session_lock:
        result = _session.get("result")
    if not result:
        return jsonify(None)
    # Return full result including mnemonic (local only, never leaves localhost)
    return jsonify(result)


@app.route("/api/result/clear", methods=["POST"])
def clear_result():
    """Wipe the in-memory result so a refresh no longer shows the old mnemonic."""
    with _session_lock:
        _session["result"] = None
    return jsonify({"ok": True})


# ── API: status ───────────────────────────────────────────────────────────

@app.route("/api/status")
def status():
    with _session_lock:
        return jsonify({
            "running": _session["running"],
            "has_result": _session["result"] is not None,
        })


if __name__ == "__main__":
    print("\n  Vanity Wallet UI")
    print("  http://localhost:5003\n")
    app.run(host="127.0.0.1", port=5003, debug=False, threaded=True)
