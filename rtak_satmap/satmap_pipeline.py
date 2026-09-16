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
v1.1 additions:
  - Sentinel-2 API pull via Element84 STAC + GDAL /vsicurl (no account needed)
    Polls every 6 hours for new low-cloud-cover imagery over the observer area.
    Serves as a second ATAK layer at /sentinel-latest/{z}/{x}/{y}.png
  - /sentinel-source.xml endpoint returns auto-filled ATAK map source XML
  - Planet Labs API hook (set --planet-key for sub-meter imagery when available)
"""

import argparse
import http.server
import json
import logging
import math
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

# ---------------------------------------------------------------------------
# Sentinel-2 / API imagery config
# ---------------------------------------------------------------------------

# Element84 Earth Search STAC — public, no account required
STAC_ENDPOINT = "https://earth-search.aws.element84.com/v1/search"

SENTINEL_BBOX_DEG = 1.5     # degrees each side of observer for STAC scene search
SENTINEL_RADIUS_KM = 200    # km radius to crop around observer when tiling
SENTINEL_CLOUD_MAX = 20     # skip scenes with more than this % cloud cover
SENTINEL_POLL_HOURS = 6     # how often to check for new Sentinel-2 imagery
SENTINEL_ZOOM = "5-13"      # tile zoom range (13 gives ~10m/px at full Sentinel res)

SENTINEL_TILE_DIR = OUTPUT_DIR / "sentinel_tiles"
SENTINEL_LOG = OUTPUT_DIR / "sentinel_log.jsonl"

# Planet Labs API (optional — sub-meter imagery if you have a key)
PLANET_API_KEY = ""         # set via --planet-key; leave blank to disable

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
# Sentinel-2 imagery poller
# ---------------------------------------------------------------------------

def _lonlat_to_3857(lon: float, lat: float) -> tuple[float, float]:
    x = lon * math.pi / 180.0 * 6378137.0
    y = math.log(math.tan(math.pi / 4.0 + lat * math.pi / 360.0)) * 6378137.0
    return x, y


class SentinelPoller:
    """Polls Element84 STAC for fresh Sentinel-2 L2A imagery and tiles it."""

    def __init__(self):
        self._last_scene_id: str | None = None

    def poll(self):
        item = self._search_stac()
        if not item:
            log.info("Sentinel-2: no suitable scene found (try relaxing cloud limit)")
            return
        scene_id = item["id"]
        if scene_id == self._last_scene_id:
            log.debug(f"Sentinel-2: no new scene since last poll ({scene_id[:20]})")
            return
        cloud = item["properties"].get("eo:cloud_cover", "?")
        acq = item["properties"].get("datetime", "")[:10]
        log.info(f"Sentinel-2: scene {scene_id[:20]} | {acq} | cloud {cloud}%")
        tci_url = self._get_tci_url(item)
        if not tci_url:
            log.warning("Sentinel-2: no visual/TCI asset found in scene")
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tile_dest = SENTINEL_TILE_DIR / f"s2_{timestamp}"
        if self._tile_cog(tci_url, tile_dest):
            self._update_link(tile_dest)
            self._log(scene_id, item, tile_dest)
            self._last_scene_id = scene_id
            log.info(f"Sentinel-2: ready → {tile_dest.name}")
        else:
            log.warning("Sentinel-2: tiling failed — will retry next poll")

    def _search_stac(self) -> dict | None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=7)
        bbox = [
            OBSERVER_LON - SENTINEL_BBOX_DEG,
            OBSERVER_LAT - SENTINEL_BBOX_DEG,
            OBSERVER_LON + SENTINEL_BBOX_DEG,
            OBSERVER_LAT + SENTINEL_BBOX_DEG,
        ]
        payload = {
            "collections": ["sentinel-2-l2a"],
            "bbox": bbox,
            "datetime": f"{cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')}/{now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "query": {"eo:cloud_cover": {"lt": SENTINEL_CLOUD_MAX}},
            "sortby": [{"field": "datetime", "direction": "desc"}],
            "limit": 1,
        }
        try:
            r = requests.post(STAC_ENDPOINT, json=payload, timeout=30)
            r.raise_for_status()
            features = r.json().get("features", [])
            return features[0] if features else None
        except Exception as exc:
            log.warning(f"Sentinel-2 STAC search failed: {exc}")
            return None

    def _get_tci_url(self, item: dict) -> str | None:
        assets = item.get("assets", {})
        for key in ("visual", "TCI", "tci", "true_color"):
            if key in assets:
                href = assets[key].get("href", "")
                if href.startswith("s3://"):
                    bucket, *rest = href[5:].split("/", 1)
                    href = f"https://{bucket}.s3.amazonaws.com/{rest[0]}"
                return href or None
        return None

    def _tile_cog(self, cog_url: str, tile_dest: Path) -> bool:
        """Stream COG via GDAL vsicurl, crop to observer area, generate XYZ tiles."""
        tile_dest.mkdir(parents=True, exist_ok=True)
        tmp = OUTPUT_DIR / "s2_reproj.tif"

        # Compute crop extent in EPSG:3857
        r_deg = SENTINEL_RADIUS_KM / 111.0
        xmin, ymin = _lonlat_to_3857(OBSERVER_LON - r_deg, OBSERVER_LAT - r_deg)
        xmax, ymax = _lonlat_to_3857(OBSERVER_LON + r_deg, OBSERVER_LAT + r_deg)

        log.info("Sentinel-2: reprojecting + cropping COG (streaming via vsicurl)…")
        result = subprocess.run([
            "gdalwarp",
            "-t_srs", "EPSG:3857",
            "-te", str(xmin), str(ymin), str(xmax), str(ymax),
            "-r", "bilinear",
            "-overwrite",
            f"/vsicurl/{cog_url}", str(tmp),
        ], capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            log.error(f"Sentinel gdalwarp failed: {result.stderr[:300]}")
            return False

        log.info(f"Sentinel-2: tiling at zoom {SENTINEL_ZOOM}…")
        result = subprocess.run([
            "gdal2tiles.py",
            f"--zoom={SENTINEL_ZOOM}",
            "--webviewer=none",
            "--tilesize=256",
            str(tmp),
            str(tile_dest),
        ], capture_output=True, text=True, timeout=900)
        tmp.unlink(missing_ok=True)
        if result.returncode != 0:
            log.error(f"Sentinel gdal2tiles failed: {result.stderr[:300]}")
            return False
        return True

    def _update_link(self, tile_dir: Path):
        latest = SENTINEL_TILE_DIR / "latest"
        if latest.is_symlink():
            latest.unlink()
        latest.symlink_to(tile_dir.resolve())
        log.info(f"'sentinel-latest' symlink → {tile_dir.name}")

    def _log(self, scene_id: str, item: dict, tile_dir: Path):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scene_id": scene_id,
            "acquired": item["properties"].get("datetime"),
            "cloud_cover": item["properties"].get("eo:cloud_cover"),
            "tiles": str(tile_dir),
        }
        with open(SENTINEL_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Tile HTTP server
# ---------------------------------------------------------------------------

class _TileHandler(http.server.BaseHTTPRequestHandler):
    """Minimal XYZ tile server. Serves files from TILE_DIR."""

    def log_message(self, format, *args):
        pass  # suppress per-request logs

    def _client_facing_host(self) -> str:
        """Return the IP the client used to reach us — correct regardless of aliases."""
        host_header = self.headers.get("Host", "")
        if host_header:
            return host_header.split(":")[0]
        return self.server.server_address[0]

    def do_GET(self):
        # Strip leading slash and resolve path under TILE_DIR
        rel = self.path.lstrip("/").split("?")[0]
        target = TILE_DIR / rel

        # Auto-filled ATAK map source XMLs
        if rel == "source.xml":
            self._send_source_xml()
            return
        if rel == "sentinel-source.xml":
            self._send_sentinel_source_xml()
            return

        # Index / status page
        if rel in ("", "index.html"):
            self._send_index()
            return

        # Sentinel tile route: /sentinel-latest/{z}/{x}/{y}.png
        if rel.startswith("sentinel-latest/"):
            sub = rel[len("sentinel-latest/"):]
            sentinel_target = SENTINEL_TILE_DIR / "latest" / sub
            if sentinel_target.is_file():
                data = sentinel_target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404)
            return

        # RF satellite tile file
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

    def _send_source_xml(self):
        """Return a ready-to-use ATAK customMapSource XML with the node IP auto-filled."""
        host = self._client_facing_host()
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<customMapSource>\n"
            "    <name>RTAK SatMap — Latest Pass</name>\n"
            "    <minZoom>3</minZoom>\n"
            "    <maxZoom>12</maxZoom>\n"
            "    <type>tms</type>\n"
            f"    <url>http://{host}:{TILE_PORT}/latest/{{z}}/{{x}}/{{y}}.png</url>\n"
            "    <backgroundColor>#00000000</backgroundColor>\n"
            "</customMapSource>\n"
        )
        body = xml.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Disposition", 'attachment; filename="rtak_satmap_source.xml"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sentinel_source_xml(self):
        """Return ATAK customMapSource XML for the Sentinel-2 layer."""
        host = self._client_facing_host()
        sentinel_latest = SENTINEL_TILE_DIR / "latest"
        if not sentinel_latest.exists():
            self.send_error(503, "No Sentinel-2 imagery available yet — check back after first poll")
            return
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<customMapSource>\n"
            "    <name>RTAK SatMap — Sentinel-2 (10m)</name>\n"
            "    <minZoom>5</minZoom>\n"
            "    <maxZoom>13</maxZoom>\n"
            "    <type>tms</type>\n"
            f"    <url>http://{host}:{TILE_PORT}/sentinel-latest/{{z}}/{{x}}/{{y}}.png</url>\n"
            "    <backgroundColor>#00000000</backgroundColor>\n"
            "</customMapSource>\n"
        )
        body = xml.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Disposition", 'attachment; filename="rtak_sentinel_source.xml"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_index(self):
        host = self._client_facing_host()
        latest = TILE_DIR / "latest"
        tileset = latest.resolve().name if latest.is_symlink() else "none"
        sentinel_latest = SENTINEL_TILE_DIR / "latest"
        sentinel_tileset = sentinel_latest.resolve().name if sentinel_latest.is_symlink() else "none"
        passes = []
        if PASS_LOG.exists():
            with open(PASS_LOG) as f:
                passes = [json.loads(l) for l in f if l.strip()][-10:]
        sentinel_log = []
        if SENTINEL_LOG.exists():
            with open(SENTINEL_LOG) as f:
                sentinel_log = [json.loads(l) for l in f if l.strip()][-5:]
        body = json.dumps({
            "status": "ok",
            "rf_satellite": {
                "latest_tileset": tileset,
                "source_xml_url": f"http://{host}:{TILE_PORT}/source.xml",
                "tile_url": f"http://{host}:{TILE_PORT}/latest/{{z}}/{{x}}/{{y}}.png",
                "recent_passes": passes,
            },
            "sentinel2": {
                "latest_tileset": sentinel_tileset,
                "source_xml_url": f"http://{host}:{TILE_PORT}/sentinel-source.xml",
                "tile_url": f"http://{host}:{TILE_PORT}/sentinel-latest/{{z}}/{{x}}/{{y}}.png",
                "recent_scenes": sentinel_log,
                "poll_interval_hours": SENTINEL_POLL_HOURS,
            },
        }, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_tile_server():
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    SENTINEL_TILE_DIR.mkdir(parents=True, exist_ok=True)
    server = http.server.HTTPServer(("0.0.0.0", TILE_PORT), _TileHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info(f"Tile server (RF):       http://<node-ip>:{TILE_PORT}/latest/{{z}}/{{x}}/{{y}}.png")
    log.info(f"Tile server (Sentinel): http://<node-ip>:{TILE_PORT}/sentinel-latest/{{z}}/{{x}}/{{y}}.png")


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
    parser.add_argument("--sentinel-cloud-max", type=float, default=SENTINEL_CLOUD_MAX,
                        help="Max cloud cover %% for Sentinel-2 scene selection")
    parser.add_argument("--sentinel-radius-km", type=float, default=SENTINEL_RADIUS_KM,
                        help="Crop radius around observer for Sentinel-2 tiles (km)")
    parser.add_argument("--planet-key", type=str, default="",
                        help="Planet Labs API key (enables sub-meter Planet imagery polling)")
    parser.add_argument("--no-sentinel", action="store_true",
                        help="Disable Sentinel-2 API polling (RF-only mode)")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    global OBSERVER_LAT, OBSERVER_LON, OBSERVER_ALT, MIN_ELEVATION_DEG, TILE_PORT
    global SENTINEL_CLOUD_MAX, SENTINEL_RADIUS_KM, PLANET_API_KEY
    OBSERVER_LAT = args.lat
    OBSERVER_LON = args.lon
    OBSERVER_ALT = args.alt
    MIN_ELEVATION_DEG = args.min_elev
    TILE_PORT = args.port
    SENTINEL_CLOUD_MAX = args.sentinel_cloud_max
    SENTINEL_RADIUS_KM = args.sentinel_radius_km
    PLANET_API_KEY = args.planet_key

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    SENTINEL_TILE_DIR.mkdir(parents=True, exist_ok=True)

    log.info(f"Observer: {OBSERVER_LAT}°N {OBSERVER_LON}°E alt={OBSERVER_ALT}m")
    log.info(f"Minimum pass elevation: {MIN_ELEVATION_DEG}°")
    if not args.no_sentinel:
        log.info(f"Sentinel-2 polling: every {SENTINEL_POLL_HOURS}h | "
                 f"cloud <{SENTINEL_CLOUD_MAX}% | radius {SENTINEL_RADIUS_KM}km")
    if PLANET_API_KEY:
        log.info("Planet Labs API key configured — planet polling active")

    start_tile_server()

    scheduler = PassScheduler()
    sentinel = SentinelPoller() if not args.no_sentinel else None
    last_tle_refresh = 0.0
    last_sentinel_poll = 0.0

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

            # Sentinel-2 poll
            if sentinel and now - last_sentinel_poll > SENTINEL_POLL_HOURS * 3600:
                threading.Thread(
                    target=sentinel.poll, daemon=True, name="sentinel-poll"
                ).start()
                last_sentinel_poll = now

            time.sleep(3600)

    except KeyboardInterrupt:
        log.info("Stopped")


if __name__ == "__main__":
    main()
