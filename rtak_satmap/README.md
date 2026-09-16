# RTAK SatMap — Live Satellite Imagery for ATAK

Two complementary imagery sources, both served from the OmniNode as ATAK map layers:

| Layer | Resolution | Source | Update cycle | Cost |
|---|---|---|---|---|
| RF satellite (NOAA/Meteor) | ~4 km/px | 137 MHz receive | ~90 min | Free, no account |
| Sentinel-2 (v1.1) | 10 m/px | ESA open data API | ~6 h | Free, no account |

Both are served as standard ATAK custom tile sources — no ATAK plugin code required. Stack them: Sentinel-2 as the high-res base, RF satellite on top for live cloud/weather context.

---

## How It Works

### RF Satellite Layer (NOAA/Meteor — 4 km resolution)

```
NOAA/Meteor satellite (LEO, 137 MHz)
        ↓  RF signal
RTL-SDR dongle (USB, on OmniNode)
        ↓  raw IQ samples
SatDump (automated decode + georeferencing)
        ↓  GeoTIFF (visible + IR bands, georeferenced)
GDAL (gdalwarp + gdal2tiles)
        ↓  XYZ map tiles (PNG, EPSG:3857)
Python tile server (port 8889)
        ↓  http://<node-ip>:8889/latest/{z}/{x}/{y}.png
ATAK → weather/cloud layer on tactical map
```

### Sentinel-2 Layer (ESA open data — 10 m resolution)

```
Element84 Earth Search STAC API (public, no account)
        ↓  scene metadata + COG URL for latest low-cloud image
GDAL /vsicurl/ (HTTP range request — streams only the needed area)
        ↓  crop + reproject to EPSG:3857
gdal2tiles → XYZ tiles
        ↓  http://<node-ip>:8889/sentinel-latest/{z}/{x}/{y}.png
ATAK → high-res terrain/urban base layer
```

No account, no API key, no registration required for Sentinel-2. ESA's Copernicus program makes all Sentinel-2 L2A imagery freely available. The pipeline queries the Element84 Earth Search catalog and streams only the area around your observer location — no full scene download.

The pipeline runs as a systemd service managing both sources simultaneously.

---

## Additional Hardware Required

