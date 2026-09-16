# RTAK Changelog

Bridge code revisions follow the `v1.0.x` scheme. Modules and subdirectories use descriptive tags (`<name>-v1`, etc.).

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
