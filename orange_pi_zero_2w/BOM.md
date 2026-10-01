# RTAK OmniNode — Orange Pi Zero 2W Variant BOM

Hardware list for the Orange Pi Zero 2W edition of the RTAK OmniNode.
For the Raspberry Pi 4B / CM4 reference build, see the root README.

## Brain

| Component | Part | Source | Est. Price |
|---|---|---|---|
| SBC | Orange Pi Zero 2W (2 GB recommended) | orangepi.org / AliExpress | ~$22–28 |
| microSD | 32 GB Class 10 / A1 (e.g. SanDisk Endurance) | Amazon | ~$11 |
| OS | Armbian Bookworm (minimal, no desktop) | armbian.com | free |

**Why 2 GB:** FreeTAKServer + Reticulum + bridge together sit comfortably under 512 MB idle but peak higher under load. 2 GB gives clear headroom. 1 GB will work at reduced ATAK client count.

## Radio (unchanged from Pi build)

| Component | Part | Notes |
|---|---|---|
| 915 MHz RNode | LilyGO T-Beam Supreme (ESP32-S3 + SX1262 + GPS) | Flash as RNode via rnodeconf |
| 433 MHz RNode | LilyGO T-Beam v1.1 (SX1278) | Select 433 MHz at checkout |
| 915 MHz antenna | SMA stub, tuned 915 MHz | ~$12 |
| 433 MHz antenna | SMA stub, tuned 433 MHz | ~$12 |

Both T-Beams connect via USB — radio stack is identical to the Pi build.

## USB

The Orange Pi Zero 2W has **one USB-A 2.0 port** built in (plus USB-C for power).
Both T-Beams need USB, so a small hub is still required.

| Component | Part | Est. Price |
|---|---|---|
| USB hub | Sabrent 4-port USB 2.0 hub (compact, bus-powered) | ~$9 |

USB 2.0 is sufficient — T-Beam serial consoles run at 115200 baud, well under USB 2.0 limits.

## Power

The Orange Pi Zero 2W uses **USB-C** for power input (5V/3A).
The Waveshare UPS HAT from the Pi build is Pi-HAT form factor and **does not fit**.

### Option A — Field portable (recommended)

| Component | Part | Est. Price |
|---|---|---|
| UPS power bank | Anker 737 or similar with USB-C PD passthrough | ~$50 |
| USB-C cable (short) | 0.3m USB-C to USB-C, 60W+ rated | ~$8 |

A PD passthrough bank charges while powering the board. Runtime: ~8–12h on a 26800 mAh bank.

### Option B — HAT-style UPS (compact build)

| Component | Part | Est. Price |
|---|---|---|
| UPS module | X1501 / OLAH UPS for Orange Pi Zero 2W | ~$18–25 (AliExpress) |
| Battery | 18650 cell × 1 (3000+ mAh) | ~$8 |

The X1501-style module sits under the OPi and connects to the 26-pin header (uses UART/I2C for status only — power pins are standard). Check vendor compatibility with OPi Zero 2W before ordering.

## Enclosure

No commercial cases are available for the OPi Zero 2W + dual T-Beam USB hub combo as of 2026.
Design an OpenSCAD enclosure sized to:

- OPi Zero 2W board: **70 mm × 46 mm**
- Clearance for USB-A port (long side), USB-C power (short side), HDMI (short side)
- 4× USB hub footprint below or beside
- Antenna SMA bulkheads × 2 on exterior

## Cost Summary

| Category | Option A (power bank) | Option B (HAT UPS) |
|---|---|---|
| Brain + SD | ~$39 | ~$39 |
| Radio + antennas | ~$102 | ~$102 |
| USB hub | ~$9 | ~$9 |
| Power | ~$58 | ~$33 |
| **Total** | **~$208** | **~$183** |

Roughly $10–35 cheaper than the Pi 4B reference build with more RAM.

## Key Differences vs Pi 4B Build

| Item | Pi 4B Build | OPi Zero 2W Build |
|---|---|---|
| RAM | 4 GB | 1–4 GB (2 GB rec.) |
| WiFi | 2.4 GHz only | 2.4 + 5 GHz (ac) |
| USB-A ports | 4× USB 3.0 | 1× USB 2.0 (hub required) |
| Power connector | Micro-USB / USB-C (4B) | USB-C |
| GPIO header | 40-pin | 26-pin (no GPIOs used in RTAK BOM) |
| OS | Raspberry Pi OS Lite | Armbian Bookworm (minimal) |
| Setup script | setup_pi.sh | setup_orangepi.sh |
| Form factor | 85 × 56 mm | 70 × 46 mm |
| Approx. cost (node) | ~$220 | ~$183–208 |
