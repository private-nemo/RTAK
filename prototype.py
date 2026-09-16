#!/usr/bin/env python3
"""
RTAK Bridge — v1.0.5
Routes CoT (Cursor on Target) messages between a local FreeTAKServer
instance and a private Reticulum network over any transport
(LoRa 433/915, WiFi, AX.25, serial, etc.).

Architecture:
  ATAK clients
      ↕  TCP CoT  (port 8087)
  FreeTAKServer  (local Pi)
      ↕  TCP CoT  (this bridge connects to FTS as a client)
  rtak_bridge
      ↕  LXMF messages (compressed CoT)
  Reticulum network  (LoRa / WiFi / AX.25 / anything)
      ↕
  Remote RTAK nodes  (same stack)

v1.0.5 additions:
  - Panic wipe system: one command erases FTS event logs on this node
    and all trusted peers simultaneously via LXMF
  - HTTP control panel on port 8888 (accessible from ATAK's browser):
      GET  /        — panic button UI
      GET  /status  — node status JSON
      POST /panic   — trigger wipe + propagate to all peers
  - Inbound LXMF "panic" messages from trusted peers trigger local wipe
    and do NOT re-propagate (prevents wipe loops)

Dependencies:
  pip install rns lxmf pytak
"""

import asyncio
import functools
import http.server
import json
import logging
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Optional

import RNS
import LXMF

# ---------------------------------------------------------------------------
# Config — override via CLI args or environment; sensible defaults for the Pi
# ---------------------------------------------------------------------------

FTS_HOST = "127.0.0.1"
FTS_COT_PORT = 8087          # FreeTAKServer TCP CoT streaming port
FTS_RECONNECT_DELAY = 10     # seconds between reconnect attempts
FTS_DB_PATH = "/opt/rtak/fts_data.db"  # FTS SQLite database (wipe target)

RTAK_APP_NAME = "rtak"       # must match on all nodes
RTAK_APP_ASPECT = "bridge"

RNS_CONFIG_PATH = None       # None = Reticulum default (~/.reticulum)
LXMF_STORAGE_PATH = "./lxmf_storage"
IDENTITY_STORAGE_PATH = "./rtak_identity"

ANNOUNCE_INTERVAL = 300      # re-announce every 5 minutes
COT_COMPRESS_LEVEL = 6       # zlib: 1=fast, 9=smallest; 6 is good middle ground

PANIC_HTTP_PORT = 8888       # panic button web UI — open in ATAK browser at http://<node-ip>:8888

# Peer registry: list of hex destination hashes for known remote RTAK nodes.
KNOWN_PEERS_FILE = "./rtak_peers.txt"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("rtak")


# ---------------------------------------------------------------------------
# Panic button HTTP server
# ---------------------------------------------------------------------------

