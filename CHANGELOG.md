# RTAK Changelog

Bridge code revisions follow the `v1.0.x` scheme. Modules and subdirectories use descriptive tags (`<name>-v1`, etc.).

---

## rtak-satmap-v1
**Added:** `rtak_satmap/`

Automated weather satellite reception and live imagery overlay for ATAK. No ATAK plugin code required — ATAK's built-in custom map source system points to a tile server running on the OmniNode.

**How it works:** SatDump records NOAA APT and Meteor-M2 LRPT passes (~137 MHz) using an RTL-SDR dongle, produces georeferenced GeoTIFF output, GDAL converts to XYZ map tiles, a lightweight Python HTTP server serves tiles at port 8889. ATAK fetches from `http://<node-ip>:8889/latest/{z}/{x}/{y}.png` — "latest" always resolves to the most recently decoded pass, updating automatically every ~90 minutes.

**Pipeline features:** TLE auto-download and refresh, `pyorbital` pass prediction 12 hours ahead, minimum elevation filter (default 15°), recording via SatDump CLI with pass duration + margin timeout, GDAL warp to EPSG:3857 + tile generation, symlink rotation so ATAK URL never changes between passes, JSON pass log and status endpoint.

- `satmap_pipeline.py` — full pipeline daemon: TLE download, pass scheduling, SatDump orchestration, GDAL tile generation, HTTP tile server, pass log
- `setup_satmap.sh` — installs SatDump (pre-built ARM64 .deb or source build fallback), GDAL, pyorbital, deploys pipeline, installs `rtak-satmap.service`, opens UFW 8889/tcp
- `atak_satmap_source.xml` — ATAK custom map source template (edit `<node-ip>`, copy to `/sdcard/atak/imagery/`)
- `README.md` — full workflow: hardware BOM (RTL-SDR V4 + 137 MHz turnstile antenna + optional LNA), satellite reference table (NOAA 15/18/19, Meteor-M2-3/4), ATAK layer setup, pass quality guide, OPSEC note (passive reception only — no RF emission, no license required)

**Additional hardware:** RTL-SDR V4 (~$35) + 137 MHz turnstile or QFH antenna (~$30–50) + SMA extension cable (~$8). Connects to existing USB hub on OmniNode. No additional HAT or GPIO wiring.

---

## rtak-inlet-v1
**Added:** `rtak_inlet/`

Reticulum-over-internet module. Bridges RTAK LoRa meshes across the internet without exposing CoT content or protocol identity.

Two modes: **Basic** (Reticulum TCP on port 4242 — already binary-encrypted, no CoT signature visible) and **Stealth** (stunnel TLS wrapper on port 443 — traffic is indistinguishable from HTTPS to any DPI, firewall, or middlebox). Double encryption in stealth mode: TLS outer layer + Reticulum Curve25519+AES inner layer; keys are independent.

- `setup_inlet.sh` — appends `TCPServerInterface` to Reticulum config, optionally installs and configures `stunnel4` for stealth mode, opens UFW port, restarts Reticulum, prints the remote-node config block with detected public IP
- `README.md` — explains the encryption layering, both modes, network requirements, router port-forward notes, DDNS setup for dynamic IPs, I2P option for full endpoint anonymization, and an illustrated multi-hop topology diagram
- `reticulum-inlet.conf` — reference config snippets for both OmniNode server and remote client sides, plus I2P interface stub

What the inlet does **not** hide: endpoint IP addresses are still visible to ISPs and network observers. Content and protocol identity are hidden; source/destination IP is not. For full anonymization, the I2P option documented in the README routes both through I2P.

---

## v1.0.6
**Changed:** `prototype.py`

Panic control panel enhanced with device-side operator checklist.

- **Two-tab UI** — control panel at port 8888 now has "Server Panic" and "Device Checklist" tabs
- **GET `/checklist`** — standalone full hardening checklist page (linkable, bookmarkable from ATAK browser); covers pre-op network isolation, device hardening, ATAK settings, and panic protocol steps
- **Auto-switch on panic** — triggering server wipe automatically switches to the Device Checklist tab so operators immediately see the manual steps required on their Android device
- Device checklist covers: clear ATAK event data, delete GeoChat history, delete track log, remove server connection profile, disable WiFi Calling, factory reset procedure

**Changed (no tag):** `setup_pi.sh`

- Added `macchanger` to system packages
- New `mac-randomize.service` systemd unit: randomizes Pi's MAC address on `$LAN_IFACE` at every boot, before network comes up
- `debconf-set-selections` prevents macchanger from running a conflicting automatic mode

**Added (no tag):** `rtak_hardening/`

Comprehensive Android device hardening guide and plugin whitelist. Covers all 12 items identified in the RTAK security audit:

- `README.md` — full hardening guide: OS selection (GrapheneOS vs stock), network isolation (airplane mode, WiFi-only, MAC randomization, DNS/NTP via OmniNode, BT off, forget non-RTAK networks), device hardening (ADB off, USB data lock, encryption verify, screen lock, EXIF geotagging, IMEI randomization), ATAK settings (offline maps, plugin whitelist, SSL only), Google Play Store leak analysis, panic protocol with device-side steps, operational posture summary table
- `allowed_plugins.md` — plugin whitelist framework: approval criteria, review procedure (apktool decompile + grep + tcpdump), disqualifying findings (analytics SDKs, unexpected outbound, unknown source), empty approved list (add plugins as they pass review)

