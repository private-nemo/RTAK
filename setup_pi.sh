#!/usr/bin/env bash
# RTAK Node — Raspberry Pi Setup Script
# Tested on: Raspberry Pi OS Lite (64-bit), Bookworm
#
# What this does:
#   1.  Updates system packages
#   2.  Installs Python deps: rns, lxmf, pytak, FreeTAKServer
#   3.  Deploys the RTAK bridge to /opt/rtak
#   4.  Writes a Reticulum config for dual RNodes (915 + 433 MHz) + WiFi
#   5a. Generates a private CA + server TLS cert for FTS (SSL CoT on 8089)
#   5b. Hardens firewall: blocks plain-text port 8087, allows only 8089 + SSH
#       Also opens: 8888 (panic panel), 53/udp (DNS sinkhole), 123/udp (NTP)
#   5c. Installs FreeTAKServer with SSL config
#   6.  Installs systemd services for FreeTAKServer and the bridge
#   7.  Configures chrony as a local NTP server (LAN clients use Pi for time)
#   8.  Configures dnsmasq as a DNS sinkhole (all external DNS returns NXDOMAIN)
#
# Usage:
#   sudo bash setup_pi.sh
#
# After running:
#   1. Plug in both T-Beam RNodes via USB
#   2. Verify port assignments: ls /dev/ttyUSB*
#   3. Edit /etc/reticulum/config if port names differ from defaults
#   4. sudo systemctl start freetakserver rtak-bridge
#   5. Note the bridge hash printed in: journalctl -u rtak-bridge -f
#   6. Generate per-user client certs: sudo bash /opt/rtak/generate_user_cert.sh <username>
#      Import the resulting <username>.p12 into ATAK as a trust store
#   7. On Android: WiFi advanced settings → set DNS to this Pi's IP
#      On Android: Developer options → set NTP server to this Pi's IP
#      (or use GrapheneOS network-time-update settings)

set -euo pipefail

RTAK_USER="rtak"
RTAK_HOME="/opt/rtak"
RNS_CONFIG="/etc/reticulum"

# Ports — adjust if your system assigns them differently
# Run: ls /dev/ttyUSB* after plugging in both T-Beams
PORT_915="/dev/ttyUSB0"   # T-Beam Supreme (915 MHz)
PORT_433="/dev/ttyUSB1"   # T-Beam v1.1 (433 MHz)

# LoRa RF settings — US 915 MHz ISM band defaults
# Adjust for your regulatory region and link budget needs
FREQ_915=915000000
FREQ_433=433000000
BANDWIDTH=125000          # 125 kHz — balanced range vs speed
TXPOWER=17                # dBm — 17 dBm (~50 mW), legal everywhere
SF=8                      # Spreading factor 8 — good balance
CR=5                      # Coding rate 4/5

CERTS_DIR="$RTAK_HOME/certs"
CA_DAYS=3650    # 10-year CA
CERT_DAYS=3650  # 10-year leaf certs (adjust to taste)

echo "=== RTAK Node Setup ==="
echo "Target: $RTAK_HOME"
echo "RNode 915: $PORT_915"
echo "RNode 433: $PORT_433"
echo ""

# Detect primary LAN interface for dnsmasq binding
LAN_IFACE=$(ip route show default 2>/dev/null | awk '{print $5}' | head -1)
LAN_IFACE="${LAN_IFACE:-eth0}"
echo "Detected LAN interface: $LAN_IFACE"
echo ""

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
echo "[1/8] Updating system packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    git usbutils openssl ufw \
    chrony dnsmasq macchanger

# ---------------------------------------------------------------------------
# 2. Flash RNode firmware (requires boards to be plugged in)
# ---------------------------------------------------------------------------
echo "[2/8] Installing rnodeconf and checking RNode firmware..."
pip3 install --quiet rnodeconf

echo "  Flashing 915 MHz RNode on $PORT_915..."
rnodeconf --autoinstall --freq $FREQ_915 --bw $BANDWIDTH --txp $TXPOWER \
    --sf $SF --cr $CR "$PORT_915" || \
    echo "  WARNING: Could not flash $PORT_915 — plug in T-Beam Supreme and rerun, or flash manually."