class _PanicHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler for the RTAK panic button control panel."""

    def __init__(self, bridge, *args, **kwargs):
        self.bridge = bridge
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        pass  # suppress per-request access log noise

    def do_GET(self):
        if self.path == "/status":
            peers = self.bridge._load_peers()
            self._json({"status": "ok", "peers": len(peers)})
        elif self.path in ("/", "/panic"):
            self._html()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/panic":
            self.bridge._handle_panic(source="local_http")
            self._json({"status": "wiped", "propagated": True})
        else:
            self.send_error(404)

    def _json(self, data: dict):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self):
        body = b"""<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>RTAK Control</title>
  <style>
    body{font-family:monospace;background:#111;color:#0f0;padding:20px;max-width:480px;margin:auto}
    h1{color:#0f0;margin-bottom:4px}
    p{color:#888;font-size:14px}
    .panic{display:block;width:100%;padding:28px;background:#800;color:#fff;
           font-size:22px;font-weight:bold;border:none;border-radius:8px;
           cursor:pointer;margin-top:28px;letter-spacing:1px}
    .panic:active{background:#c00}
    #msg{margin-top:20px;color:#ff0;min-height:24px;font-size:14px}
  </style>
</head>
<body>
  <h1>RTAK Node</h1>
  <p>Panic wipe deletes all FTS event logs on this node and transmits
     the wipe command to every trusted peer via Reticulum.</p>
  <button class="panic" onclick="go()">&#9888; PANIC — WIPE ALL LOGS</button>
  <div id="msg"></div>
  <script>
    function go(){
      if(!confirm("Wipe all FTS event logs on this node and all peers?"))return;
      document.getElementById("msg").textContent="Wiping…";
      fetch("/panic",{method:"POST"})
        .then(r=>r.json())
        .then(d=>{document.getElementById("msg").textContent="Done: "+JSON.stringify(d);})
        .catch(e=>{document.getElementById("msg").textContent="Error: "+e;});
    }
  </script>
</body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------

class RTAKBridge:
    def __init__(
        self,
        fts_host: str = FTS_HOST,
        fts_port: int = FTS_COT_PORT,
        debug: bool = False,
    ):
        self.fts_host = fts_host
        self.fts_port = fts_port
        if debug:
            logging.getLogger().setLevel(logging.DEBUG)

        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._fts_writer: Optional[asyncio.StreamWriter] = None

        # Reticulum / LXMF
        self._rns: Optional[RNS.Reticulum] = None
        self._router: Optional[LXMF.LXMRouter] = None
        self._identity: Optional[RNS.Identity] = None
        self._destination = None  # LXMF delivery destination

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def start(self):
        self._running = True
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._init_reticulum()
        self._start_panic_server()
        threading.Thread(target=self._announce_loop, daemon=True).start()

        log.info("Bridge running. Press Ctrl-C to stop.")
        try:
            self._loop.run_until_complete(self._fts_connect_loop())
        finally:
            self.stop()

    def _init_reticulum(self):
        log.info("Starting Reticulum...")
        self._rns = RNS.Reticulum(configdir=RNS_CONFIG_PATH)

        # Persistent node identity — same hash survives restarts
        id_path = IDENTITY_STORAGE_PATH
        if Path(id_path).exists():
            self._identity = RNS.Identity.from_file(id_path)
            log.info(f"Loaded identity: {RNS.prettyhexrep(self._identity.hash)}")
        else:
            self._identity = RNS.Identity()
            self._identity.to_file(id_path)
            log.info(f"Created identity: {RNS.prettyhexrep(self._identity.hash)}")

        # LXMF router — handles fragmentation + store-and-forward
        self._router = LXMF.LXMRouter(storagepath=LXMF_STORAGE_PATH)
        self._destination = self._router.register_delivery_identity(
            self._identity,
            display_name="RTAK Node",
        )
        self._router.register_delivery_callback(self._on_lxmf_inbound)

        log.info(
            f"RTAK bridge address: {RNS.prettyhexrep(self._destination.hash)}\n"
            f"Share this hash with other node operators so they can add it to rtak_peers.txt"
        )
        self._destination.announce()

    def _announce_loop(self):
        while self._running:
            time.sleep(ANNOUNCE_INTERVAL)
            if self._running and self._destination:
                self._destination.announce()
                log.debug("Re-announced to Reticulum network")

    # ------------------------------------------------------------------
    # Panic server
    # ------------------------------------------------------------------

    def _start_panic_server(self):
        handler = functools.partial(_PanicHandler, self)
        server = http.server.HTTPServer(("0.0.0.0", PANIC_HTTP_PORT), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        log.info(
            f"Panic control panel: http://<node-ip>:{PANIC_HTTP_PORT}/\n"
            f"  Open this URL in ATAK's built-in browser to access the panic wipe button."
        )

    # ------------------------------------------------------------------
    # Panic wipe
    # ------------------------------------------------------------------

    def _wipe_fts_logs(self):
        """Delete all records from the FTS SQLite database."""
        db_path = Path(FTS_DB_PATH)
        if not db_path.exists():
            log.warning(f"PANIC: FTS database not found at {FTS_DB_PATH} — nothing to wipe")
            return
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            wiped = 0
            for table in tables:
                try:
                    cur.execute(f"DELETE FROM {table}")  # noqa: S608 — controlled input
                    wiped += 1
                except Exception as exc:
                    log.debug(f"PANIC: could not wipe table {table!r}: {exc}")
            conn.commit()
            conn.close()
            log.warning(f"PANIC: wiped {wiped}/{len(tables)} FTS tables in {FTS_DB_PATH}")
        except Exception as exc:
            log.error(f"PANIC: FTS wipe failed: {exc}")

    def _propagate_panic(self):
        """Send a panic wipe command to all trusted peers via LXMF."""
        peers = self._load_peers()
        if not peers:
            log.warning("PANIC: no peers configured — wipe is local only")
            return
        log.warning(f"PANIC: propagating wipe command to {len(peers)} peer(s)")
        for peer_hex in peers:
            try:
                peer_hash = bytes.fromhex(peer_hex)
                peer_identity = RNS.Identity.recall(peer_hash)
                dest = RNS.Destination(
                    peer_identity,
                    RNS.Destination.OUT,
                    RNS.Destination.SINGLE,
                    RTAK_APP_NAME,
                    RTAK_APP_ASPECT,
                )
                msg = LXMF.LXMessage(
                    destination=dest,
                    source=self._destination,
                    content=b"wipe",
                    title="panic",
                    desired_method=LXMF.LXMessage.PROPAGATED,
                )
                self._router.handle_outbound(msg)
                log.warning(f"PANIC: wipe command sent to {peer_hex[:16]}…")
            except Exception as exc:
                log.error(f"PANIC: failed to send wipe to {peer_hex[:16]}…: {exc}")

    def _handle_panic(self, source: str = "unknown", propagate: bool = True):
        """Wipe local FTS logs and optionally propagate to peers."""
        log.warning(f"PANIC triggered — source: {source}")
        self._wipe_fts_logs()
        if propagate:
            self._propagate_panic()

    # ------------------------------------------------------------------
    # FreeTAKServer connection loop
    # ------------------------------------------------------------------

    async def _fts_connect_loop(self):
        while self._running:
            try:
                log.info(f"Connecting to FreeTAKServer {self.fts_host}:{self.fts_port}")
                reader, writer = await asyncio.open_connection(self.fts_host, self.fts_port)
                self._fts_writer = writer
                log.info("Connected to FreeTAKServer — bridging CoT")
                await self._fts_read_loop(reader)
            except (ConnectionRefusedError, OSError) as exc:
                log.warning(f"FTS not reachable ({exc}), retrying in {FTS_RECONNECT_DELAY}s")
                self._fts_writer = None
                await asyncio.sleep(FTS_RECONNECT_DELAY)
            except Exception as exc:
                log.error(f"Unexpected FTS error: {exc}")
                self._fts_writer = None
                await asyncio.sleep(FTS_RECONNECT_DELAY)

    async def _fts_read_loop(self, reader: asyncio.StreamReader):
        """Read CoT XML events from FreeTAKServer and relay to Reticulum peers."""
        buf = b""
        while self._running:
            try:
                chunk = await asyncio.wait_for(reader.read(8192), timeout=5.0)
                if not chunk:
                    log.warning("FreeTAKServer closed the connection")
                    break
                buf += chunk

                # CoT events are self-delimited by </event>; parse out whole events
                while b"</event>" in buf:
                    end = buf.index(b"</event>") + len(b"</event>")
                    cot_xml = buf[:end]
                    buf = buf[end:]
                    await self._relay_outbound(cot_xml)

            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                log.error(f"FTS read error: {exc}")
                break

    # ------------------------------------------------------------------
    # Outbound: FTS → Reticulum
    # ------------------------------------------------------------------

    async def _relay_outbound(self, cot_xml: bytes):
        compressed = zlib.compress(cot_xml, COT_COMPRESS_LEVEL)
        log.debug(
            f"Outbound CoT: {len(cot_xml)}b → {len(compressed)}b compressed "
            f"({100 - int(len(compressed)/len(cot_xml)*100)}% reduction)"
        )
        peers = self._load_peers()
        if not peers:
            log.debug("No peers configured; nothing to relay")
            return

        for peer_hex in peers:
            await self._loop.run_in_executor(None, self._send_lxmf, peer_hex, compressed)

    def _send_lxmf(self, peer_hex: str, payload: bytes):
        try:
            peer_hash = bytes.fromhex(peer_hex)
            peer_identity = RNS.Identity.recall(peer_hash)
            if peer_identity is None:
                log.debug(f"Identity for {peer_hex[:16]}… not in path table yet; queuing")
            dest = RNS.Destination(
                peer_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                RTAK_APP_NAME,
                RTAK_APP_ASPECT,
            )
            msg = LXMF.LXMessage(
                destination=dest,
                source=self._destination,
                content=payload,
                title="cot",
                desired_method=LXMF.LXMessage.PROPAGATED,
            )
            self._router.handle_outbound(msg)
            log.debug(f"Queued CoT for {peer_hex[:16]}…")
        except Exception as exc:
            log.warning(f"Failed to send to peer {peer_hex[:16]}…: {exc}")

    # ------------------------------------------------------------------
    # Inbound: Reticulum → FTS
    # ------------------------------------------------------------------

    def _on_lxmf_inbound(self, message: LXMF.LXMessage):
        """Called by LXMF router in its own thread when a message arrives."""
        try:
            title = message.title_as_string
            source_hex = message.source_hash.hex()
            trusted = self._load_peers()

            # Panic wipe command from a trusted peer — wipe local logs only,
            # do NOT re-propagate (prevents wipe-loop storms on the network).
            if title == "panic":
                if source_hex in trusted:
                    self._handle_panic(
                        source=f"peer:{source_hex[:16]}",
                        propagate=False,
                    )
                else:
                    log.warning(
                        f"REJECTED panic from untrusted source {source_hex[:16]}… "
                        f"— add to rtak_peers.txt to allow"
                    )
                return

            if title != "cot":
                log.debug(f"Ignoring non-CoT LXMF message (title={title!r})")
                return

            # Reject inbound CoT from any source not in the trusted peer list.
            if source_hex not in trusted:
                log.warning(
                    f"REJECTED inbound CoT from untrusted source {source_hex[:16]}… "
                    f"— add to rtak_peers.txt to allow"
                )
                return

            cot_xml = zlib.decompress(message.content)
            log.info(
                f"Inbound CoT from {RNS.prettyhexrep(message.source_hash)}: {len(cot_xml)}b"
            )
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._inject_to_fts(cot_xml), self._loop
                )
        except zlib.error as exc:
            log.warning(f"Decompression failed (non-RTAK message?): {exc}")
        except Exception as exc:
            log.error(f"Inbound message processing error: {exc}")

    async def _inject_to_fts(self, cot_xml: bytes):
        """Push received CoT into FreeTAKServer so local ATAK clients see it."""
        if self._fts_writer is None or self._fts_writer.is_closing():
            log.warning("FTS not connected; dropping inbound CoT")
            return
        try:
            self._fts_writer.write(cot_xml)
            await self._fts_writer.drain()
            log.debug(f"Injected {len(cot_xml)}b CoT into FTS")
        except Exception as exc:
            log.error(f"FTS inject failed: {exc}")
            self._fts_writer = None

    # ------------------------------------------------------------------
    # Peer management
    # ------------------------------------------------------------------

    def _load_peers(self) -> list[str]:
        """
        Load peer destination hashes from rtak_peers.txt.
        One hex hash per line. Lines starting with # are comments.
        """
        path = Path(KNOWN_PEERS_FILE)
        if not path.exists():
            return []
        peers = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if len(line) == 32:  # Reticulum destination hashes are 16 bytes = 32 hex chars
                peers.append(line)
            else:
                log.warning(f"Skipping malformed peer hash: {line!r} (expected 32 hex chars)")
        return peers

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def stop(self):
        self._running = False
        log.info("Bridge stopped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="RTAK Bridge — CoT over Reticulum",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--fts-host", default=FTS_HOST, help="FreeTAKServer host")
    parser.add_argument("--fts-port", type=int, default=FTS_COT_PORT, help="FTS CoT TCP port")
    parser.add_argument("--panic-port", type=int, default=PANIC_HTTP_PORT,
                        help="HTTP port for panic button control panel")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    global PANIC_HTTP_PORT
    PANIC_HTTP_PORT = args.panic_port

    bridge = RTAKBridge(
        fts_host=args.fts_host,
        fts_port=args.fts_port,
        debug=args.debug,
    )
    try:
        bridge.start()
    except KeyboardInterrupt:
        log.info("Interrupted")
        bridge.stop()


if __name__ == "__main__":
    main()
