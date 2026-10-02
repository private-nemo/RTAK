#!/usr/bin/env python3
"""
RTAK Setup Wizard
Browser-based configuration wizard for RTAK OmniNode and mesh_babelfish.

Usage:
    python3 wizard.py          # opens browser automatically
    python3 wizard.py --port 8080 --no-browser
"""

import argparse
import json
import os
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Config generators
# ---------------------------------------------------------------------------

def gen_rtak_config(d):
    hw        = d.get("hardware", "pi4b")
    port_915  = d.get("port_915", "/dev/ttyUSB0")
    port_433  = d.get("port_433", "/dev/ttyUSB1")
    dual_band = d.get("dual_band", False)
    freq_915  = int(d.get("freq_915", 915000000))
    freq_433  = int(d.get("freq_433", 433000000))
    bw        = int(d.get("bandwidth", 125000))
    txp       = int(d.get("txpower", 17))
    sf        = int(d.get("sf", 8))
    cr        = int(d.get("cr", 5))
    voice     = d.get("partyline", False)
    operators = [o.strip() for o in d.get("operators", "").split(",") if o.strip()]
    node_name = d.get("node_name", "RTAK-Node")

    server_pass = secrets.token_hex(20)
    user_pass   = secrets.token_hex(20)

    setup_cmd = (
        f"RTAK_SERVER_PASS='{server_pass}' "
        f"RTAK_USER_PASS='{user_pass}' "
        + ("INSTALL_PARTYLINE=yes " if voice else "INSTALL_PARTYLINE=no ")
        + "sudo -E bash setup_pi.sh"
    )

    rns_cfg = f"""[reticulum]
  enable_transport = True
  share_instance   = Yes
  shared_instance_port = 37428
  instance_control_port = 37429

[interface:lora_915]
  type             = RNodeInterface
  interface_enabled = True
  port             = {port_915}
  frequency        = {freq_915}
  bandwidth        = {bw}
  txpower          = {txp}
  spreadingfactor  = {sf}
  codingrate       = {cr}
"""
    if dual_band:
        rns_cfg += f"""
[interface:lora_433]
  type             = RNodeInterface
  interface_enabled = True
  port             = {port_433}
  frequency        = {freq_433}
  bandwidth        = {bw}
  txpower          = {txp}
  spreadingfactor  = {sf}
  codingrate       = {cr}
"""
    else:
        rns_cfg += """
# Dual-band not enabled — add a second RNode and uncomment to enable:
# [interface:lora_433]
#   type             = RNodeInterface
#   interface_enabled = False
#   port             = /dev/ttyUSB1
"""

    rns_cfg += """
[interface:local_auto]
  type             = AutoInterface
  interface_enabled = True
"""

    partyline_cfg = None
    if voice:
        partyline_cfg = json.dumps({
            "name": node_name + " Voice",
            "description": "RTAK OmniNode encrypted PTT",
            "rooms": [
                {"name": "Ops",   "codec": "c2-700",  "access": "identified"},
                {"name": "Admin", "codec": "c2-1200", "access": "allowlist", "allow": []},
                {"name": "Open",  "codec": "c2-700",  "access": "open"},
            ],
            "dial_in": {"enabled": True, "default_room": "Ops"}
        }, indent=2)

    hw_labels = {
        "pi4b":    "Raspberry Pi 4B",
        "pi3aplus":"Raspberry Pi 3A+",
        "opizero2w":"Orange Pi Zero 2W",
        "heltec_v4":"Heltec V4 variant",
    }

    sections = []

    sections.append(("Hardware", hw_labels.get(hw, hw)))
    sections.append(("Node name", node_name))
    sections.append(("Setup command", setup_cmd))
    sections.append(("Reticulum config  (/etc/reticulum/config)", rns_cfg))
    if partyline_cfg:
        sections.append(("Partyline server config  (/opt/rtak/partyline/server.json)", partyline_cfg))
    if operators:
        cert_cmds = "\n".join(
            f"sudo bash /opt/rtak/generate_user_cert.sh {op}" for op in operators
        )
        sections.append(("Generate operator certs (run after setup)", cert_cmds))

    start_cmds = "sudo systemctl start freetakserver rtak-bridge"
    if voice:
        start_cmds += "\nsudo systemctl start rtak-partyline"
    start_cmds += "\nsudo journalctl -u rtak-bridge -f   # note your node hash"
    sections.append(("Start services", start_cmds))

    sections.append(("Passwords (save securely)", (
        f"SERVER_P12_PASS = {server_pass}\n"
        f"USER_P12_PASS   = {user_pass}\n\n"
        "These are also written to /opt/rtak/certs/passwords.txt (chmod 600) by the setup script.\n"
        "The setup command above passes them as environment variables."
    )))

    return sections


