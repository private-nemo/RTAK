# RTAK Voice — Encrypted PTT over LoRa

Encrypted group voice is available on every RTAK OmniNode via the **LXST** protocol
(Lightweight Extensible Signal Transport), written by the same author as Reticulum.
No additional radio hardware is required — voice traffic rides the existing Reticulum
transport over the same LoRa RNode used for TAK.

---

## How it works

```
Android (Sideband)          OmniNode Pi
  LXST voice call ──WiFi──→ Reticulum daemon
                                  ↕ (LXST over LXMF/RNS)
                             partyline-server
                             (group PTT rooms)
                                  ↕
                             Reticulum daemon
                                  ↕ (LoRa ← RNode)
                         Other OmniNodes in range
```

Operators use **Sideband** (Android) or **MeshChatX** for voice. They join a room
by calling the Partyline server's Reticulum hash — same as any other LXST client.
The OmniNode relays voice packets over LoRa using Codec2 at 700 bps, which fits
comfortably within LoRa's bandwidth.

---

## LoRa voice constraints

| Property | Value | Notes |
|---|---|---|
| Codec | Codec2 | 700–3200 bps; 700 bps mode for LoRa |
| LoRa effective throughput | ~3–5 kbps | SF8/BW125 typical RTAK config |
| Codec2-700 overhead on wire | ~1000–1200 bps | Audio + Reticulum framing |
| Mode | **Half-duplex (PTT)** | LoRa is physically half-duplex — one speaker at a time |
| Real-time calls | Marginal | Latency ~300–500ms per hop; works for PTT net discipline |
| Voice messages | Reliable | Store-and-forward via Sideband; always works over LoRa |

**LoRa is PTT radio.** Full-duplex voice calls are not possible. Group PTT via
Partyline is the correct use case — it matches how operators already think about
LoRa net discipline.

---

## Components

### Partyline (runs on the OmniNode Pi)

[github.com/RFnexus/partyline](https://github.com/RFnexus/partyline)

Mumble-style encrypted group voice server for Reticulum. Runs as a systemd service
alongside FreeTAKServer. Clients discover it by Reticulum hash — no IP address needed.
Supports per-room access control: open, identified-only, or allowlisted identities.

**Installed by `setup_pi.sh` when `INSTALL_PARTYLINE=yes` (default).**

Room config: `/opt/rtak/partyline/server.json`

Server hash is printed on first start:

```bash
sudo journalctl -u rtak-partyline -f
```

Share this hash with operators — they paste it into Sideband or MeshChatX as a contact.

### Sideband (Android / Linux client)

[github.com/markqvist/Sideband](https://github.com/markqvist/Sideband)
APK: [latest release](https://github.com/markqvist/Sideband/releases/latest)

The primary Android client. Supports:
- **PTT voice messages** — Codec2 encoded, store-and-forward. Works reliably over slow LoRa.
- **LXST real-time voice calls** — call the Partyline server hash to join a room,
  or call another operator directly P2P.
- **Situational awareness** — location sharing, maps. Complements ATAK.

Operators can run Sideband alongside ATAK simultaneously on the same Android device.
Sideband connects to the OmniNode via WiFi; voice and CoT share the same LoRa transport.

### MeshChatX (alternative Android / desktop client)

[meshchatx.com](https://meshchatx.com)

All-in-one Reticulum client. Supports LXST voice calls, Partyline dial-in, NomadNet
browser, and messaging. Android + desktop. Use as an alternative to Sideband if
preferred.

### lxst_phone (desktop P2P calls)

[github.com/kc1awv/lxst_phone](https://github.com/kc1awv/lxst_phone)

Desktop-only P2P voice using LXST (Linux/macOS/Windows). Opus or Codec2. Use for
operator-to-operator calls from a laptop connected to the OmniNode over WiFi.
No group rooms — direct calls only.

---

## Partyline server management

### Check status

```bash
sudo systemctl status rtak-partyline
sudo journalctl -u rtak-partyline -f
```

### Get server hash (share with operators)

```bash
sudo journalctl -u rtak-partyline | grep "destination hash"
```

### Edit rooms / access control

```bash
sudo nano /opt/rtak/partyline/server.json
sudo systemctl restart rtak-partyline
```

### Add operator to Admin room allowlist

Edit `server.json`, add their Reticulum identity hash to the Admin room's `allow` array:

```json
"allow": [
  "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
]
```

Operator identity hashes are visible in Sideband (Settings → Identity) or printed
when any Reticulum application announces.

---

## Rooms (default config)

| Room | Codec | Access | Notes |
|---|---|---|---|
| Ops | Codec2-700 | identified | Primary ops net; any Reticulum identity |
| Admin | Codec2-1200 | allowlist | Node operators only; add hashes to server.json |
| Open | Codec2-700 | open | No identity required |

Edit `/opt/rtak/partyline/server.json` to add, remove, or reconfigure rooms.

---

## Operator setup (Android)

1. Install **Sideband** APK from [github.com/markqvist/Sideband/releases/latest](https://github.com/markqvist/Sideband/releases/latest)
2. Connect Android to the OmniNode's WiFi
3. In Sideband → Contacts → Add contact → paste the Partyline server hash
4. Tap the contact → Call → select "Voice call" → lands in default room (Ops)
5. Use push-to-talk. Codec2-700 over LoRa sounds like HF radio — intelligible, not hi-fi.

---

## Firewall note

Partyline uses Reticulum for transport — no additional UFW rules are needed. Voice
packets travel over the existing Reticulum instance (shared port 37428) alongside
CoT traffic. No new ports are exposed to the network.

---

## Disabling voice

To remove Partyline from the OmniNode:

```bash
sudo systemctl stop rtak-partyline
sudo systemctl disable rtak-partyline
```

Or prevent installation entirely during setup:

```bash
INSTALL_PARTYLINE=no sudo bash setup_pi.sh
```
