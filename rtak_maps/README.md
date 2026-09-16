# RTAK Offline Maps

Operational security guide and setup workflow for using offline satellite imagery in ATAK without leaking your area of operations to commercial tile providers.

---

## Why Online Map Sources Are a Security Problem

When ATAK fetches tiles from Google Maps, Bing, ArcGIS Online, or any commercial provider, each tile request encodes the exact coordinates being viewed and transmits them over the device's internet connection — WiFi or cellular — completely outside of Reticulum's encryption. The tile provider learns your operational area, when you're actively using the map, and your device's IP or carrier identity. This happens regardless of how well RTAK encrypts CoT traffic.

**The fix is not a code patch.** ATAK's online sources are configured layers, not hardwired defaults. You replace them with an offline layer and the leak disappears at the source.

---

## How ATAK Map Sources Work

ATAK maintains a stack of map layers. Each layer is either:
- **Online** — fetches tiles from a URL (Google, Bing, WMS servers, etc.)
- **Offline** — renders from a local file on the device (`.mbtiles`, CIB, DTED)

When an offline layer is set as the active base layer and online sources are removed or disabled, ATAK renders entirely from local storage. No network requests are made for map tiles at all.

ATAK auto-discovers `.mbtiles` files placed in `/sdcard/atak/imagery/` on the Android device. Once a file is there, it appears in the map layer list automatically.

---

## Step 1 — Generate Offline Tiles

### Option A — MOBAC (Cross-platform, recommended for most users)

**Mobile Atlas Creator** pulls tiles from any configured online source and packages them as a `.mbtiles` file. Run this before operations on any internet-connected machine — the resulting file contains all the imagery you need.

1. Download MOBAC: <https://mobac.sourceforge.io/>
2. Launch MOBAC (requires Java 11+)
3. In the **Map Source** dropdown, select your imagery source:
   - `Google Maps Satellite` — sub-meter in populated areas, global
   - `Bing Maps Aerial` — comparable to Google, good global coverage
   - `OpenStreetMap` — vector/road only, no satellite
4. In the map view, draw a selection rectangle over your AO
5. In **Zoom Levels**, select the range you need:
   - Zoom 10–14: good tactical overview (covers large areas, smaller file size)
   - Zoom 14–17: high detail (buildings, roads clearly visible, larger file)
   - Typical tactical selection: **12–16**
6. Set **Atlas Format** to `MBTiles (SQLite)`
7. Click **Create Atlas** — MOBAC packages all selected tiles into a single `.mbtiles` file
8. Output file is in the `atlases/` folder in your MOBAC directory

> File size guide: a 10×10 km AO at zoom 12–16 is roughly 200–800 MB depending on terrain complexity.

---

### Option B — SAS Planet (Windows, most source options)

SAS Planet supports the widest range of imagery sources including high-resolution commercial providers.

1. Download SAS Planet: <https://www.sasgis.org/sasplaneta/>
2. Launch, select your map source from the top-left dropdown (Google Satellite, Yandex Satellite, Bing, etc.)
3. Navigate to your AO
4. Right-click → **Selection Manager** → draw a rectangle
5. **Download** → select zoom levels → wait for download to complete
6. **Stitch** → select output format **SQLite (MBTiles)** → export

---

### Option C — Sentinel-2 via Copernicus Browser (Free, 10m resolution, global)

Sentinel-2 is a European Space Agency program providing free, openly licensed 10m/pixel satellite imagery updated every 5 days globally. This is the best free source for areas outside the US.

1. Go to: <https://browser.dataspace.copernicus.eu/>
2. Create a free Copernicus account (required for download)
3. Navigate to your AO on the map
4. Set the date range — pick a recent clear day (use the cloud cover slider)
5. Select **Sentinel-2 L2A**, band combination **True Color**
6. Click **Download** → choose **GeoTIFF** format, full resolution
7. Convert the GeoTIFF to `.mbtiles` using GDAL (see conversion step below)