---

## v1.0.5
**Changed:** `prototype.py`

Panic wipe system and HTTP control panel.

- **Panic wipe command** — sending an LXMF message titled `"panic"` from a trusted peer triggers immediate deletion of all records from the FTS SQLite database (`/opt/rtak/fts_data.db`) on the receiving node. The wipe command does not re-propagate from the receiving node to prevent loop storms; a single initiating node propagates to all peers.
- **HTTP control panel** — a minimal HTTP server starts on port 8888 (LAN-accessible from any browser, including ATAK's built-in browser). Bookmarking `http://<node-ip>:8888/` gives any operator a one-tap panic button without leaving ATAK. Endpoint: `POST /panic` triggers local wipe plus Reticulum propagation to all peers.
- **`_wipe_fts_logs()`** — enumerates all SQLite tables in the FTS database and runs `DELETE FROM <table>` on each, wiping all stored CoT events, chat messages, and user connection history.
- **`_propagate_panic()`** — iterates `rtak_peers.txt` and sends a signed LXMF `"panic"` message to each trusted peer.
- **`--panic-port`** CLI argument — override the HTTP control panel port (default 8888).

**Changed (no tag):** `setup_pi.sh`

Added two new provisioning steps (now 8 total):

- **Step 7 — chrony local NTP** — configures the OmniNode as a LAN NTP server. `local stratum 10` fallback ensures LAN clients maintain consistent time even when no internet NTP is reachable. Android clients should point to the Pi's IP as their NTP server (Developer Options, or GrapheneOS network time settings) to eliminate `time.google.com` contact.
- **Step 8 — dnsmasq DNS sinkhole** — binds to the LAN-facing interface; all external DNS queries from LAN clients return NXDOMAIN. The Pi's own DNS continues through systemd-resolved. Reticulum is unaffected (uses cryptographic hashes, not hostnames). Android clients point to the Pi's IP as their DNS server via WiFi advanced settings.
- UFW: added rules for port 8888/tcp (panic panel), 53/udp (DNS sinkhole), 123/udp (NTP).

**Changed (no tag):** `README.md`

Added **Google Play Store as a Leak Vector** section to the Android Client Security technical note. Documents that Play Store installations create a cloud-linked device identity; recommends CivTAK APK direct install, dedicated hardware, and GrapheneOS sandboxed Play Store profile as mitigations.

---

## rtak-maps-v1
**Added:** `rtak_maps/`

Offline map tile workflow and ATAK data package generator. Covers how to generate `.mbtiles` files from Sentinel-2, USGS, MOBAC, and SAS Planet; how to load them into ATAK as a local offline layer; and how to distribute a pre-configured layer to all operators via a single importable data package. Eliminates the operational security leak from ATAK fetching online tile imagery during operations.

---

## security-notes-v1
**Added:** Satellite map tile security section to `README.md` and `rtak_relay/README.md`

Documented that ATAK's online tile requests bypass Reticulum encryption entirely — tile providers observe operational area coordinates over cellular/WiFi regardless of CoT encryption. Three mitigations ranked by effectiveness: offline tile packs, local tile server on OmniNode, network isolation.

---

## rtak-relay-v1
**Added:** `rtak_relay/`

Passive dual-band Reticulum relay node based on Raspberry Pi Zero 2W. Full BOM (~$153 dual-band), step-by-step weatherproof assembly instructions, `setup_relay.sh` provisioning script, and `reticulum.conf` reference. Relay requires no TAK stack, no certs, no whitelisting — only `enable_transport = True` in Reticulum config. Solar-powered for indefinite field deployment.

---

## v1.0.4
**Changed:** `prototype.py`, `README.md`

Added Android client security technical note to README. Documented that RTAK secures CoT in transit but cannot protect data in process memory on the Android device — Android kernel, Google Play Services, and baseband firmware all have access paths. Mitigations: GrapheneOS, dedicated hardware with MDM, data compartmentalization.

---

## v1.0.3
**Changed:** `README.md`, `assets/`

Added full hardware photo gallery (6 component images: Pi 4B, T-Beam Supreme, T-Beam v1.1, Argon NEO, Waveshare UPS HAT D, Digirig Mobile). Corrected Waveshare UPS HAT from (C) to (D) — the C model is Pi Zero-only; the D model is correct for Pi 4B with 2× 21700 cells.

---

## v1.0.2
**Changed:** `README.md`, `assets/`

Added initial hardware images to README. Sourced from vendor CDNs with referrer headers where required.

---

## v1.0.1
**Added:** `README.md`

Initial OmniNode README with full Bill of Materials (compute, dual LoRa RNodes, power, optional AX.25), 9-step assembly instructions, security model table, and per-node cost summary.

---

## v1.0.0
**Added:** `prototype.py`, `setup_pi.sh`, `requirements.txt`, `rtak_peers.txt`

Core RTAK bridge daemon (`RTAKBridge` class) bridging FreeTAKServer CoT over LXMF/Reticulum. Full Pi provisioning script with TLS mutual auth (private CA, PKCS12 client certs), UFW hardening (blocks plain-text CoT port 8087, opens SSL 8089), dual RNode Reticulum config, and systemd units for `freetakserver` and `rtak-bridge`.
