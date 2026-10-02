# RTAK OmniNode — Heltec V4 Variant BOM

Compact, lower-cost RTAK OmniNode using Heltec LoRa32 V4 boards in place of LilyGO T-Beams.
Base build is single-band (915 MHz). Dual-band is an optional upgrade — add a second radio board.

---

## Brain

| Component | Part | Source | Est. Price |
|---|---|---|---|
| SBC | Raspberry Pi 3A+ or 4B (2 GB+) | raspberrypi.com / Adafruit | $35–55 |
| microSD | SanDisk 32 GB Extreme A2 | Amazon | ~$11 |
| OS | Raspberry Pi OS Lite 64-bit (Bookworm) | raspberrypi.com | free |

**Orange Pi Zero 2W** (2 GB) is a viable cheaper alternative (~$22–28). See orange_pi_zero_2w/BOM.md for that SBC's power and USB notes — they apply here too.

---

## Radio — Base Build (single-band 915 MHz)

| Component | Part | Source | Est. Price |
|---|---|---|---|
| 915 MHz RNode | Heltec WiFi LoRa 32 V4 — 915 MHz (ESP32-S3 + SX1262) | heltec.org / Amazon | ~$22 |
| 915 MHz antenna | SMA-male stub, tuned 915 MHz, 3 dBi | Amazon | ~$11 |

The V4 ships with the SX1262 chip covering 150–960 MHz. Order the **915 MHz SKU** (labeled
"868-915 MHz" on the Heltec store). Do not order the 470 MHz or 2.4 GHz variant.

---

## Radio — Dual-Band Upgrade (optional, adds 433 MHz)

Add one of the following as a second radio for 433 MHz coverage:

| Option | Part | Notes | Est. Price |
|---|---|---|---|
| A (preferred) | Heltec WiFi LoRa 32 V4 — 470 MHz SKU | SX1262, covers 433 MHz; same USB-C as primary | ~$22 |
| B | LilyGO T-Beam v1.1 — select 433 MHz at checkout | SX1278, 433 MHz only; proven with rnodeconf | ~$31 |
| C | Heltec WiFi LoRa 32 V3 — 868 MHz SKU | SX1262; covers 433–915; older ESP32 not S3 | ~$18 |

Option A keeps the form factor consistent — two identical V4s, different frequency SKUs.
Option B is the same 433 MHz board used in the main Pi 4B OmniNode; well-tested.

---

## USB

The Pi 3A+ has **one USB-A** port. Pi 4B has four USB 3.0 ports (can run 2 radios directly).

| Condition | Part | Est. Price |
|---|---|---|
| Pi 3A+ or Orange Pi Zero 2W (any config) | Sabrent 4-port USB 2.0 hub | ~$9 |
| Pi 4B + single radio | No hub needed | — |
| Pi 4B + dual radio | No hub needed | — |

All radio serial traffic runs at 115200 baud — USB 2.0 is entirely sufficient.

---

## Power

| Option | Part | Est. Price |
|---|---|---|
| Waveshare UPS HAT D (Pi 4B only) | 2× 21700 cells, GPIO header | ~$25 |
| 21700 cells × 2 | Samsung 48G or Keeppower P2150U | ~$18 |
| USB-C power bank (Pi 3A+ / OPi) | Anker 737 or similar, PD passthrough | ~$50 |
| Short USB-C cable | 0.3 m, 60W rated | ~$8 |

The Heltec V4 boards are USB-C powered — they do **not** require separate power; they draw from
the SBC's USB port (5V, ~350 mA per board at full TX power).

---

## Per-Node Cost Summary

| Configuration | Est. Total |
|---|---|
| Pi 3A+ + single Heltec V4 + USB bank | ~$125 |
| Pi 3A+ + dual Heltec V4 + USB bank | ~$147 |
| Pi 4B + single Heltec V4 + UPS HAT | ~$164 |
| Pi 4B + dual Heltec V4 + UPS HAT | ~$186 |

Roughly **$40–80 cheaper** than the T-Beam reference build at equivalent specs.

---

## Key Differences vs T-Beam Build

| Item | T-Beam Build | Heltec V4 Build |
|---|---|---|
| 915 MHz chip | SX1262 (T-Beam Supreme) | SX1262 (V4) — same chip |
| 433 MHz chip | SX1278 (T-Beam v1.1) | SX1262 (V4 470 SKU) or SX1278 (T-Beam v1.1) |
| Built-in GPS | Yes (T-Beam Supreme) | **No** — GPS not available on V4 |
| OLED display | No | **Yes** — 0.96" 128×64 on V4 |
| Battery management | Yes (T-Beam 18650 holder) | **No** — power from SBC USB only |
| Form factor | 120 × 35 mm (T-Beam) | 57 × 25 mm (V4) — significantly smaller |
| Radio cost (pair) | ~$68 (Supreme + v1.1) | ~$44 (dual V4) |
| rnodeconf support | First-class | Supported (verify board in autoinstall list) |
