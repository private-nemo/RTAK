# RTAK SatMap — Live Satellite Imagery for ATAK

Automated weather satellite reception, processing, and delivery as a live map overlay in ATAK. The OmniNode records satellite passes, converts imagery to map tiles, and serves them via HTTP. ATAK treats the OmniNode as a custom tile source and displays the imagery as a transparent overlay on top of the base map — no ATAK plugin code required.

Imagery updates automatically every ~90 minutes as satellites pass overhead.

---

## How It Works

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
        ↓  HTTP tile requests
ATAK custom map source → live satellite overlay on tactical map
```

The pipeline runs as a systemd service. It predicts upcoming passes, starts recording automatically at the right time, processes the output, and updates the `latest` tile set. ATAK always fetches from `http://<node-ip>:8889/latest/{z}/{x}/{y}.png` — no URL changes needed between passes.

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

### Step 1 — Copy the map source file

Edit `atak_satmap_source.xml`, replace `<node-ip>` with your OmniNode's LAN IP, then copy to the device:

```bash
# Replace 192.168.1.100 with your OmniNode's actual LAN IP
sed 's/<node-ip>/192.168.1.100/g' rtak_satmap/atak_satmap_source.xml \
    > /tmp/rtak_satmap_source.xml

# Transfer to Android via USB:
adb push /tmp/rtak_satmap_source.xml /sdcard/atak/imagery/
```

Or copy the file manually via USB file transfer.

### Step 2 — Enable the layer in ATAK

1. ATAK → **Map** → **Layers** (or Map Manager)
2. Find **RTAK SatMap — Latest Pass** in the layer list
3. Enable it and position it above the base map layer
4. Set opacity to ~70% so tactical overlays remain visible underneath

### Step 3 — Verify

After the next satellite pass (~90 minutes from setup), the imagery will appear automatically on the map without any ATAK restart or reconfiguration.

To check what imagery is currently loaded:

```bash
curl http://<node-ip>:8889/
```

Returns JSON with the current tile set name, timestamp, and recent pass log.

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
