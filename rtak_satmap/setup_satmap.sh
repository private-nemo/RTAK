#!/usr/bin/env bash
# RTAK SatMap Setup — Automated satellite imagery pipeline
#
# Installs SatDump, GDAL, Python deps, and configures the satmap pipeline
# as a systemd service. After running this, satellite passes are automatically
# recorded, processed, and served as map tiles at http://<node-ip>:8889/
#
# Usage:
#   sudo bash setup_satmap.sh --lat 38.9 --lon -77.0
#   sudo bash setup_satmap.sh --lat 38.9 --lon -77.0 --alt 100
#
# Prerequisites:
#   - setup_pi.sh must have already been run
#   - RTL-SDR dongle plugged into USB hub
#   - 137 MHz antenna connected to RTL-SDR

set -euo pipefail

RTAK_HOME="/opt/rtak"
SATMAP_DIR="$RTAK_HOME/satmap"
RTAK_USER="rtak"

LAT=""
LON=""
ALT=0
TILE_PORT=8889
PLANET_KEY=""
NO_SENTINEL=0

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --lat) LAT="$2"; shift 2 ;;
        --lon) LON="$2"; shift 2 ;;
        --alt) ALT="$2"; shift 2 ;;
        --port) TILE_PORT="$2"; shift 2 ;;
        --planet-key) PLANET_KEY="$2"; shift 2 ;;
        --no-sentinel) NO_SENTINEL=1; shift ;;
        *) echo "Unknown argument: $1"
           echo "Usage: $0 --lat <deg> --lon <deg> [--alt <m>] [--port N] [--planet-key KEY] [--no-sentinel]"
           exit 1 ;;
    esac
done

if [[ -z "$LAT" || -z "$LON" ]]; then
    echo "ERROR: --lat and --lon are required"
    echo "Usage: sudo bash $0 --lat 38.9 --lon -77.0"
    exit 1
fi

echo "=== RTAK SatMap Setup (v1.1) ==="
echo "Observer: ${LAT}°N ${LON}°E alt=${ALT}m"
echo "Tile port: $TILE_PORT"
[[ -n "$PLANET_KEY" ]] && echo "Planet Labs API: configured" || echo "Planet Labs API: not configured (pass --planet-key to enable)"
[[ "$NO_SENTINEL" -eq 1 ]] && echo "Sentinel-2: disabled (--no-sentinel)" || echo "Sentinel-2: enabled (Element84 STAC, no account needed)"
echo ""

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
echo "[1/5] Installing system dependencies..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    gdal-bin python3-gdal \
    rtl-sdr librtlsdr-dev \
    cmake build-essential git \
    curl wget

# Blacklist DVB-T kernel modules that claim RTL-SDR by default
if ! grep -q "blacklist dvb_usb_rtl28xxu" /etc/modprobe.d/rtlsdr.conf 2>/dev/null; then
    cat > /etc/modprobe.d/rtlsdr.conf <<MODCONF
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
MODCONF
    echo "  RTL-SDR kernel module blacklist installed (prevents DVB driver conflict)"
fi

# ---------------------------------------------------------------------------
# 2. SatDump
# ---------------------------------------------------------------------------
echo "[2/5] Installing SatDump..."
SATDUMP_VERSION="1.2.0"
SATDUMP_DEB="satdump_${SATDUMP_VERSION}_arm64.deb"
SATDUMP_URL="https://github.com/SatDump/SatDump/releases/download/${SATDUMP_VERSION}/${SATDUMP_DEB}"

if command -v satdump &>/dev/null; then
    echo "  SatDump already installed: $(satdump --version 2>/dev/null || echo '(version unknown)')"
else
    echo "  Downloading SatDump ${SATDUMP_VERSION}..."
    wget -q -O "/tmp/${SATDUMP_DEB}" "${SATDUMP_URL}" || {
        echo "  WARNING: Could not download pre-built .deb — falling back to build from source"
        echo "  This will take 15-30 minutes on a Pi 4B."
        BUILD_DIR="/tmp/satdump_build"
        git clone --depth=1 https://github.com/SatDump/SatDump.git "$BUILD_DIR"
        mkdir -p "$BUILD_DIR/build"
        cmake -B "$BUILD_DIR/build" -S "$BUILD_DIR" \
            -DCMAKE_BUILD_TYPE=Release \
            -DBUILD_GUI=OFF \
            -DPLUGIN_ALL=ON
        make -C "$BUILD_DIR/build" -j"$(nproc)"
        make -C "$BUILD_DIR/build" install
        rm -rf "$BUILD_DIR"
    }
    if [[ -f "/tmp/${SATDUMP_DEB}" ]]; then
        dpkg -i "/tmp/${SATDUMP_DEB}" 2>/dev/null || apt-get install -f -y
        rm -f "/tmp/${SATDUMP_DEB}"
    fi
    echo "  SatDump installed: $(satdump --version 2>/dev/null || echo 'ok')"
fi

# ---------------------------------------------------------------------------
# 3. Python dependencies
# ---------------------------------------------------------------------------
echo "[3/5] Installing Python dependencies..."
"$RTAK_HOME/venv/bin/pip" install --quiet \
    pyorbital \
    requests