def gen_babelfish_config(d):
    node_name   = d.get("node_name", "BabelFish-1")
    en_rns      = d.get("enable_reticulum", True)
    en_mtk      = d.get("enable_meshtastic", True)
    en_mc       = d.get("enable_meshcore", True)
    en_433      = d.get("enable_433", False)
    port_rns    = d.get("port_reticulum", "/dev/ttyUSB0")
    port_mtk    = d.get("port_meshtastic", "/dev/ttyUSB1")
    port_mc     = d.get("port_meshcore", "/dev/ttyUSB2")
    port_433    = d.get("port_433", "/dev/ttyUSB3")
    proto_433   = d.get("proto_433", "reticulum")
    freq_915    = int(d.get("freq_915", 915000000))
    freq_433    = int(d.get("freq_433", 433000000))
    ttl         = int(d.get("session_ttl", 300))
    status_port = int(d.get("status_port", 8080))

    cfg = {
        "node_name": node_name,
        "radios": {
            "reticulum": {
                "port": port_rns,
                "frequency": freq_915,
                "enabled": en_rns,
                "announce_presence": True,
            },
            "meshtastic": {
                "port": port_mtk,
                "frequency": freq_915,
                "enabled": en_mtk,
                "announce_presence": False,
            },
            "meshcore": {
                "port": port_mc,
                "frequency": freq_915,
                "enabled": en_mc,
                "announce_presence": False,
            },
            "optional_433": {
                "port": port_433,
                "frequency": freq_433,
                "protocol": proto_433,
                "enabled": en_433,
            },
        },
        "sessions": {
            "ttl_seconds": ttl,
            "reply_routing": True,
        },
        "status_server": {
            "enabled": True,
            "port": status_port,
            "bind": "0.0.0.0",
        },
    }

    cfg_yaml = _dict_to_yaml(cfg)

    setup_cmd = (
        "git clone https://github.com/private-nemo/mesh_babelfish\n"
        "cd mesh_babelfish\n"
        "sudo bash setup.sh\n"
        f"sudo nano /opt/babelfish/config.yaml   # paste the config below\n"
        "sudo systemctl start babelfish\n"
        "sudo journalctl -u babelfish -f"
    )

    return [
        ("Node name", node_name),
        ("Setup commands", setup_cmd),
        ("config.yaml  (/opt/babelfish/config.yaml)", cfg_yaml),
        ("Status panel", f"http://<sbc-ip>:{status_port}/"),
    ]