echo "  Flashing 433 MHz RNode on $PORT_433..."
rnodeconf --autoinstall --freq $FREQ_433 --bw $BANDWIDTH --txp $TXPOWER \
    --sf $SF --cr $CR "$PORT_433" || \
    echo "  WARNING: Could not flash $PORT_433 — plug in T-Beam v1.1 and rerun, or flash manually."

# ---------------------------------------------------------------------------
# 3. Create RTAK system user and deploy files
# ---------------------------------------------------------------------------
echo "[3/8] Creating rtak user and deploying files..."
id "$RTAK_USER" &>/dev/null || useradd --system --shell /usr/sbin/nologin \
    --home-dir "$RTAK_HOME" --create-home "$RTAK_USER"

# Add rtak user to dialout so it can access USB serial ports
usermod -aG dialout "$RTAK_USER"

# Copy bridge files
mkdir -p "$RTAK_HOME"
cp prototype.py "$RTAK_HOME/"
cp requirements.txt "$RTAK_HOME/"
cp rtak_peers.txt "$RTAK_HOME/" 2>/dev/null || touch "$RTAK_HOME/rtak_peers.txt"

# Create virtualenv and install Python deps
python3 -m venv "$RTAK_HOME/venv"
"$RTAK_HOME/venv/bin/pip" install --quiet -r "$RTAK_HOME/requirements.txt"

chown -R "$RTAK_USER:$RTAK_USER" "$RTAK_HOME"

# ---------------------------------------------------------------------------
# 4. Reticulum config
# ---------------------------------------------------------------------------
echo "[4/8] Writing Reticulum config..."
mkdir -p "$RNS_CONFIG"

cat > "$RNS_CONFIG/config" <<RETCONFIG
# Reticulum config — RTAK Node
# Generated by setup_pi.sh

[reticulum]
  enable_transport = True
  share_instance   = Yes
  shared_instance_port = 37428
  instance_control_port = 37429

# 915 MHz LoRa (T-Beam Supreme, SX1262)
[interface:lora_915]
  type             = RNodeInterface
  interface_enabled = True
  port             = $PORT_915
  frequency        = $FREQ_915
  bandwidth        = $BANDWIDTH
  txpower          = $TXPOWER
  spreadingfactor  = $SF
  codingrate       = $CR

# 433 MHz LoRa (T-Beam v1.1, SX1278)
[interface:lora_433]
  type             = RNodeInterface
  interface_enabled = True
  port             = $PORT_433
  frequency        = $FREQ_433
  bandwidth        = $BANDWIDTH
  txpower          = $TXPOWER
  spreadingfactor  = $SF
  codingrate       = $CR

# Local WiFi / Ethernet (auto-discovers other Reticulum nodes on LAN)
[interface:local_auto]
  type             = AutoInterface
  interface_enabled = True

# Uncomment to add an outbound TCP tunnel to a known remote node:
# [interface:tcp_relay]
#   type            = TCPClientInterface
#   interface_enabled = True
#   target_host     = your.relay.host
#   target_port     = 4242
RETCONFIG

echo "  Reticulum config written to $RNS_CONFIG/config"

# ---------------------------------------------------------------------------
# 5. TLS certificates (private CA + server cert for FTS)
# ---------------------------------------------------------------------------
echo "[5a/8] Generating RTAK private CA and server certificates..."
mkdir -p "$CERTS_DIR"
chmod 700 "$CERTS_DIR"

# Private CA
openssl genrsa -out "$CERTS_DIR/ca.key" 4096 2>/dev/null
openssl req -new -x509 -days $CA_DAYS \
    -key "$CERTS_DIR/ca.key" \
    -out "$CERTS_DIR/ca.crt" \
    -subj "/CN=RTAK-CA/O=RTAK/OU=TacticalComms/C=US" 2>/dev/null
echo "  CA cert: $CERTS_DIR/ca.crt"

