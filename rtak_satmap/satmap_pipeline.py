#!/usr/bin/env python3
"""
RTAK SatMap Pipeline — Automated satellite imagery for ATAK map overlay.

What this does:
  1. Downloads fresh TLE orbital data for NOAA and Meteor-M satellites
  2. Computes upcoming passes above a configured minimum elevation
  3. Schedules SatDump recordings timed to each pass
  4. Post-processes SatDump GeoTIFF output into XYZ map tiles (EPSG:3857)
  5. Serves tiles via HTTP so ATAK can use the Pi as a live tile source

ATAK integration (no plugin code required):
  Point ATAK to http://<node-ip>:8889/latest/{z}/{x}/{y}.png
  as a custom map source. The tile set updates automatically after each pass.

Usage:
  python3 satmap_pipeline.py --lat 38.9 --lon -77.0
  python3 satmap_pipeline.py --lat 38.9 --lon -77.0 --alt 100 --debug

Dependencies:
  pip install pyorbital requests
  apt-get install gdal-bin python3-gdal
  SatDump binary: https://github.com/SatDump/SatDump/releases
"""

import argparse
import http.server
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from pyorbital.orbital import Orbital

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Observer location — override via CLI args
OBSERVER_LAT = 0.0
OBSERVER_LON = 0.0
OBSERVER_ALT = 0.0           # meters above sea level

MIN_ELEVATION_DEG = 15       # skip passes below this peak elevation (degrees)
LOOKAHEAD_HOURS = 12         # schedule passes this far ahead
TLE_REFRESH_HOURS = 6        # re-download TLEs this often
TILE_PORT = 8889             # HTTP tile server port (open in UFW by setup script)

OUTPUT_DIR = Path("/opt/rtak/satmap")
TILE_DIR = OUTPUT_DIR / "tiles"
TLE_PATH = OUTPUT_DIR / "weather.tle"
PASS_LOG = OUTPUT_DIR / "pass_log.jsonl"

SATDUMP_BIN = "/usr/local/bin/satdump"  # override if installed elsewhere

# Satellites to track. Keys are SatDump pipeline names; values are (NORAD_ID, freq_hz).
SATELLITES = {
    "noaa_apt": [
        ("NOAA 15", 137620000),
        ("NOAA 18", 137912500),
        ("NOAA 19", 137100000),
    ],
    "meteor_m2_lrpt": [
        ("METEOR-M2 3", 137900000),
        ("METEOR-M2 4", 137900000),
    ],
}

TLE_URLS = [
    "https://celestrak.org/NOAA/elements/noaa.txt",
    "https://celestrak.org/NOAA/elements/weather.txt",
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] satmap: %(message)s",
)
log = logging.getLogger("satmap")


# ---------------------------------------------------------------------------
# TLE management
# ---------------------------------------------------------------------------

def refresh_tle():
    """Download fresh TLE data from Celestrak. Returns True on success."""
    combined = ""
    for url in TLE_URLS:
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            combined += r.text + "\n"
            log.info(f"TLE fetched from {url}")
        except Exception as exc:
            log.warning(f"TLE fetch failed ({url}): {exc}")
    if combined:
        TLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TLE_PATH.write_text(combined)
        return True
    return False


# ---------------------------------------------------------------------------
# Pass prediction
# ---------------------------------------------------------------------------

def find_upcoming_passes(sat_name: str, hours_ahead: float) -> list[dict]:
    """Return a list of upcoming pass dicts for sat_name."""
    if not TLE_PATH.exists():
        log.warning("No TLE file — cannot predict passes")
        return []
    try:
        orb = Orbital(sat_name, tle_file=str(TLE_PATH))
    except Exception as exc:
        log.debug(f"Could not load TLE for {sat_name!r}: {exc}")
        return []

    passes = []
    now = datetime.now(timezone.utc)
    try:
        raw = orb.get_next_passes(
            now, hours_ahead,
            OBSERVER_LON, OBSERVER_LAT, OBSERVER_ALT,
        )
    except Exception as exc:
        log.debug(f"Pass prediction failed for {sat_name}: {exc}")
        return []

    for (rise, fall, peak) in raw:
        try:
            _, elev = orb.get_observer_look(peak, OBSERVER_LON, OBSERVER_LAT, OBSERVER_ALT)
            if elev >= MIN_ELEVATION_DEG:
                duration = int((fall - rise).total_seconds())
                passes.append({
                    "sat_name": sat_name,
                    "rise_utc": rise.isoformat(),
                    "fall_utc": fall.isoformat(),
                    "peak_utc": peak.isoformat(),
                    "peak_elevation_deg": round(elev, 1),
                    "duration_sec": duration,
                })
        except Exception:
            continue
    return passes