def _dict_to_yaml(d, indent=0):
    lines = []
    pad = "  " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{pad}{k}:")
            lines.append(_dict_to_yaml(v, indent + 1))
        elif isinstance(v, bool):
            lines.append(f"{pad}{k}: {'true' if v else 'false'}")
        elif isinstance(v, str):
            lines.append(f"{pad}{k}: {json.dumps(v)}")
        else:
            lines.append(f"{pad}{k}: {v}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RTAK Setup Wizard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#c9d1d9;font-family:'Courier New',monospace;min-height:100vh;display:flex;justify-content:center;align-items:flex-start;padding:2rem 1rem}
.container{width:100%;max-width:760px}
h1{color:#58a6ff;font-size:1.4rem;margin-bottom:.3rem}
.tagline{color:#8b949e;font-size:.85rem;margin-bottom:2rem}
.progress{display:flex;gap:.5rem;margin-bottom:2rem;flex-wrap:wrap}
.pip{width:28px;height:4px;background:#21262d;border-radius:2px;transition:background .3s}
.pip.done{background:#238636}
.pip.active{background:#58a6ff}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1.5rem;margin-bottom:1.5rem}
h2{color:#f0f6fc;font-size:1rem;margin-bottom:1.2rem;text-transform:uppercase;letter-spacing:.08em}
.field{margin-bottom:1rem}
label{display:block;font-size:.82rem;color:#8b949e;margin-bottom:.3rem}
input[type=text],input[type=number],select{width:100%;background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:.5rem .7rem;border-radius:4px;font-family:inherit;font-size:.9rem;outline:none}
input:focus,select:focus{border-color:#58a6ff}
.row{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem}
.toggle-row{display:flex;align-items:center;gap:.8rem;margin-bottom:.8rem}
.toggle-row label{margin:0;color:#c9d1d9;font-size:.9rem;cursor:pointer}
input[type=checkbox]{accent-color:#58a6ff;width:16px;height:16px;cursor:pointer}
.mode-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:.5rem}
.mode-btn{background:#161b22;border:2px solid #30363d;border-radius:8px;padding:1.2rem;cursor:pointer;text-align:center;transition:border-color .2s,background .2s;color:#c9d1d9}
.mode-btn:hover{border-color:#58a6ff;background:#1c2230}
.mode-btn.selected{border-color:#58a6ff;background:#1c2230}
.mode-btn .icon{font-size:2rem;display:block;margin-bottom:.5rem}
.mode-btn .name{font-weight:bold;font-size:.95rem;color:#f0f6fc}
.mode-btn .desc{font-size:.78rem;color:#8b949e;margin-top:.3rem}
.hw-grid{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
.hw-btn{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:.9rem;cursor:pointer;text-align:left;transition:border-color .2s;color:#c9d1d9}
.hw-btn:hover{border-color:#58a6ff}
.hw-btn.selected{border-color:#58a6ff;background:#1c2230}
.hw-btn .hw-name{font-weight:bold;font-size:.9rem;color:#f0f6fc}
.hw-btn .hw-detail{font-size:.77rem;color:#8b949e;margin-top:.3rem}
.nav{display:flex;gap:1rem;margin-top:1rem}
.btn{padding:.6rem 1.4rem;border-radius:4px;border:none;font-family:inherit;font-size:.9rem;cursor:pointer;transition:background .2s}
.btn-primary{background:#238636;color:#fff}
.btn-primary:hover{background:#2ea043}
.btn-secondary{background:#21262d;color:#c9d1d9;border:1px solid #30363d}
.btn-secondary:hover{background:#30363d}
.btn-danger{background:#b91c1c;color:#fff}
.btn-danger:hover{background:#dc2626}
.output-section{margin-bottom:1.2rem}
.output-section h3{font-size:.82rem;color:#8b949e;text-transform:uppercase;letter-spacing:.07em;margin-bottom:.4rem}
.output-box{position:relative;background:#0d1117;border:1px solid #30363d;border-radius:4px;padding:.8rem 2.8rem .8rem .8rem;font-size:.8rem;white-space:pre-wrap;word-break:break-all;max-height:200px;overflow-y:auto;color:#a8d8a8}
.output-box.cmd{color:#ffd700}
.copy-btn{position:absolute;top:.5rem;right:.5rem;background:#21262d;border:1px solid #30363d;color:#8b949e;padding:.2rem .5rem;border-radius:3px;cursor:pointer;font-size:.7rem;font-family:inherit}
.copy-btn:hover{background:#30363d;color:#c9d1d9}
.warn{background:#1c1400;border:1px solid #9e6a03;border-radius:4px;padding:.7rem 1rem;font-size:.82rem;color:#e3b341;margin-bottom:1rem}
.info{background:#0d2136;border:1px solid #1f6feb;border-radius:4px;padding:.7rem 1rem;font-size:.82rem;color:#58a6ff;margin-bottom:1rem}
.hidden{display:none!important}
.step-label{font-size:.78rem;color:#8b949e;margin-bottom:1.5rem}
.divider{border:none;border-top:1px solid #21262d;margin:1rem 0}
.proto-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:.8rem}
.proto-card{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:.9rem;transition:border-color .2s}
.proto-card.enabled{border-color:#238636}
.proto-card label{font-size:.88rem;color:#f0f6fc;font-weight:bold;display:flex;align-items:center;gap:.5rem;margin-bottom:.4rem}
.proto-card .proto-detail{font-size:.76rem;color:#8b949e}
</style>
</head>
<body>
<div class="container">
  <h1>🛰 RTAK Setup Wizard</h1>
  <p class="tagline">Generates configuration for RTAK OmniNode and mesh_babelfish</p>

  <div class="progress" id="progress"></div>

  <!-- ── Step 1: Mode ─────────────────────────────────────────────────── -->
  <div id="s1" class="card">
    <h2>What are you configuring?</h2>
    <div class="mode-grid">
      <div class="mode-btn" id="m-rtak" onclick="selectMode('rtak')">
        <span class="icon">📡</span>
        <span class="name">RTAK OmniNode</span>
        <p class="desc">TAK situational awareness over encrypted LoRa/Reticulum</p>
      </div>
      <div class="mode-btn" id="m-bf" onclick="selectMode('babelfish')">
        <span class="icon">🐟</span>
        <span class="name">mesh_babelfish</span>
        <p class="desc">Multi-protocol LoRa bridge (Meshtastic ↔ Reticulum ↔ MeshCore)</p>
      </div>
    </div>
    <div class="nav" style="margin-top:1.5rem">
      <button class="btn btn-primary" onclick="next()">Next →</button>
    </div>
  </div>

  <!-- ── Step 2a: RTAK Hardware ─────────────────────────────────────── -->
  <div id="s2-rtak" class="card hidden">
    <h2>Hardware</h2>
    <p class="step-label">Select the SBC your OmniNode is built around</p>
    <div class="hw-grid">
      <div class="hw-btn selected" id="hw-pi4b" onclick="selectHW('pi4b')">
        <div class="hw-name">Raspberry Pi 4B</div>
        <div class="hw-detail">Reference build · 4× USB 3.0 · Waveshare UPS HAT D</div>
      </div>
      <div class="hw-btn" id="hw-pi3aplus" onclick="selectHW('pi3aplus')">
        <div class="hw-name">Raspberry Pi 3A+</div>
        <div class="hw-detail">Compact · 1× USB (hub required) · USB-C power bank</div>
      </div>
      <div class="hw-btn" id="hw-opizero2w" onclick="selectHW('opizero2w')">
        <div class="hw-name">Orange Pi Zero 2W</div>
        <div class="hw-detail">Budget · 1× USB (hub required) · Armbian Bookworm</div>
      </div>
      <div class="hw-btn" id="hw-heltec_v4" onclick="selectHW('heltec_v4')">
        <div class="hw-name">Heltec V4 variant</div>
        <div class="hw-detail">Compact · Heltec V4 as RNode · OLED display · no GPS</div>
      </div>
    </div>
    <hr class="divider">
    <div class="field">
      <label>Node name / callsign</label>
      <input type="text" id="node_name" value="RTAK-1" placeholder="e.g. RTAK-Alpha">
    </div>
    <div class="nav">
      <button class="btn btn-secondary" onclick="prev()">← Back</button>
      <button class="btn btn-primary" onclick="next()">Next →</button>
    </div>
  </div>

  <!-- ── Step 2b: BabelFish Protocols ───────────────────────────────── -->
  <div id="s2-bf" class="card hidden">
    <h2>Protocols</h2>
    <p class="step-label">Select which protocols this BabelFish node will bridge</p>
    <div class="field">
      <label>Node name</label>
      <input type="text" id="bf_node_name" value="BabelFish-1">
    </div>
    <hr class="divider">
    <div class="proto-grid">
      <div class="proto-card enabled" id="pc-rns">
        <label><input type="checkbox" id="en_rns" checked onchange="toggleProto('rns')"> Reticulum</label>
        <p class="proto-detail">RNode firmware · LXMF transport · strongest encryption</p>
      </div>
      <div class="proto-card enabled" id="pc-mtk">
        <label><input type="checkbox" id="en_mtk" checked onchange="toggleProto('mtk')"> Meshtastic</label>
        <p class="proto-detail">Standard Meshtastic firmware · widest community</p>
      </div>
      <div class="proto-card enabled" id="pc-mc">
        <label><input type="checkbox" id="en_mc" checked onchange="toggleProto('mc')"> MeshCore</label>
        <p class="proto-detail">Stub adapter (API pending) · enable to reserve slot</p>
      </div>
    </div>
    <hr class="divider">
    <div class="toggle-row">
      <input type="checkbox" id="en_433" onchange="toggle433()">
      <label for="en_433">Enable optional 433 MHz 4th radio</label>
    </div>
    <div id="row_433" class="hidden">
      <div class="row">
        <div class="field">
          <label>433 MHz port</label>
          <input type="text" id="bf_port_433" value="/dev/ttyUSB3">
        </div>
        <div class="field">
          <label>Protocol on 433 slot</label>
          <select id="proto_433">
            <option value="reticulum">Reticulum</option>
            <option value="meshtastic">Meshtastic</option>
            <option value="meshcore">MeshCore</option>
          </select>
        </div>
      </div>
    </div>
    <div class="nav">
      <button class="btn btn-secondary" onclick="prev()">← Back</button>
      <button class="btn btn-primary" onclick="next()">Next →</button>
    </div>
  </div>

  <!-- ── Step 3a: RTAK Radio ──────────────────────────────────────────── -->
  <div id="s3-rtak" class="card hidden">
    <h2>Radio configuration</h2>
    <p class="step-label">USB port assignments and RF parameters</p>
    <div class="info">
      Plug in all radio boards, then run <code>ls /dev/ttyUSB*</code> on the Pi to confirm port assignments.
    </div>
    <div class="row">
      <div class="field">
        <label>915 MHz RNode port</label>
        <input type="text" id="port_915" value="/dev/ttyUSB0">
      </div>
      <div class="field">
        <label>915 MHz frequency (Hz)</label>
        <input type="number" id="freq_915" value="915000000">
      </div>
    </div>
    <hr class="divider">
    <div class="toggle-row">
      <input type="checkbox" id="dual_band" onchange="toggleDual()">
      <label for="dual_band">Enable dual-band (add 433 MHz RNode)</label>
    </div>
    <div id="row_dual" class="hidden">
      <div class="row">
        <div class="field">
          <label>433 MHz RNode port</label>
          <input type="text" id="port_433" value="/dev/ttyUSB1">
        </div>
        <div class="field">
          <label>433 MHz frequency (Hz)</label>
          <input type="number" id="freq_433" value="433000000">
        </div>
      </div>
    </div>
    <hr class="divider">
    <h2>RF parameters</h2>
    <p class="step-label" style="margin-bottom:.8rem">Defaults match US 915 MHz ISM band — adjust for your region</p>
    <div class="row3">
      <div class="field">
        <label>Bandwidth (Hz)</label>
        <select id="bandwidth">
          <option value="125000" selected>125 kHz (recommended)</option>
          <option value="250000">250 kHz (higher speed)</option>
          <option value="500000">500 kHz (fastest, short range)</option>
        </select>
      </div>
      <div class="field">
        <label>Spreading factor</label>
        <select id="sf">
          <option value="7">SF7 (fastest)</option>
          <option value="8" selected>SF8 (balanced)</option>
          <option value="9">SF9</option>
          <option value="10">SF10</option>
          <option value="11">SF11</option>
          <option value="12">SF12 (max range)</option>
        </select>
      </div>
      <div class="field">
        <label>TX power (dBm)</label>
        <select id="txpower">
          <option value="10">10 dBm (10 mW)</option>
          <option value="14">14 dBm (25 mW)</option>
          <option value="17" selected>17 dBm (50 mW)</option>
          <option value="20">20 dBm (100 mW)</option>
        </select>
      </div>
    </div>
    <div class="nav">
      <button class="btn btn-secondary" onclick="prev()">← Back</button>
      <button class="btn btn-primary" onclick="next()">Next →</button>
    </div>
  </div>

  <!-- ── Step 3b: BabelFish Ports ─────────────────────────────────────── -->
  <div id="s3-bf" class="card hidden">
    <h2>Port assignments</h2>
    <p class="step-label">Assign USB ports to each protocol slot. Run <code>ls /dev/ttyUSB*</code> to confirm.</p>
    <div id="bf_port_rns_row" class="field">
      <label>Reticulum (RNode firmware) port</label>
      <input type="text" id="bf_port_rns" value="/dev/ttyUSB0">
    </div>
    <div id="bf_port_mtk_row" class="field">
      <label>Meshtastic port</label>
      <input type="text" id="bf_port_mtk" value="/dev/ttyUSB1">
    </div>
    <div id="bf_port_mc_row" class="field">
      <label>MeshCore port</label>
      <input type="text" id="bf_port_mc" value="/dev/ttyUSB2">
    </div>
    <hr class="divider">
    <div class="row">
      <div class="field">
        <label>Session TTL (seconds)</label>
        <input type="number" id="session_ttl" value="300" min="60" max="3600">
      </div>
      <div class="field">
        <label>Status web server port</label>
        <input type="number" id="status_port" value="8080" min="1024" max="65535">
      </div>
    </div>
    <div class="nav">
      <button class="btn btn-secondary" onclick="prev()">← Back</button>
      <button class="btn btn-primary" onclick="next()">Next →</button>
    </div>
  </div>

  <!-- ── Step 4: RTAK Services ─────────────────────────────────────────── -->
  <div id="s4-rtak" class="card hidden">
    <h2>Optional services</h2>
    <div class="toggle-row">
      <input type="checkbox" id="partyline" checked>
      <label for="partyline">Enable Partyline voice server (encrypted group PTT over LoRa)</label>
    </div>
    <div class="toggle-row">
      <input type="checkbox" id="ax25">
      <label for="ax25">Enable AX.25 packet radio (Digirig + VHF/UHF handheld)</label>
    </div>
    <hr class="divider">
    <h2>Operators</h2>
    <p class="step-label">Comma-separated callsigns — a client TLS certificate will be generated for each</p>
    <div class="field">
      <label>Callsigns</label>
      <input type="text" id="operators" placeholder="e.g. ALPHA,BRAVO,CHARLIE">
    </div>
    <div class="nav">
      <button class="btn btn-secondary" onclick="prev()">← Back</button>
      <button class="btn btn-primary" onclick="next()">Next →</button>
    </div>
  </div>

  <!-- ── Step 5: Review & Generate ──────────────────────────────────── -->
  <div id="s5" class="card hidden">
    <h2>Review &amp; generate</h2>
    <p class="step-label">Check your settings and generate configuration files</p>
    <div id="review-table" class="card" style="background:#0d1117;font-size:.82rem"></div>
    <div class="nav">
      <button class="btn btn-secondary" onclick="prev()">← Back</button>
      <button class="btn btn-primary" onclick="generate()">⚙ Generate configs</button>
    </div>
  </div>

  <!-- ── Step 6: Output ─────────────────────────────────────────────── -->
  <div id="s6" class="card hidden">
    <h2>Generated configuration</h2>
    <div class="warn">
      ⚠ The setup command contains auto-generated passwords. Copy it now — it will not be shown again after you close this page.
    </div>
    <div id="output-sections"></div>
    <div class="nav">
      <button class="btn btn-secondary" onclick="restart()">↩ Start over</button>
    </div>
  </div>
</div>

<script>
const state = {
  mode: null,
  hw: 'pi4b',
  step: 1,
};

// Step sequences per mode
const STEPS = {
  rtak:      [1, '2-rtak', '3-rtak', '4-rtak', 5, 6],
  babelfish: [1, '2-bf',   '3-bf',   5, 6],
};

function stepIds() {
  return (STEPS[state.mode] || [1, 6]);
}

function currentStepId() {
  const ids = stepIds();
  return ids[state.step - 1];
}

function showStep(id) {
  ['s1','s2-rtak','s2-bf','s3-rtak','s3-bf','s4-rtak','s5','s6'].forEach(s => {
    document.getElementById(s).classList.add('hidden');
  });
  document.getElementById('s' + id).classList.remove('hidden');
  updateProgress();
}

function updateProgress() {
  const ids = stepIds();
  const total = ids.length;
  const pips = document.getElementById('progress');
  pips.innerHTML = '';
  ids.forEach((_, i) => {
    const pip = document.createElement('div');
    pip.className = 'pip' + (i + 1 < state.step ? ' done' : i + 1 === state.step ? ' active' : '');
    pips.appendChild(pip);
  });
}

function next() {
  if (state.step === 1 && !state.mode) {
    alert('Please select a configuration type.');
    return;
  }
  state.step++;
  showStep(currentStepId());
  if (currentStepId() === 5) buildReview();
}

function prev() {
  state.step--;
  showStep(currentStepId());
}

function selectMode(m) {
  state.mode = m;
  state.step = 1;
  document.getElementById('m-rtak').classList.toggle('selected', m === 'rtak');
  document.getElementById('m-bf').classList.toggle('selected', m === 'babelfish');
}

function selectHW(hw) {
  state.hw = hw;
  ['pi4b','pi3aplus','opizero2w','heltec_v4'].forEach(h => {
    document.getElementById('hw-' + h).classList.toggle('selected', h === hw);
  });
}

function toggleDual() {
  const on = document.getElementById('dual_band').checked;
  document.getElementById('row_dual').classList.toggle('hidden', !on);
}

function toggle433() {
  const on = document.getElementById('en_433').checked;
  document.getElementById('row_433').classList.toggle('hidden', !on);
}

function toggleProto(p) {
  const cb = document.getElementById('en_' + p);
  document.getElementById('pc-' + p).classList.toggle('enabled', cb.checked);
  // Show/hide the port field
  const rows = {'rns':'bf_port_rns_row','mtk':'bf_port_mtk_row','mc':'bf_port_mc_row'};
  if (rows[p]) document.getElementById(rows[p]).classList.toggle('hidden', !cb.checked);
}

function g(id) {
  const el = document.getElementById(id);
  if (!el) return null;
  if (el.type === 'checkbox') return el.checked;
  return el.value;
}

function collectData() {
  if (state.mode === 'rtak') {
    return {
      mode: 'rtak',
      hardware:    state.hw,
      node_name:   g('node_name'),
      port_915:    g('port_915'),
      port_433:    g('port_433'),
      dual_band:   g('dual_band'),
      freq_915:    g('freq_915'),
      freq_433:    g('freq_433'),
      bandwidth:   g('bandwidth'),
      sf:          g('sf'),
      txpower:     g('txpower'),
      partyline:   g('partyline'),
      ax25:        g('ax25'),
      operators:   g('operators'),
    };
  } else {
    return {
      mode:             'babelfish',
      node_name:        g('bf_node_name'),
      enable_reticulum: g('en_rns'),
      enable_meshtastic:g('en_mtk'),
      enable_meshcore:  g('en_mc'),
      enable_433:       g('en_433'),
      port_reticulum:   g('bf_port_rns'),
      port_meshtastic:  g('bf_port_mtk'),
      port_meshcore:    g('bf_port_mc'),
      port_433:         g('bf_port_433'),
      proto_433:        g('proto_433'),
      freq_915:         g('freq_915') || '915000000',
      freq_433:         '433000000',
      session_ttl:      g('session_ttl'),
      status_port:      g('status_port'),
    };
  }
}

function buildReview() {
  const d = collectData();
  const hwNames = {pi4b:'Pi 4B',pi3aplus:'Pi 3A+',opizero2w:'Orange Pi Zero 2W',heltec_v4:'Heltec V4'};
  let html = '<table style="width:100%;font-size:.82rem;border-collapse:collapse">';
  const row = (k,v) => `<tr><td style="color:#8b949e;padding:.3rem .5rem;white-space:nowrap;vertical-align:top">${k}</td><td style="padding:.3rem .5rem;color:#c9d1d9">${v}</td></tr>`;
  if (d.mode === 'rtak') {
    html += row('Mode','RTAK OmniNode');
    html += row('Hardware', hwNames[d.hardware] || d.hardware);
    html += row('Node name', d.node_name || '(not set)');
    html += row('915 MHz port', d.port_915);
    html += row('Dual-band', d.dual_band ? `Yes — 433 MHz on ${d.port_433}` : 'No');
    html += row('Bandwidth', d.bandwidth + ' Hz');
    html += row('SF / TXP', `SF${d.sf} / ${d.txpower} dBm`);
    html += row('Partyline voice', d.partyline ? '✓ Enabled' : '✗ Disabled');
    html += row('AX.25', d.ax25 ? '✓ Enabled' : '✗ Disabled');
    html += row('Operators', d.operators || '(none — add later)');
  } else {
    html += row('Mode','mesh_babelfish');
    html += row('Node name', d.node_name);
    html += row('Reticulum', d.enable_reticulum ? `✓ ${d.port_reticulum}` : '✗');
    html += row('Meshtastic', d.enable_meshtastic ? `✓ ${d.port_meshtastic}` : '✗');
    html += row('MeshCore', d.enable_meshcore ? `✓ ${d.port_meshcore}` : '✗');
    html += row('433 MHz slot', d.enable_433 ? `✓ ${d.port_433} (${d.proto_433})` : '✗');
    html += row('Session TTL', d.session_ttl + ' seconds');
    html += row('Status port', d.status_port);
  }
  html += '</table>';
  document.getElementById('review-table').innerHTML = html;
}

function generate() {
  const d = collectData();
  fetch('/generate', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(d),
  })
  .then(r => r.json())
  .then(sections => {
    const out = document.getElementById('output-sections');
    out.innerHTML = '';
    sections.forEach(([title, content]) => {
      const isCmd = title.toLowerCase().includes('command') || title.toLowerCase().includes('start');
      const div = document.createElement('div');
      div.className = 'output-section';
      div.innerHTML = `
        <h3>${title}</h3>
        <div class="output-box${isCmd?' cmd':''}" id="ob-${Math.random().toString(36).slice(2)}">
          ${escHtml(content)}
          <button class="copy-btn" onclick="copyBox(this)">copy</button>
        </div>`;
      out.appendChild(div);
    });
    state.step++;
    showStep(currentStepId());
  })
  .catch(e => alert('Generation failed: ' + e));
}

function copyBox(btn) {
  const box = btn.parentElement;
  const text = box.innerText.replace('copy','').trim();
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = '✓';
    setTimeout(() => btn.textContent = 'copy', 1500);
  });
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function restart() {
  state.step = 1;
  state.mode = null;
  document.getElementById('m-rtak').classList.remove('selected');
  document.getElementById('m-bf').classList.remove('selected');
  showStep(1);
}

// Init
showStep(1);
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class WizardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence default access log

    def do_GET(self):
        if urlparse(self.path).path in ('/', '/index.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if urlparse(self.path).path == '/generate':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                mode = data.get('mode', 'rtak')
                if mode == 'rtak':
                    sections = gen_rtak_config(data)
                else:
                    sections = gen_babelfish_config(data)
                resp = json.dumps(sections).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(resp)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self.end_headers()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='RTAK Setup Wizard')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()

    server = HTTPServer(('0.0.0.0', args.port), WizardHandler)
    url = f'http://localhost:{args.port}/'

    print(f'\n  RTAK Setup Wizard')
    print(f'  Running at: {url}')
    print(f'  Also accessible from other devices on your network')
    print(f'  Press Ctrl+C to stop\n')

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n  Stopped.')


if __name__ == '__main__':
    main()