**GDAL conversion (Linux/Mac):**
```bash
# Install GDAL if needed
sudo apt-get install gdal-bin    # Debian/Ubuntu
brew install gdal                # macOS

# Translate GeoTIFF to standard projection (if needed)
gdalwarp -t_srs EPSG:3857 input.tif reprojected.tif

# Generate XYZ tiles
gdal2tiles.py --zoom=10-16 --webviewer=none reprojected.tif tiles/

# Package tiles into mbtiles
# Install mb-util: pip install mbutil
mb-util --image_format=jpg tiles/ output.mbtiles
```

---

### Option D — USGS National Map (US only, up to 1m resolution)

1. Go to: <https://apps.nationalmap.gov/downloader/>
2. Click **Imagery** in the data type selector
3. Draw your AO on the map
4. Select resolution (1m NAIP imagery where available) and download
5. Convert to `.mbtiles` using the GDAL steps above

---

## Step 2 — Load Tiles onto the Device

1. Connect the Android device via USB (or transfer over local network/SD card)
2. Copy the `.mbtiles` file to: `/sdcard/atak/imagery/rtak-base.mbtiles`
3. If the `imagery/` folder doesn't exist, create it

ATAK will discover the file automatically the next time it scans for map sources (on startup or when you open the map layer settings).

---

## Step 3 — Configure ATAK to Use Offline Layer

1. In ATAK: tap the **Map** icon → **Layers** (or **Map Manager**)
2. Find your imported layer (`rtak-base` or the filename you used)
3. Tap it → **Set as Default Base Map**
4. Scroll through the active layers list and **remove or disable** any online sources (Google Satellite, Bing, etc.)

ATAK now renders entirely from local storage. You can verify: enable airplane mode and confirm the map still loads correctly.

---

## Step 4 — Distribute via ATAK Data Package (Team Deployment)

For multi-operator deployments, use `generate_map_package.py` (included in this directory) to create a distributable ATAK data package that pre-configures the offline layer for all operators:

```bash
python3 generate_map_package.py \
    --name "RTAK Base Map" \
    --mbtiles rtak-base.mbtiles \
    --output rtak-maps-package.zip
```

This produces `rtak-maps-package.zip`. Distribute it to each operator via:
- ATAK's built-in **Sync** over the local network
- USB transfer
- FreeTAKServer data package sync (operators connected to the OmniNode receive it automatically)

**To import on each device:**
1. Copy `rtak-maps-package.zip` to the device
2. In ATAK: Settings → Data Packages → Import → select the zip
3. The offline map layer is now configured and set as default

---

## Step 5 — Network Isolation (Final Backstop)

Even with offline tiles configured, the safest operational posture is to ensure the Android device has no path to the internet at all during ops:

1. Enable **Airplane Mode**
2. Enable **WiFi only** (to reach the OmniNode)
3. Leave cellular, Bluetooth off

With the OmniNode acting as a private WiFi AP with no internet uplink, tile requests physically cannot reach any external server — even if someone accidentally re-enables an online map source. The isolation is enforced at the network level, not just at the application level.

---

## Imagery Source Comparison

| Source | Resolution | Coverage | Cost | License |
|---|---|---|---|---|
| Google Satellite (via MOBAC) | Sub-meter in cities, ~1m rural | Global | Free (personal use) | Google ToS — do not redistribute |
| Bing Aerial (via MOBAC/SAS Planet) | Similar to Google | Global | Free (personal use) | Microsoft ToS |
| Sentinel-2 (Copernicus) | 10m | Global | Free | Open (CC BY-SA) |
| USGS NAIP | 1m | Continental US | Free | Public domain |
| OpenAerialMap | Varies, some sub-meter | Patchy global | Free | Open |

> For operational use with a small trusted team, MOBAC + Google/Bing gives the best visual resolution. For redistribution or publishing, use Sentinel-2 or USGS (open licenses).

---

## Repository

<https://github.com/private-nemo/RTAK>
