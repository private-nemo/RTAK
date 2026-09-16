# RTAK Android Device Hardening

Security hardening guide for Android devices used as ATAK operator interfaces on the RTAK network. The OmniNode secures the transport; this guide secures the endpoint.

The quick-reference version of this guide is available at `http://<node-ip>:8888/checklist` from within ATAK's built-in browser.

---

## Why This Matters

Reticulum provides end-to-end encryption between nodes. FreeTAKServer has TLS mutual authentication. The weakest link is the Android device in the operator's hand. CoT data, chat messages, and GPS positions exist in plaintext inside ATAK's process memory and on the device's local storage. This guide addresses that attack surface.

---

## 1. OS Selection

**Best: GrapheneOS**

GrapheneOS is the security baseline for any sensitive RTAK deployment. It provides:

- No Google Play Services (eliminates the entire Google telemetry stack)
- Verified boot with hardware attestation
- Stronger app sandboxing and process isolation
- Per-app network permission (deny internet access to ATAK entirely, route only through OmniNode)
- USB port "charging only when locked" — blocks forensic USB tools even with physical access
- Per-network MAC randomization enabled by default, with additional rotation options
- IMEI randomization: Settings → About phone → IMEI → Randomize

Supported devices: Pixel 6 and later. Install via: <https://grapheneos.org/install>

**Acceptable: Stock Android (minimum Android 10)**

Stock Android is manageable with additional hardening steps. Google Play Services cannot be removed, so telemetry leakage is harder to fully eliminate. Use a dedicated device with no personal Google account.

**Not acceptable for sensitive ops:**
- Any device with Google account signed in and Google Backup enabled
- Any device with the ATAK APK installed from Google Play Store
- Shared/personal devices

---

## 2. Network Isolation

### 2a. Airplane Mode + WiFi Only

Enable airplane mode to kill cellular. Then re-enable WiFi to connect to the OmniNode.

- Cellular path completely severed — no baseband registration, no carrier metadata
- If your device keeps WiFi Calling active in airplane mode: Settings → Network → SIMs → WiFi calling: **off** before enabling airplane mode. Some Android builds (especially on carrier-unlocked devices) re-enable WiFi Calling when WiFi comes back on.

### 2b. Forget All Non-RTAK WiFi Networks

Android broadcasts probe requests containing the SSIDs of every network it has ever connected to. These probe requests reveal location history — even from a device with its MAC randomized, the SSID list identifies the user.

Settings → WiFi → Saved networks → delete everything except the OmniNode SSID before ops.

### 2c. Per-Network MAC Randomization

Prevents cross-location correlation via MAC address.

- Android 10+: Settings → WiFi → (OmniNode network) → Privacy → **Randomized MAC**
- GrapheneOS: enabled by default, with optional rotation

The OmniNode Pi randomizes its own MAC at each boot (installed by `setup_pi.sh`).

### 2d. DNS → OmniNode

Without this, Android resolves hostnames via cellular DNS (or the upstream WiFi router DNS) even when connected to the OmniNode.

Settings → WiFi → (OmniNode network) → Edit → Advanced options → IP settings: **Static** → DNS 1: `<node-ip>` → DNS 2: `<node-ip>`

The OmniNode's dnsmasq returns NXDOMAIN for all external queries, so no hostname resolves outside the local network.

### 2e. NTP → OmniNode

Android syncs time to `time.google.com`. Each sync packet identifies the device as active.

Settings → Developer Options → NTP server: `<node-ip>`

The OmniNode's chrony serves local time with a stratum 10 fallback when offline.

### 2f. Disable Bluetooth

Bluetooth broadcasts probe packets that can be logged by Bluetooth scanners. Unless an operation specifically requires Bluetooth, disable it.

---

## 3. Device Hardening

### 3a. USB Debugging (ADB)

If USB debugging is on, physical USB access = full shell access to the device.

Settings → Developer Options → USB debugging: **off**

GrapheneOS: Settings → Security → USB → **No data connections when locked** — this goes further, blocking USB data even to trusted computers when the screen is locked.

### 3b. Screen Lock

- **PIN or passphrase only** — biometrics can be compelled. In high-risk scenarios, use alphanumeric passphrase.
- Screen lock timeout: **30 seconds maximum**
- After failed attempts: Settings → Security → enable auto factory reset after 10 failed unlock attempts

### 3c. Full-Disk Encryption

Default on Android 10+, but verify: Settings → Security → Encryption & credentials → **Encrypted**. If not encrypted, this is a show-stopper — all data on the device is recoverable from a physical extraction.

### 3d. Camera Geotagging