# ---------------------------------------------------------------------------
# 4. Deploy pipeline and create directories
# ---------------------------------------------------------------------------
echo "[4/5] Deploying satmap pipeline..."
mkdir -p "$SATMAP_DIR/tiles" "$SATMAP_DIR/captures"
cp "$(dirname "$0")/satmap_pipeline.py" "$RTAK_HOME/"
chown -R "$RTAK_USER:$RTAK_USER" "$SATMAP_DIR"
chmod +x "$RTAK_HOME/satmap_pipeline.py"

# Open tile server port in UFW
ufw allow "$TILE_PORT/tcp" comment "RTAK SatMap tile server"
echo "  UFW: port $TILE_PORT/tcp opened for tile server"

# ---------------------------------------------------------------------------
# 5. Systemd service
# ---------------------------------------------------------------------------
echo "[5/5] Installing rtak-satmap systemd service..."
cat > /etc/systemd/system/rtak-satmap.service <<SATSVC
[Unit]
Description=RTAK SatMap — automated satellite imagery pipeline
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User=$RTAK_USER
WorkingDirectory=$RTAK_HOME
ExecStart=$RTAK_HOME/venv/bin/python $RTAK_HOME/satmap_pipeline.py \
    --lat $LAT \
    --lon $LON \
    --alt $ALT \
    --port $TILE_PORT \
    $([ -n "$PLANET_KEY" ] && echo "--planet-key $PLANET_KEY") \
    $([ "$NO_SENTINEL" -eq 1 ] && echo "--no-sentinel")
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SATSVC

systemctl daemon-reload
systemctl enable rtak-satmap
systemctl start rtak-satmap

echo ""
NODE_IP="$(hostname -I | awk '{print $1}')"

# Write a pre-filled ATAK map source XML so operators don't have to edit anything
PREFILLED_XML="$SATMAP_DIR/atak_satmap_source.xml"
cat > "$PREFILLED_XML" <<ATKXML
<?xml version="1.0" encoding="UTF-8"?>
<customMapSource>
    <name>RTAK SatMap — Latest Pass</name>
    <minZoom>3</minZoom>
    <maxZoom>12</maxZoom>
    <type>tms</type>
    <url>http://${NODE_IP}:${TILE_PORT}/latest/{z}/{x}/{y}.png</url>
    <backgroundColor>#00000000</backgroundColor>
</customMapSource>
ATKXML
chown "$RTAK_USER:$RTAK_USER" "$PREFILLED_XML"
echo "  Pre-filled RF ATAK source XML: $PREFILLED_XML"

# Sentinel-2 pre-filled map source XML
if [[ "$NO_SENTINEL" -eq 0 ]]; then
    SENTINEL_XML="$SATMAP_DIR/atak_sentinel_source.xml"
    cat > "$SENTINEL_XML" <<SXML
<?xml version="1.0" encoding="UTF-8"?>
<customMapSource>
    <name>RTAK SatMap — Sentinel-2 (10m)</name>
    <minZoom>5</minZoom>
    <maxZoom>13</maxZoom>
    <type>tms</type>
    <url>http://${NODE_IP}:${TILE_PORT}/sentinel-latest/{z}/{x}/{y}.png</url>
    <backgroundColor>#00000000</backgroundColor>
</customMapSource>
SXML
    chown "$RTAK_USER:$RTAK_USER" "$SENTINEL_XML"
    echo "  Pre-filled Sentinel-2 ATAK source XML: $SENTINEL_XML"
fi

echo ""
echo "=== SatMap setup complete ==="
echo ""
echo "Status:       sudo systemctl status rtak-satmap"
echo "Live log:     sudo journalctl -u rtak-satmap -f"
echo "Tile server:  http://${NODE_IP}:${TILE_PORT}/"
echo "ATAK source:  http://${NODE_IP}:${TILE_PORT}/latest/{z}/{x}/{y}.png"
echo ""
echo "ATAK map source setup:"
echo ""
echo "  RF satellite layer (NOAA/Meteor, ~4km resolution, updates every ~90 min):"
echo "    Browser:  http://${NODE_IP}:${TILE_PORT}/source.xml"
echo "    USB push: adb push $PREFILLED_XML /sdcard/atak/imagery/"
echo ""
if [[ "$NO_SENTINEL" -eq 0 ]]; then
echo "  Sentinel-2 layer (10m resolution, updates every ~6h from ESA open data):"
echo "    Browser:  http://${NODE_IP}:${TILE_PORT}/sentinel-source.xml"
echo "    USB push: adb push $SATMAP_DIR/atak_sentinel_source.xml /sdcard/atak/imagery/"
echo "    NOTE: Sentinel-2 layer will show 503 until the first poll completes (~6h)."
echo "          Force an immediate poll: sudo systemctl restart rtak-satmap"
echo ""
fi
echo "  In ATAK: Map → Layers — layers appear automatically after files are saved."
echo "  Stack both layers: Sentinel-2 base, RF satellite on top, set opacity ~70%."
echo ""
echo "Hardware check:"
echo "  RTL-SDR detected: $(lsusb 2>/dev/null | grep -i rtl || echo 'not detected — plug in RTL-SDR')"
echo "  Antenna: connect 137 MHz turnstile or QFH to RTL-SDR SMA port"
echo ""
echo "First pass will be scheduled automatically — check the log to see timing:"
echo "  sudo journalctl -u rtak-satmap -f"
