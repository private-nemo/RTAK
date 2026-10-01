# T-Beam v1.1 as a Resilient Reticulum Repeater Node

## Overview

A LilyGO T-Beam v1.1 (ESP32 + SX1278 LoRa + 18650 battery management) makes an excellent
low-power, standalone Reticulum infrastructure node. Flashed with RNode firmware and configured
as a Transport Node, it can forward packets for all other nodes in the mesh.

---

## Step 1 — Flash RNode Firmware

Install the config tool on any computer with Python:

```bash
pip install rnodeconf
```

Connect the T-Beam via USB, then run the autoinstaller:

```bash
rnodeconf --autoinstall
```

This detects your board, downloads the correct ESP32 firmware, and flashes it automatically.
After flashing, set operating frequency via EEPROM (choose your regulatory band):

```bash
# US 915 MHz example
rnodeconf /dev/ttyUSB0 --freq 915000000 --bw 125000 --txp 17 --sf 8 --cr 5
```

---

## Step 2 — Configure Reticulum as a Transport Node

Edit `~/.reticulum/config` (or `/etc/reticulum/config` on a server install):

```ini
[reticulum]
  enable_transport = Yes      # This is what makes it a repeater/router

[interface:lora_tbeam]
  type             = RNodeInterface
  interface_enabled = True
  outgoing         = True
  port             = /dev/ttyUSB0    # adjust as needed (COM3 on Windows)
  speed            = 115200
```

`enable_transport = Yes` allows the instance to forward packets destined for other nodes —
without this it is a leaf node only and will not repeat traffic.

---

## Step 3 — Resilience Hardening

### Weatherproofing
- Use a **NEMA 4X / IP67 junction box** — standard 3D-printed PLA degrades in UV and leaks
- Feed antenna and power cables through **waterproof cable glands**
- Seal any remaining gaps with silicone

### Power
The T-Beam's built-in 18650 holder gives ~12–24h on a single cell. For permanent outdoor deployment:

- Add a **6V–9V solar panel** feeding a **dedicated solar charge controller** wired to the
  T-Beam's battery terminals (or JST connector)
- A 5W panel + 3500mAh 18650 handles most temperate-climate deployments indefinitely
- Consider a second 18650 in parallel via a protected dual-cell holder for cloudy stretches

### Antenna
Never use the stock rubber duck for a fixed repeater. Upgrade to:

- **Fiberglass collinear** matched to your band (915/868/433 MHz) — 3–6 dBi gain
- **Low-loss coaxial**: LMR-240 for runs under ~5m, LMR-400 for longer runs
- **SMA male pigtail** at the T-Beam end; N-type at the antenna base

Signal loss in cheap RG-58 cable at 915 MHz over 5m can easily eat half your TX budget.

### Remote Management
Configure remote admin via Reticulum's **LXMF** or a backchannel interface (TCP over WiFi or
another LoRa channel) **before** deploying to a hard-to-reach location. Climbing a mast for a
config tweak is not fun.

---

## Frequency / Band Notes

| Region | Band | Typical Freq |
|---|---|---|
| US/Canada | 915 MHz ISM | 915.0 MHz |
| EU | 868 MHz SRD | 868.0–868.6 MHz |
| Global (long range) | 433 MHz | 433.175 MHz |

The T-Beam v1.1 uses the **SX1278** which covers 137–525 MHz — for 433 MHz it works natively.
For 915/868 MHz you need the **T-Beam Supreme** (SX1262) instead.

**If you have a T-Beam v1.1 and need 915/868 MHz coverage: use it for 433 MHz and pair with a
T-Beam Supreme on 915 MHz — exactly the dual-RNode setup in this repo's RTAK OmniNode.**

---

## Quick Deployment Checklist

- [ ] RNode firmware flashed and EEPROM parameters set
- [ ] `enable_transport = Yes` in Reticulum config
- [ ] Tested on bench: traffic from another node routes through this one
- [ ] Upgraded antenna installed, cable loss acceptable
- [ ] IP67 enclosure with waterproof glands
- [ ] Solar + charge controller (or verified grid power path)
- [ ] Remote admin channel configured and tested
- [ ] Node hash shared with peer operators

---

## Sources

- Reticulum Network Stack docs: https://reticulum.network
- RNode firmware / rnodeconf: https://github.com/markqvist/RNode_Firmware
- r/meshtastic repeater thread (build suggestions, 2026)

---

## Further Reading (Video)

- **The Tech Prepper** — "Reticulum - Wi-Fi + LoRa RNode Transport Architecture and Field Test" (~10 min)
  YouTube search: `Reticulum Wi-Fi LoRa RNode Transport Architecture Field Test The Tech Prepper`

- **Dude Tested** — "Building a Meshtastic Spec 5 Trekker / Lilygo T-BEAM Node" (~5 min, #hamradio)
  YouTube search: `Building Meshtastic Spec 5 Trekker Lilygo T-BEAM Node Dude Tested`

> Note: Meshtastic content is relevant for hardware technique and enclosure ideas even though
> RTAK uses Reticulum rather than Meshtastic firmware.