Photos shared via ATAK GeoChat include EXIF metadata — GPS coordinates, device model, timestamp — embedded in the image file. These reveal your position to anyone who receives the image.

Camera app → Settings → **Location tags: off**

GrapheneOS: additionally deny location permission to the camera app entirely (Settings → Apps → Camera → Permissions → Location: **Deny**).

### 3e. IMEI

IMEI is the hardware identifier burned into the baseband. Every cellular tower that sees the device logs its IMEI.

**Mitigation (remove SIM):** With no SIM and in airplane mode, the device does not register with any tower. IMEI is irrelevant.

**GrapheneOS IMEI randomization:** Settings → About phone → IMEI → Randomize. Generates a random IMEI per session, preventing cross-session carrier correlation. This is the strongest available mitigation short of SIM removal.

**Stock Android:** IMEI is fixed and cannot be spoofed.

---

## 4. ATAK Application Settings

### 4a. Map Sources — Offline Only

Remove all online map sources. Any online source sends coordinate-encoded HTTP requests outside Reticulum.

ATAK → Map → Layers → remove Google, Bing, ArcGIS, etc. → set mbtiles offline layer as default base.

See `rtak_maps/` for instructions on generating and loading offline tile packs.

### 4b. Plugin Whitelist

ATAK plugins run with full app privileges. A malicious or poorly-written plugin can exfiltrate CoT data, contact external servers, or log position history.

Policy: **disable all plugins not on the team approved list** before operations.

See `allowed_plugins.md` for the current approved plugin list and the review criteria for adding a new plugin.

### 4c. TAK Server Connection — SSL Only

ATAK → Settings → Network → Manage Server Connections:
- Server: OmniNode IP
- Port: **8089** (SSL CoT)
- SSL: **on**
- Client certificate: import the `.p12` generated by `generate_user_cert.sh`

Never use port 8087. FreeTAKServer is configured to only accept external clients on SSL.

### 4d. SA Beacon Interval

ATAK broadcasts your position at a configurable interval (default: every few seconds). On a contained local network this is fine. If the device ever touches a non-RTAK network, those beacons go out.

ATAK → Settings → Network → Reporting Interval: set to the minimum necessary. Disable location reporting entirely when not actively on the RTAK network.

---

## 5. Google Play Store

Do not install ATAK from the Google Play Store on any device used for operations.

The Play Store creates a persistent, cloud-linked device identity. Google logs: app installs, device hardware ID, account, location at install time, and periodic phone-home traffic from Play Services. This data can be subpoenaed or queried independently of anything RTAK encrypts.

**Install ATAK from the CivTAK APK directly:** <https://www.civtak.org>

If a device previously had a Google account signed in: factory reset before use. Note that factory reset alone does not purge the device's hardware identity from Google's servers — it only removes local data. The device should be considered potentially linked if it was ever signed into a Google account.

---

## 6. Panic Protocol

When the network is compromised or there is risk of device capture:

1. **Trigger server wipe first:** Open `http://<node-ip>:8888/` in ATAK browser → PANIC button. This wipes FTS logs on all nodes simultaneously via Reticulum.

2. **Device checklist (immediately after):**
   - ATAK → Settings → My Profile → Advanced → **Clear Event Data**
   - GeoChat → overflow menu → **Delete All**
   - Map → Track History → **Delete All Tracks**
   - Manage Server Connections → **delete** OmniNode entry
   - If device may be captured: Settings → General management → Reset → **Factory data reset**

3. **Power off radios:** Airplane mode → all radios off.

The complete interactive checklist is available at `http://<node-ip>:8888/checklist`.

---

## 7. Operational Posture Summary

| Risk | Mitigation | Priority |
|---|---|---|
| Google telemetry | GrapheneOS, no Google account, CivTAK APK | Critical |
| Cellular IMSI/IMEI | SIM removal + airplane mode | Critical |
| Map tile leakage | Offline mbtiles, remove online sources | Critical |
| DNS leakage | Device DNS → OmniNode sinkhole | High |
| NTP fingerprinting | Device NTP → OmniNode chrony | High |
| MAC address tracking | Per-network randomization | High |
| WiFi probe requests | Forget all non-RTAK networks | High |
| USB forensic access | ADB off, USB charging-only-when-locked (GrapheneOS) | High |
| EXIF geotagging | Camera location tags off | Medium |
| Plugin exfiltration | Approved plugin whitelist | Medium |
| WiFi Calling in airplane mode | Manually disable before ops | Medium |
| FTS event log at rest | Regular wipe schedule, panic button | Medium |

---

## Repository

<https://github.com/private-nemo/RTAK>
