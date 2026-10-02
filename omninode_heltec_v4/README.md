# RTAK OmniNode — Heltec V4 Variant

Compact, lower-cost OmniNode using **Heltec WiFi LoRa 32 V4** boards as the radio layer.
Functionally identical to the T-Beam reference build — same RTAK software, same security model,
same TAK gateway + TAK relay capability. Hardware differences are in the radio selection only.

See [BOM.md](BOM.md) for parts list and pricing.

---

## Design Goals

- **Single-board base build** — one Heltec V4 at 915 MHz; fully operational RTAK node
- **Optional dual-band** — add a second radio (V4 470 SKU, T-Beam v1.1, or V3) for 433 MHz
- **Lower cost** — ~$40–80 less than the T-Beam Supreme + T-Beam v1.1 radio pair
- **Smaller footprint** — V4 is 57 × 25 mm vs T-Beam Supreme at ~120 × 35 mm
- **Both TAK roles** — acts as TAK gateway (LoRa mesh → ATAK CoT SA tracks) and TAK relay (routes encrypted CoT between nodes over Reticulum)

---

## What You Lose vs T-Beam Build

| Feature | Notes |
|---|---|
| Built-in GPS | T-Beam Supreme has onboard GPS; V4 does not. Node location must be set manually in Reticulum config or via external USB GPS dongle if needed. |
| Battery management | T-Beam has a built-in 18650 holder. V4 draws power from the SBC USB port only — the SBC's UPS/power bank covers the whole node. |

---

## Hardware Overview

### Base build (single-band)

```
SBC (Pi 3A+ / 4B / Orange Pi Zero 2W)
  └── USB → Heltec LoRa32 V4 (915 MHz, SX1262) — RNode firmware
```

### Dual-band build (optional)

```
SBC (Pi 3A+ / 4B / Orange Pi Zero 2W)
  ├── USB → Heltec LoRa32 V4 (915 MHz, SX1262) — primary RNode
  └── USB → [one of]:
        Heltec LoRa32 V4 (470 MHz SKU, SX1262)  — preferred, same form factor
        LilyGO T-Beam v1.1 (433 MHz, SX1278)    — from main RTAK BOM, well-tested
        Heltec LoRa32 V3 (868 MHz SKU, SX1262)  — budget option, older chip
```

The software stack is identical in both configurations — the dual-band Reticulum config
in `setup_pi.sh` already handles two RNode interfaces. On a base build, simply disable
the second interface in `/etc/reticulum/config`.

---

## Assembly

### Step 1 — Flash the Heltec V4 as an RNode

Install rnodeconf on any machine with Python:

```bash
pip install rnodeconf
```

Connect the V4 via USB-C, then run the autoinstaller:

```bash
rnodeconf --autoinstall /dev/ttyUSB0
```

Select **Heltec LoRa32 V4** when prompted. If the V4 is not listed in your version of rnodeconf,
update first:

```bash
pip install --upgrade rnodeconf
```

After flashing, set frequency parameters:

```bash
# 915 MHz primary radio
rnodeconf /dev/ttyUSB0 --freq 915000000 --bw 125000 --txp 17 --sf 8 --cr 5
```

If building dual-band, flash and configure the second board on `/dev/ttyUSB1`:

```bash
# 433 MHz second radio (V4 470 SKU or T-Beam v1.1)
rnodeconf --autoinstall /dev/ttyUSB1
rnodeconf /dev/ttyUSB1 --freq 433175000 --bw 125000 --txp 17 --sf 8 --cr 5
```

**Never power a LoRa board without an antenna attached.**

---

### Step 2 — Connect radios to the SBC

- Pi 3A+ / Orange Pi Zero 2W: connect both V4 boards to a USB 2.0 hub, hub to the SBC's USB port
- Pi 4B: plug directly into USB ports — no hub needed

Verify port assignments:

```bash
ls /dev/ttyUSB*
dmesg | grep ttyUSB
```

Note which `/dev/ttyUSB*` is which board. Unplug one at a time to confirm if uncertain.
To make assignments persistent across reboots, create udev rules by board serial number:

