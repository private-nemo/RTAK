# RTAK RelayNode

A solar-powered, weatherproof Reticulum mesh relay for extending RTAK OmniNode coverage in the field. Carries both 915 MHz and 433 MHz LoRa bands. Runs no TAK stack — purely a Reticulum transport relay with store-and-forward LXMF buffering.

No Android device. No FTS. No certs. Just radio and routing.

---

## What It Does

- Receives Reticulum packets on either LoRa band and forwards them to all other interfaces (other LoRa band, WiFi if present)
- Buffers LXMF messages during intermittent contact windows — packets are held in the relay's LXMF store and retransmitted when the destination reappears
- Extends effective OmniNode range by acting as a hilltop or mid-path repeater
- Connects two separate frequency zones (915 MHz and 433 MHz networks become one Reticulum mesh)

`enable_transport = True` in Reticulum config is the only code change needed. The relay requires no whitelisting, no certificates, and no knowledge of ATAK.

---

## Bill of Materials — Per RelayNode

### Compute

| Part | Source | Price |
|---|---|---|
| Raspberry Pi Zero 2W | [Adafruit #5291](https://www.adafruit.com/product/5291) · [PiShop.us](https://www.pishop.us/product/raspberry-pi-zero-2-w/) | $15.00 |
| SanDisk 32GB Extreme A2 microSD | [Amazon B06XYHN68L](https://www.amazon.com/dp/B06XYHN68L) | ~$11 |

### LoRa RNodes

| Part | Source | Price |
|---|---|---|
| LilyGO T-Beam Supreme — 915 MHz (SX1262 + GPS) | [lilygo.cc/products/t-beam-supreme](https://lilygo.cc/products/t-beam-supreme) | $37.12 |
| LilyGO T-Beam v1.1 — **select 433 MHz** at checkout (SX1278) | [lilygo.cc/products/t-beam](https://lilygo.cc/products/t-beam) | $30.77 |
| 915 MHz antenna, 3 dBi, SMA-male (fiberglass whip) | Amazon — search "915MHz LoRa antenna 3dBi SMA" | ~$11 |
| 433 MHz antenna, 3 dBi, SMA-male (fiberglass whip) | Amazon — search "433MHz LoRa antenna 3dBi SMA" | ~$11 |

> Order both T-Beams together from LILYGO — ships as one package. Allow 2–3 weeks from China. Amazon resellers stock both at ~30% markup for faster delivery.

### Power

| Part | Source | Price |
|---|---|---|
| Waveshare Solar Power Manager (D) | [waveshare.com/solar-power-manager-d.htm](https://www.waveshare.com/solar-power-manager-d.htm) · [Amazon](https://www.amazon.com/s?k=waveshare+solar+power+manager+D) | ~$18 |
| 18650 3400mAh lithium cell (Samsung 35E or Panasonic NCR18650B) | Amazon — search "18650 3400mAh protected" | ~$9 |
| 6W 5V solar panel with 5.5×2.1mm barrel plug | Amazon — search "6W 5V solar panel 5.5mm barrel" | ~$15 |

> The Waveshare Solar Power Manager (D) accepts solar input via 5.5mm barrel jack, charges the 18650 cell, and outputs regulated 5V via micro-USB to the Pi Zero. It handles sun/battery switchover automatically.

### Connectivity

| Part | Source | Price |
|---|---|---|
| Micro-USB OTG hub, 4-port compact | Amazon — search "micro USB OTG hub 4 port" | ~$8 |
| Micro-USB OTG adapter (if hub uses USB-A) | Included with most hubs or ~$3 | ~$0–3 |

> The Pi Zero 2W has one USB OTG data port. Both T-Beams connect through this hub. The Pi's PWR IN port receives power from the Solar Power Manager.

### Enclosure

| Part | Source | Price |
|---|---|---|
| IP65 weatherproof junction box, ~200×120×75mm | Amazon — search "IP65 ABS enclosure 200x120x75" | ~$12 |
| M4 nylon standoffs (10mm) × 4 | Amazon / hardware store | ~$3 |
| M4 cable glands (PG9, ×3) | Amazon — search "PG9 cable gland waterproof" | ~$5 |
| Silica gel desiccant packs (2g, × 4) | Amazon | ~$3 |

### Per-Node Cost Summary

| Configuration | Est. Total |
|---|---|
| Dual-band relay (915 + 433 MHz), solar, weatherproof | **~$153** |
| Single-band relay (915 MHz only) | **~$112** |

---

## Assembly Instructions

### 1. Flash the microSD

1. Download [Raspberry Pi OS Lite 32-bit (Bookworm)](https://www.raspberrypi.com/software/operating-systems/) — use the 32-bit armhf image for best Zero 2W compatibility; 64-bit also works.
2. Flash to microSD using Raspberry Pi Imager. In the Imager's "Advanced Options" (gear icon), configure:
   - Enable SSH (password or public key)
   - Set hostname (e.g., `rtak-relay-1`)
   - Configure WiFi if available in the deployment area
3. Eject and insert into the Pi Zero 2W.

---

### 2. Flash RNode firmware onto both T-Beams

Do this from any laptop/desktop with Python 3 before mounting boards in the enclosure.

```bash
pip install rnodeconf

# Connect T-Beam Supreme (915 MHz) via USB — note the port (e.g., /dev/ttyUSB0 or COM3)
rnodeconf --autoinstall /dev/ttyUSB0

# Disconnect. Connect T-Beam v1.1 (433 MHz).
rnodeconf --autoinstall /dev/ttyUSB1
```

When prompted, select the correct board variant:
- T-Beam Supreme → choose **T-Beam Supreme** (SX1262)
- T-Beam v1.1 → choose **LilyGO T-Beam v1.1** (SX1278)

Flash takes ~2 minutes per board. After flashing, **immediately attach the correct antenna before powering on** — running a LoRa radio without an antenna can damage the PA.

---

### 3. Assemble the power system

1. Insert the 18650 cell into the Waveshare Solar Power Manager battery holder. Observe polarity (marked on PCB).
2. Connect the solar panel barrel plug (5.5×2.1mm) to the Solar Power Manager's solar input jack.
3. Connect a micro-USB cable from the Solar Power Manager's **5V OUT** port to the Pi Zero 2W's **PWR IN** port (the right-side micro-USB on the Zero, labeled PWR IN).

> The Solar Power Manager outputs 5V/2A regulated — sufficient for the Pi Zero 2W (peak ~500mA) plus two USB T-Beams (~100mA each). Total draw under load is well under 800mA.

---

### 4. Connect T-Beams via OTG hub

1. Plug the OTG hub into the Pi Zero 2W's **USB OTG** port (left micro-USB, labeled USB).
2. Connect the 915 MHz T-Beam Supreme to hub port 1 via USB-C or Micro-USB cable.
3. Connect the 433 MHz T-Beam v1.1 to hub port 2 via USB or Micro-USB cable.
4. Attach antennas: 915 MHz whip to the Supreme's SMA connector, 433 MHz whip to the v1.1's SMA connector.

At this point the assembly should power up. The Pi Zero 2W green LED will blink, and both T-Beams will show their boot sequence on their OLED displays (if fitted).

---

### 5. Verify port assignments

SSH into the Pi Zero 2W, then:

```bash
ls /dev/ttyUSB*
# Expected output: /dev/ttyUSB0   /dev/ttyUSB1

# To confirm which board is on which port, unplug one T-Beam at a time and recheck ls
# Typical assignment: ttyUSB0 = first T-Beam plugged in (Supreme / 915 MHz)
#                     ttyUSB1 = second T-Beam (v1.1 / 433 MHz)
```

Note your actual port assignments — you will need them in the next step.

---

### 6. Run the relay setup script

```bash
git clone https://github.com/private-nemo/RTAK.git
cd RTAK/rtak_relay

# If your port assignments differ from defaults, edit setup_relay.sh first:
#   PORT_915="/dev/ttyUSB0"
#   PORT_433="/dev/ttyUSB1"

sudo bash setup_relay.sh
```

The script will:
- Install `rns` (Reticulum Network Stack)
- Write `/etc/reticulum/config` with both RNode interfaces and WiFi auto-discovery
- Enable `enable_transport = True` — this is what makes the node a relay
- Install and enable `rnsd` as a systemd service
- Configure UFW: SSH only (no FTS ports — this node runs no TAK stack)

---

### 7. Start and verify the relay

```bash
sudo systemctl start rnsd
sudo journalctl -u rnsd -f
```

You should see lines like:
```
[RNS] Started
[RNS] RNodeInterface[lora_915] configured on /dev/ttyUSB0
[RNS] RNodeInterface[lora_433] configured on /dev/ttyUSB1
[RNS] AutoInterface[local_auto] started
[RNS] Transport enabled — routing active
```

Check interface status:
```bash
rnstatus
```

This shows each active interface, link-layer connectivity status, and byte counters. Bytes flowing on both LoRa interfaces confirm the relay is operating.

To verify from an OmniNode that the relay is routing:
```bash
rnprobe <destination-hash>
# Route path will show the relay's hash as an intermediate hop
```

---

### 8. Mount in weatherproof enclosure

1. Drill cable entry holes for:
   - Solar panel cable (use PG9 cable gland, seal with rubber gasket)
   - Antenna cables for 915 MHz and 433 MHz — route SMA bulkhead connectors through gland holes and tighten
   - Optional: micro-USB maintenance access port (seal when deployed)
2. Mount the Pi Zero 2W assembly on M4 nylon standoffs inside the enclosure. Keep the standoffs tall enough to prevent the PCB from contacting the case bottom.
3. Secure the Solar Power Manager PCB alongside the Pi — use standoffs or foam double-sided tape.
4. Tuck T-Beam boards flat; secure with cable ties or foam wedges to prevent vibration damage.
5. Place 2–4 silica gel desiccant packs in the free space inside the enclosure to absorb moisture ingress.
6. Route the 18650 cell where it won't short against any metal.
7. Close and seal the enclosure. Check all cable glands are hand-tight.

---

### 9. Field deployment

- Mount at elevation for best RF line-of-sight (hilltop, rooftop, tree-mounted is ideal)
- Orient solar panel south (northern hemisphere) at 30–45° tilt
- Antennas should be vertical (omnidirectional coverage) or directed if terrain requires
- The relay requires no ongoing maintenance — once `rnsd` is running, it routes autonomously
- SSH is available via WiFi if the deployment area has a network; otherwise access is only possible by physically retrieving the unit

---

## RF Interoperability Notes

The Reticulum config in `reticulum.conf` sets:

```ini
frequency     = 915000000   # or 433000000
bandwidth     = 125000
txpower       = 17
spreadingfactor = 8
codingrate    = 5
```

**These values must match identically on every OmniNode for cross-node communication.** Mismatch in any parameter (especially frequency and spreading factor) results in complete deafness between nodes. Verify OmniNode `/etc/reticulum/config` matches before deploying a relay.

---

## Repository

<https://github.com/private-nemo/RTAK>