| Part | Purpose | Source | Price |
|---|---|---|---|
| RTL-SDR V4 dongle | Software-defined radio receiver | [rtl-sdr.com](https://www.rtl-sdr.com/buy-rtl-sdr-dvb-t-dongles/) | ~$35 |
| 137 MHz turnstile antenna | Circular polarization for LEO satellites | [Nooelec](https://www.nooelec.com/) · [wimo.com](https://www.wimo.com) | ~$30–50 |
| SMA extension cable (1–2m) | Route antenna outside the enclosure | Amazon | ~$8 |

> **Antenna notes:** A turnstile or QFH (quadrifilar helix) antenna is strongly preferred over a whip — the circular polarization matches the satellite's signal and significantly improves reception. A basic V-dipole angled at ~120° works as a fallback. Mount the antenna outdoors with clear sky view for best results.

> **The RTL-SDR V4** (released 2023) has an improved oscillator and built-in bias-T for LNA power. Earlier V3 dongles work too. Avoid generic "DVB-T" sticks — they often have poor thermal stability.

The RTL-SDR connects to the existing USB hub already on the OmniNode. No additional HAT or GPIO wiring required.

---

## Satellites Tracked

### NOAA APT (137 MHz) — Primary

| Satellite | Frequency | Resolution | Status |
|---|---|---|---|
| NOAA 15 | 137.620 MHz | ~4 km/pixel | Operational |
| NOAA 18 | 137.9125 MHz | ~4 km/pixel | Operational |
| NOAA 19 | 137.100 MHz | ~4 km/pixel | Primary |

APT (Automatic Picture Transmission) sends two image channels: visible light and thermal infrared. Useful for cloud cover, storm systems, and terrain/sea surface temperature.

Passes over any given location every ~90 minutes. A high-elevation pass (>60°) produces a ~2,000 km wide swath of imagery.

### Meteor-M2 LRPT (137 MHz) — Secondary

| Satellite | Frequency | Resolution |
|---|---|---|
| Meteor-M2-3 | 137.900 MHz | ~1 km/pixel |
| Meteor-M2-4 | 137.900 MHz | ~1 km/pixel |

Higher resolution than NOAA APT. Russian meteorological satellite series. LRPT (Low Rate Picture Transmission) provides visible, near-IR, and thermal bands.

---

## OmniNode Setup

Run `setup_satmap.sh` after `setup_pi.sh` has been completed:

```bash
cd RTAK
sudo bash rtak_satmap/setup_satmap.sh --lat 38.9 --lon -77.0
# replace with your actual coordinates
```

With custom elevation and tile port:

```bash
sudo bash rtak_satmap/setup_satmap.sh --lat 38.9 --lon -77.0 --alt 120 --port 8889
```

The script:
1. Installs SatDump (pre-built ARM64 .deb, or builds from source as fallback)
2. Installs GDAL and `pyorbital` for tile generation and pass prediction
3. Blacklists conflicting DVB-T kernel modules
4. Deploys `satmap_pipeline.py` to `/opt/rtak/`
5. Opens port 8889/tcp in UFW
6. Installs and starts `rtak-satmap` systemd service

Check logs after setup:

```bash
sudo journalctl -u rtak-satmap -f
```

You should see TLE download, pass predictions, and the next scheduled recording time.

---

## ATAK Setup (per device)

### Step 1 — Get the map source file

The tile server auto-fills its own IP address in the map source XML. No manual editing needed.

**Option A — Download directly from ATAK's built-in browser (no USB required):**

1. In ATAK, open the built-in browser and navigate to:
   ```
   http://<node-ip>:8889/source.xml
   ```
2. Android prompts to save the file — save to `/sdcard/atak/imagery/`

**Option B — Copy via USB:**

After running `setup_satmap.sh`, a pre-filled XML is written to `/opt/rtak/satmap/atak_satmap_source.xml` with the correct node IP already embedded:

```bash
adb push /opt/rtak/satmap/atak_satmap_source.xml /sdcard/atak/imagery/
```

**Option C — Manual fallback:**

Edit `rtak_satmap/atak_satmap_source.xml`, replace `<node-ip>` with the OmniNode's LAN IP, and copy to `/sdcard/atak/imagery/`.

### Step 2 — Enable the layer in ATAK

1. ATAK → **Map** → **Layers** (or Map Manager)
2. Find **RTAK SatMap — Latest Pass** in the layer list
3. Enable it and position it above the base map layer
4. Set opacity to ~70% so tactical overlays remain visible underneath

### Step 3 — Add the Sentinel-2 layer (v1.1)

Same process, second XML file:

**Option A — Browser download:**
```
http://<node-ip>:8889/sentinel-source.xml
```
Save to `/sdcard/atak/imagery/`. Returns 503 until the first Sentinel poll completes — typically within the first 6 hours of service start.

**Option B — USB push:**
```bash
adb push /opt/rtak/satmap/atak_sentinel_source.xml /sdcard/atak/imagery/
```

### Step 4 — Layer stacking in ATAK

1. ATAK → **Map → Layers**
2. Enable **RTAK SatMap — Latest Pass** (RF satellite)
3. Enable **RTAK SatMap — Sentinel-2**
4. Order: Sentinel-2 below RF satellite
5. Set RF satellite layer opacity to ~70% so terrain/features show through

**Result:** 10 m Sentinel-2 base layer with live weather/cloud data on top, both updating automatically.

### Verify

```bash
curl http://<node-ip>:8889/
```

Returns JSON with status for both layers — RF passes and Sentinel-2 recent scenes.

---

## Pass Scheduling

The pipeline predicts passes 12 hours ahead and reschedules every hour. Passes below 15° peak elevation are skipped (low signal quality). You can verify upcoming passes in the log:

```bash
sudo journalctl -u rtak-satmap | grep "Scheduled:"
```

Example output:
```
Scheduled: NOAA 19 @ 14:23 UTC (peak 67°, 840s, in 3120s)
Scheduled: NOAA 15 @ 16:07 UTC (peak 31°, 620s, in 9240s)
Scheduled: METEOR-M2 3 @ 17:44 UTC (peak 52°, 780s, in 15600s)
```

---

## Sentinel-2 Imagery (v1.1)

Sentinel-2 is a European Space Agency (ESA) Earth observation constellation. All imagery is free and publicly available under the Copernicus Open License.

| Attribute | Value |
|---|---|
| Resolution | 10 m/pixel (true color RGB) |
| Revisit time | ~5 days at equator |
| Coverage | Global |
| Cloud masking | Pipeline skips scenes >20% cloud (configurable) |
| Area fetched | 200 km radius around observer (configurable) |
| Account required | No |
| License | Copernicus Open License — unrestricted use |

The pipeline polls every 6 hours. If a scene from the past 7 days exists with acceptable cloud cover, it tiles and serves it. For more frequent updates, lower `--sentinel-radius-km` (less area = faster tiling).

### Tuning

```bash
# Tighter crop (faster), lower cloud tolerance
sudo bash rtak_satmap/setup_satmap.sh \
    --lat 38.9 --lon -77.0 \
    --sentinel-radius-km 100 \
    --sentinel-cloud-max 10

# Disable Sentinel-2 (RF-only mode)
sudo bash rtak_satmap/setup_satmap.sh \
    --lat 38.9 --lon -77.0 --no-sentinel
```

### Planet Labs API (optional — sub-meter imagery)

If you have a Planet Labs account (Education & Research program is free for qualifying users), pass your API key at setup time:

```bash
sudo bash rtak_satmap/setup_satmap.sh \
    --lat 38.9 --lon -77.0 \
    --planet-key YOUR_PLANET_API_KEY
```

Planet's PlanetScope constellation provides 3–50 cm imagery with daily revisits. The pipeline supports the key slot; full Planet download integration is documented in `satmap_pipeline.py` (see `PLANET_API_KEY` config block).

## Imagery Quality and Coverage

| Factor | Impact |
|---|---|
| Pass elevation | Higher = wider swath, better signal, less noise |
| Antenna placement | Outdoors, unobstructed sky = best results; indoors = significantly degraded |
| Weather (for visual band) | Cloud cover visible in IR; heavy rain can attenuate 137 MHz signal |
| LNA (optional) | Low-noise amplifier in-line with antenna improves signal-to-noise ratio |

A 70°+ elevation pass produces excellent imagery. A 15° pass is marginal — sometimes useful, sometimes too noisy to decode. The pipeline only schedules passes above the configured minimum (default 15°, recommended 20°+ for tactical use).

---

## Optional: LNA for Better Reception

A low-noise amplifier (LNA) inserted between the antenna and RTL-SDR significantly improves reception, especially for low-elevation passes and in RF-noisy environments.

Recommended: **Nooelec LaNA** or **RTL-SDR Blog LNA4ALL** (~$20–30). The RTL-SDR V4 has a built-in bias-T that can power the LNA over the coax — enable it with:

```bash
rtl_biast -b 1  # enable bias-T (5V on center pin)
```

Add this to the SatMap systemd service as an `ExecStartPre=` line if using a bias-T powered LNA.

---

## Operational Security

Satellite imagery reception is entirely passive — the RTL-SDR only receives, never transmits. There is no RF emission, no spectrum license required, and no activity detectable by third parties.

The tile server on port 8889 is accessible only on the OmniNode's LAN (UFW rule allows all LAN traffic on that port, same as FTS and the panic panel). Tiles are served only to devices already connected to the OmniNode network.

---

## Repository

<https://github.com/private-nemo/RTAK>