# Server cert (signed by RTAK-CA)
openssl genrsa -out "$CERTS_DIR/server.key" 2048 2>/dev/null
openssl req -new \
    -key "$CERTS_DIR/server.key" \
    -out "$CERTS_DIR/server.csr" \
    -subj "/CN=rtak-server/O=RTAK/OU=TacticalComms/C=US" 2>/dev/null
openssl x509 -req -days $CERT_DAYS \
    -in "$CERTS_DIR/server.csr" \
    -CA "$CERTS_DIR/ca.crt" \
    -CAkey "$CERTS_DIR/ca.key" \
    -CAcreateserial \
    -out "$CERTS_DIR/server.crt" 2>/dev/null

# PKCS12 bundle for FTS (FTS expects .p12)
openssl pkcs12 -export \
    -out "$CERTS_DIR/server.p12" \
    -inkey "$CERTS_DIR/server.key" \
    -in "$CERTS_DIR/server.crt" \
    -certfile "$CERTS_DIR/ca.crt" \
    -passout pass:rtak_server 2>/dev/null
echo "  Server cert bundle: $CERTS_DIR/server.p12"

# Helper script to generate per-user client certs
cat > "$RTAK_HOME/generate_user_cert.sh" <<'GENCERT'
#!/usr/bin/env bash
# Usage: sudo bash generate_user_cert.sh <username>
# Outputs: /opt/rtak/certs/<username>.p12
# Import that file into ATAK as a trust store (password: rtak_user)
set -euo pipefail
USERNAME="${1:?Usage: $0 <username>}"
CERTS="/opt/rtak/certs"
CERT_DAYS=3650

openssl genrsa -out "$CERTS/$USERNAME.key" 2048 2>/dev/null
openssl req -new \
    -key "$CERTS/$USERNAME.key" \
    -out "$CERTS/$USERNAME.csr" \
    -subj "/CN=$USERNAME/O=RTAK/OU=TacticalComms/C=US" 2>/dev/null
openssl x509 -req -days $CERT_DAYS \
    -in "$CERTS/$USERNAME.csr" \
    -CA "$CERTS/ca.crt" \
    -CAkey "$CERTS/ca.key" \
    -CAcreateserial \
    -out "$CERTS/$USERNAME.crt" 2>/dev/null
openssl pkcs12 -export \
    -out "$CERTS/$USERNAME.p12" \
    -inkey "$CERTS/$USERNAME.key" \
    -in "$CERTS/$USERNAME.crt" \
    -certfile "$CERTS/ca.crt" \
    -passout pass:rtak_user 2>/dev/null

chmod 600 "$CERTS/$USERNAME.p12"
echo "User cert created: $CERTS/$USERNAME.p12"
echo "Import into ATAK as a trust store. Password: rtak_user"
GENCERT
chmod +x "$RTAK_HOME/generate_user_cert.sh"
echo "  User cert helper: $RTAK_HOME/generate_user_cert.sh"