```bash
udevadm info -a -n /dev/ttyUSB0 | grep '{serial}'
```

Add to `/etc/udev/rules.d/99-rtak.rules`:

```
SUBSYSTEM=="tty", ATTRS{serial}=="<915-board-serial>", SYMLINK+="rtak_915"
SUBSYSTEM=="tty", ATTRS{serial}=="<433-board-serial>", SYMLINK+="rtak_433"
```

Then use `/dev/rtak_915` and `/dev/rtak_433` in the Reticulum config.

---

### Step 3 — Deploy RTAK software

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/private-nemo/RTAK.git
cd RTAK
sudo bash setup_pi.sh
```

The setup script installs and configures the full RTAK stack (Reticulum, FreeTAKServer,
rtak-bridge, TLS certs, firewall). Default Reticulum config expects `/dev/ttyUSB0` (915)
and `/dev/ttyUSB1` (433). If using udev symlinks or different ports, edit before starting:

```bash
sudo nano /etc/reticulum/config
```

**Base build (single radio)** — disable the second interface block:

```ini
[interface:lora_433]
  interface_enabled = False
```

---

### Step 4 — Start services and share your node hash

```bash
sudo systemctl start freetakserver rtak-bridge
sudo journalctl -u rtak-bridge -f
```

The bridge prints your node's Reticulum hash on first start:

```
RTAK bridge address: <a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6>
```

Share this hash with other RTAK node operators. They add it to their `/opt/rtak/rtak_peers.txt`;
you add theirs to yours. See the root README for the full peering and certificate workflow.

---

## OLED Status Display

The Heltec V4's built-in 0.96" OLED (128×64) can show node status while the board is running
as an RNode. By default, the RNode firmware displays radio parameters (frequency, bandwidth,
spreading factor) and packet counters on the OLED. No additional configuration is needed —
this is a passive benefit over the T-Beam reference build, which has no display.

---

## GPS — What's Missing and How to Add It

The Heltec V4 has no onboard GPS. For the main RTAK use case (relaying CoT between ATAK
clients), node GPS position is not required — the node just routes packets.

If your use case requires the OmniNode itself to appear as a tracked entity on ATAK:

- **Option A:** Set a static location in the Reticulum announce — edit the node's
  `~/.reticulum/config` identity section to include a fixed GPS coordinate.
- **Option B:** Add a USB GPS dongle (u-blox M8 or similar, ~$15–20). Feed NMEA
  to `gpsd` on the SBC; extend the rtak-bridge to read `gpsd` and emit CoT position reports.
- **Option C:** Use a T-Beam Supreme for the 915 MHz slot instead of the V4 (T-Beam has GPS).
  The rest of the design is compatible — just note the larger T-Beam form factor.

---

## Reticulum Config Reference (dual-band V4 build)

Excerpt for `/etc/reticulum/config` — adjust ports to match your actual assignments:

```ini
[reticulum]
  enable_transport = Yes

[interface:lora_915]
  type              = RNodeInterface
  interface_enabled = True
  outgoing          = True
  port              = /dev/rtak_915
  frequency         = 915000000
  bandwidth         = 125000
  txpower           = 17
  spreadingfactor   = 8
  codingrate        = 5

[interface:lora_433]
  type              = RNodeInterface
  interface_enabled = True
  outgoing          = True
  port              = /dev/rtak_433
  frequency         = 433175000
  bandwidth         = 125000
  txpower           = 17
  spreadingfactor   = 8
  codingrate        = 5
```

---

## Relationship to Other RTAK Builds

| Build | Radio | SBC | GPS | OLED | Reference |
|---|---|---|---|---|---|
| Reference (Pi 4B) | T-Beam Supreme (915) + T-Beam v1.1 (433) | Pi 4B | Yes | No | root README |
| Orange Pi Zero 2W | T-Beam Supreme + T-Beam v1.1 | OPi Zero 2W | Yes | No | orange_pi_zero_2w/ |
| **Heltec V4 (this)** | **Heltec V4 (915) ± V4/T-Beam (433)** | **Any Pi** | **No** | **Yes** | **this directory** |

All three builds run the same RTAK software stack and are fully interoperable on the network.