# ---------------------------------------------------------------------------
# Tile generation
# ---------------------------------------------------------------------------

def geotiff_to_tiles(geotiff_path: Path, tile_output_dir: Path, zoom: str = "5-12"):
    """Convert a SatDump GeoTIFF to XYZ tiles using GDAL."""
    tile_output_dir.mkdir(parents=True, exist_ok=True)
    tmp = geotiff_path.parent / "reprojected.tif"

    log.info(f"Reprojecting {geotiff_path.name} to EPSG:3857...")
    result = subprocess.run([
        "gdalwarp", "-t_srs", "EPSG:3857",
        "-r", "bilinear",
        "-overwrite",
        str(geotiff_path), str(tmp),
    ], capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"gdalwarp failed: {result.stderr.strip()}")
        return False

    log.info(f"Generating XYZ tiles at zoom {zoom}...")
    result = subprocess.run([
        "gdal2tiles.py",
        f"--zoom={zoom}",
        "--webviewer=none",
        "--tilesize=256",
        str(tmp),
        str(tile_output_dir),
    ], capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"gdal2tiles failed: {result.stderr.strip()}")
        return False

    tmp.unlink(missing_ok=True)
    log.info(f"Tiles written to {tile_output_dir}")
    return True


def update_latest_link(tile_dir: Path):
    """Point the 'latest' symlink to tile_dir so ATAK always gets the newest pass."""
    latest = TILE_DIR / "latest"
    if latest.is_symlink():
        latest.unlink()
    latest.symlink_to(tile_dir.resolve())
    log.info(f"'latest' tile set → {tile_dir.name}")


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record_pass(pipeline: str, sat_name: str, freq_hz: int, duration_sec: int):
    """Run SatDump for one satellite pass and post-process the output."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = sat_name.replace(" ", "_").replace("-", "_")
    output_dir = OUTPUT_DIR / "captures" / f"{safe_name}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        SATDUMP_BIN, "live", pipeline,
        str(output_dir),
        "--source", "rtlsdr",
        "--frequency", str(freq_hz),
        "--samplerate", "2400000",
        "--timeout", str(duration_sec + 30),  # 30s margin
    ]
    log.info(f"Recording {sat_name} ({pipeline}) for {duration_sec}s → {output_dir.name}")
    try:
        result = subprocess.run(cmd, timeout=duration_sec + 120, capture_output=True, text=True)
        if result.returncode != 0:
            log.warning(f"SatDump exited {result.returncode}: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log.warning(f"SatDump timed out for {sat_name} — likely pass completed")
    except FileNotFoundError:
        log.error(f"SatDump binary not found at {SATDUMP_BIN}")
        return

    # Find the GeoTIFF output (SatDump writes it under output_dir)
    geotiffs = list(output_dir.rglob("*.tif")) + list(output_dir.rglob("*.tiff"))
    if not geotiffs:
        log.warning(f"No GeoTIFF found in {output_dir} — pass may have had insufficient signal")
        return

    for gtiff in geotiffs:
        tile_dest = TILE_DIR / f"{safe_name}_{timestamp}"
        if geotiff_to_tiles(gtiff, tile_dest):
            update_latest_link(tile_dest)
            _log_pass(sat_name, timestamp, gtiff, tile_dest)
            break


def _log_pass(sat_name, timestamp, geotiff_path, tile_dir):
    entry = {
        "timestamp": timestamp,
        "satellite": sat_name,
        "geotiff": str(geotiff_path),
        "tiles": str(tile_dir),
    }
    with open(PASS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class PassScheduler:
    def __init__(self):
        self._scheduled: set[str] = set()  # (sat_name, rise_utc) pairs already scheduled
        self._lock = threading.Lock()

    def schedule_upcoming(self):
        """Compute passes for the next LOOKAHEAD_HOURS and schedule threads for each."""
        for pipeline, sats in SATELLITES.items():
            for sat_name, freq_hz in sats:
                for p in find_upcoming_passes(sat_name, LOOKAHEAD_HOURS):
                    key = f"{sat_name}|{p['rise_utc']}"
                    with self._lock:
                        if key in self._scheduled:
                            continue
                        self._scheduled.add(key)
                    self._schedule_one(pipeline, p, freq_hz)

    def _schedule_one(self, pipeline: str, pass_info: dict, freq_hz: int):
        rise = datetime.fromisoformat(pass_info["rise_utc"])
        now = datetime.now(timezone.utc)
        delay = max(0.0, (rise - now).total_seconds() - 10)  # start 10s early

        sat = pass_info["sat_name"]
        elev = pass_info["peak_elevation_deg"]
        dur = pass_info["duration_sec"]

        log.info(
            f"Scheduled: {sat} @ {rise.strftime('%H:%M UTC')} "
            f"(peak {elev}°, {dur}s, in {int(delay)}s)"
        )

        def _run():
            time.sleep(delay)
            record_pass(pipeline, sat, freq_hz, dur)

        t = threading.Thread(target=_run, daemon=True, name=f"pass-{sat}")
        t.start()


# ---------------------------------------------------------------------------
# Tile HTTP server
# ---------------------------------------------------------------------------

class _TileHandler(http.server.BaseHTTPRequestHandler):
    """Minimal XYZ tile server. Serves files from TILE_DIR."""

    def log_message(self, format, *args):
        pass  # suppress per-request logs

    def do_GET(self):
        # Strip leading slash and resolve path under TILE_DIR
        rel = self.path.lstrip("/")
        target = TILE_DIR / rel

        # Index page
        if rel in ("", "index.html"):
            self._send_index()
            return

        # Tile file
        if target.is_file():
            ext = target.suffix.lower()
            ctype = {".png": "image/png", ".jpg": "image/jpeg"}.get(ext, "application/octet-stream")
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)

    def _send_index(self):
        latest = TILE_DIR / "latest"
        target = latest.resolve().name if latest.is_symlink() else "none"
        passes = []
        if PASS_LOG.exists():
            with open(PASS_LOG) as f:
                passes = [json.loads(l) for l in f if l.strip()][-10:]
        body = json.dumps({
            "status": "ok",
            "latest_tileset": target,
            "recent_passes": passes,
            "tile_url_template": f"http://<node-ip>:{TILE_PORT}/latest/{{z}}/{{x}}/{{y}}.png",
        }, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_tile_server():
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    server = http.server.HTTPServer(("0.0.0.0", TILE_PORT), _TileHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info(f"Tile server: http://<node-ip>:{TILE_PORT}/latest/{{z}}/{{x}}/{{y}}.png")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="RTAK SatMap — automated satellite imagery pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--lat", type=float, required=True, help="Observer latitude (decimal degrees)")
    parser.add_argument("--lon", type=float, required=True, help="Observer longitude (decimal degrees)")
    parser.add_argument("--alt", type=float, default=0.0, help="Observer altitude above sea level (meters)")
    parser.add_argument("--min-elev", type=float, default=MIN_ELEVATION_DEG,
                        help="Minimum peak pass elevation to record (degrees)")
    parser.add_argument("--port", type=int, default=TILE_PORT, help="HTTP tile server port")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    global OBSERVER_LAT, OBSERVER_LON, OBSERVER_ALT, MIN_ELEVATION_DEG, TILE_PORT
    OBSERVER_LAT = args.lat
    OBSERVER_LON = args.lon
    OBSERVER_ALT = args.alt
    MIN_ELEVATION_DEG = args.min_elev
    TILE_PORT = args.port

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TILE_DIR.mkdir(parents=True, exist_ok=True)

    log.info(f"Observer: {OBSERVER_LAT}°N {OBSERVER_LON}°E alt={OBSERVER_ALT}m")
    log.info(f"Minimum pass elevation: {MIN_ELEVATION_DEG}°")

    start_tile_server()

    scheduler = PassScheduler()
    last_tle_refresh = 0.0

    log.info("SatMap pipeline running. Press Ctrl-C to stop.")
    try:
        while True:
            now = time.monotonic()

            # Refresh TLEs periodically
            if now - last_tle_refresh > TLE_REFRESH_HOURS * 3600:
                if refresh_tle():
                    last_tle_refresh = now
                    scheduler.schedule_upcoming()
                else:
                    log.warning("TLE refresh failed — retrying in 30 minutes")

            # Re-schedule every hour to pick up any new pass windows
            scheduler.schedule_upcoming()
            time.sleep(3600)

    except KeyboardInterrupt:
        log.info("Stopped")


if __name__ == "__main__":
    main()