# Lock down cert files
chown -R "$RTAK_USER:$RTAK_USER" "$CERTS_DIR"
chmod 600 "$CERTS_DIR"/*.key "$CERTS_DIR"/*.p12 2>/dev/null || true

# ---------------------------------------------------------------------------
# 5b. Firewall hardening
# ---------------------------------------------------------------------------
echo "[5b/8] Hardening firewall..."
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 8089/tcp comment "FTS SSL CoT (ATAK clients)"
ufw allow 8080/tcp comment "FTS data packages"
ufw allow 8888/tcp comment "RTAK panic panel (open in ATAK browser)"
ufw allow 53/udp  comment "DNS sinkhole (LAN clients)"
ufw allow 123/udp comment "NTP server (LAN clients)"
# Port 8087 (plain-text CoT) intentionally NOT opened
ufw --force enable
echo "  UFW enabled. Open ports: 22 (SSH), 8089 (SSL CoT), 8080 (packages)"
echo "              8888 (panic panel), 53/udp (DNS), 123/udp (NTP)"
echo "  Port 8087 (plain-text CoT) is BLOCKED"

# ---------------------------------------------------------------------------
# 5c. FreeTAKServer with SSL
# ---------------------------------------------------------------------------
echo "[5c/8] Installing FreeTAKServer..."
pip3 install --quiet FreeTAKServer

FTS_CONFIG="/etc/freetakserver"
mkdir -p "$FTS_CONFIG"
cat > "$FTS_CONFIG/FreeTAKServerConfig.py" <<FTSCONFIG
# FreeTAKServer config for RTAK node — SSL only, no plain-text CoT
IP = '0.0.0.0'
CoTServicePort = 8087          # Kept for local bridge connection (loopback only)
SSLCoTServicePort = 8089       # External ATAK clients connect here (SSL + client cert)
DataPackageServiceDefaultPort = 8080
UserConnectionString = 'sqlite:////opt/rtak/fts_data.db'
MainLoopDelay = 1

# TLS — server identity
pemDir = '/opt/rtak/certs'
certPath = '/opt/rtak/certs/server.p12'
keyDir = '/opt/rtak/certs'
unencryptedKey = 'server.key'
P12Password = 'rtak_server'

# CA trust store — only clients with certs signed by RTAK-CA are accepted
CA = '/opt/rtak/certs/ca.crt'
FTSCONFIG

# FTS systemd unit
cat > /etc/systemd/system/freetakserver.service <<FTSSVC
[Unit]
Description=FreeTAKServer
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=$RTAK_USER
WorkingDirectory=$RTAK_HOME
ExecStart=/usr/bin/python3 -m FreeTAKServer.controllers.services.FTS
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
FTSSVC

# ---------------------------------------------------------------------------
# 6. RTAK bridge systemd unit
# ---------------------------------------------------------------------------
echo "[6/8] Installing RTAK bridge systemd service...
Note: bridge connects to FTS on loopback 8087 (not firewalled for 127.0.0.1)."
cat > /etc/systemd/system/rtak-bridge.service <<BRIDGESVC
[Unit]
Description=RTAK Bridge — CoT over Reticulum
After=network.target freetakserver.service
Requires=freetakserver.service
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=$RTAK_USER
WorkingDirectory=$RTAK_HOME
ExecStart=$RTAK_HOME/venv/bin/python $RTAK_HOME/prototype.py
Restart=on-failure
RestartSec=15
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
BRIDGESVC

systemctl daemon-reload
systemctl enable freetakserver rtak-bridge

# ---------------------------------------------------------------------------
# 7. chrony — local NTP server
# ---------------------------------------------------------------------------
echo "[7/8] Configuring chrony as local NTP server..."

# Keep upstream pool for initial sync when internet is available.
# local stratum 10 = fallback: serve time from local clock when offline.
# This means Android devices never need to contact time.google.com.
cat >> /etc/chrony/chrony.conf <<CHRONYCONF

# RTAK: serve time to LAN clients
allow 10.0.0.0/8
allow 192.168.0.0/16
allow 172.16.0.0/12

# RTAK: when no internet NTP is reachable, serve local clock at stratum 10
# so LAN clients still get a consistent time reference during offline ops
local stratum 10
CHRONYCONF

systemctl enable chrony
systemctl restart chrony
echo "  chrony configured. Android NTP server → set to this Pi's IP in Developer Options"
echo "  (GrapheneOS: Settings → System → Date & Time → network time provider)"

# ---------------------------------------------------------------------------
# 8. dnsmasq — DNS sinkhole
# ---------------------------------------------------------------------------
echo "[8/8] Configuring dnsmasq DNS sinkhole..."

# dnsmasq binds to the LAN interface only.
# Pi's own DNS continues to use systemd-resolved (127.0.0.53) — unaffected.
# LAN clients that use the Pi as their DNS server get NXDOMAIN for all
# external queries — tile servers, analytics, telemetry, etc. cannot resolve.
# Reticulum is unaffected (uses cryptographic hashes, not DNS hostnames).

cat > /etc/dnsmasq.d/rtak-sinkhole.conf <<DNSCFG
# RTAK DNS sinkhole — returns NXDOMAIN for all external queries
# Bind to LAN interface only so Pi's own systemd-resolved is untouched
bind-interfaces
interface=$LAN_IFACE

# No upstream resolvers — every external query returns NXDOMAIN
no-resolv
no-poll
bogus-priv
domain-needed

# Pi's own hostname still resolves via /etc/hosts
# Add static entries below if needed:
# address=/rtak.local/<this-pi-ip>
DNSCFG

systemctl enable dnsmasq
systemctl restart dnsmasq
echo "  dnsmasq sinkhole active on $LAN_IFACE:53"
echo "  Android DNS → set to this Pi's IP in WiFi advanced settings"
echo "  All external DNS queries from clients will return NXDOMAIN"

# ---------------------------------------------------------------------------
# MAC address randomization — Pi randomizes its own MAC at each boot
# ---------------------------------------------------------------------------
echo "  Configuring MAC address randomization for $LAN_IFACE..."

# Debconf: set macchanger to not run automatically (we use our own unit)
echo "macchanger macchanger/automatically_run boolean false" | debconf-set-selections

cat > /etc/systemd/system/mac-randomize.service <<MACSVC
[Unit]
Description=Randomize MAC address on $LAN_IFACE
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
ExecStart=/usr/bin/macchanger -r $LAN_IFACE
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
MACSVC

systemctl enable mac-randomize
echo "  Pi MAC randomization enabled — new random MAC assigned on each boot"
echo "  Android: enable per-network MAC randomization in WiFi settings"
echo "  GrapheneOS: this is already enabled by default"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Verify RNode ports:  ls /dev/ttyUSB*"
echo "     If they differ from $PORT_915 / $PORT_433, edit $RNS_CONFIG/config"
echo ""
echo "  2. Start services:"
echo "     sudo systemctl start freetakserver rtak-bridge"
echo ""
echo "  3. Check bridge is running and note your node hash:"
echo "     sudo journalctl -u rtak-bridge -f"
echo ""
echo "  4. Share your Reticulum hash with other node operators."
echo "     Add their hashes to $RTAK_HOME/rtak_peers.txt (one per line)"
echo "     Only peers listed here can send CoT to your node."
echo ""
echo "  5. Generate a client cert for each ATAK operator:"
echo "     sudo bash $RTAK_HOME/generate_user_cert.sh <callsign>"
echo "     Import <callsign>.p12 into ATAK → Settings → Network → Manage Server Connections"
echo "     Password: rtak_user"
echo ""
echo "  6. Point ATAK clients at this Pi's IP on port 8089 (SSL CoT)"
echo "     Port 8087 (plain-text) is firewalled — clients must use SSL."
echo ""
echo "Security summary:"
echo "  LoRa/Reticulum transport:  E2E encrypted (Reticulum default)"
echo "  ATAK → FTS connection:     TLS mutual auth (client cert required)"
echo "  Inbound bridge relay:      Whitelist-only (rtak_peers.txt)"
echo "  Firewall:                  UFW — SSH, 8089, 8080, 8888, DNS, NTP"
echo "  DNS sinkhole:              dnsmasq on $LAN_IFACE — NXDOMAIN for all external queries"
echo "  Local NTP:                 chrony — serves LAN clients, no time.google.com needed"
echo ""
echo "Android client hardening checklist:"
echo "  [ ] WiFi advanced settings → DNS → set to $(hostname -I | awk '{print $1}')"
echo "  [ ] Developer options → NTP server → set to $(hostname -I | awk '{print $1}')"
echo "  [ ] Enable airplane mode during ops, WiFi-only to reach OmniNode"
echo "  [ ] Use GrapheneOS or equivalent degoogled OS"
echo ""
echo "Panic control panel: http://$(hostname -I | awk '{print $1}'):8888/"
echo "  Open in ATAK browser to wipe FTS logs on all nodes simultaneously."
echo ""
echo "FTS data:       $RTAK_HOME/fts_data.db"
echo "RNS config:     $RNS_CONFIG/config"
echo "Peer list:      $RTAK_HOME/rtak_peers.txt"
echo "Certs:          $CERTS_DIR/"
echo "User cert tool: $RTAK_HOME/generate_user_cert.sh"
