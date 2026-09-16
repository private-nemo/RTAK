#!/usr/bin/env python3
"""
RTAK Bridge — prototype
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

Dependencies:
  pip install rns lxmf pytak

LXMF is the message layer on top of Reticulum — it handles
fragmentation, store-and-forward, and delivery receipts, which
matters a lot on slow LoRa links.
"""

import asyncio
import logging
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

RTAK_APP_NAME = "rtak"       # must match on all nodes
RTAK_APP_ASPECT = "bridge"

RNS_CONFIG_PATH = None       # None = Reticulum default (~/.reticulum)
LXMF_STORAGE_PATH = "./lxmf_storage"
IDENTITY_STORAGE_PATH = "./rtak_identity"

ANNOUNCE_INTERVAL = 300      # re-announce every 5 minutes
COT_COMPRESS_LEVEL = 6       # zlib: 1=fast, 9=smallest; 6 is good middle ground

# Peer registry: list of hex destination hashes for known remote RTAK nodes.
# A peer here is the LXMF destination hash, printed when each remote bridge starts.
# TODO: replace with dynamic discovery in a future version.
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
                # RNS will attempt to path-find and LXMF will queue for delivery
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
                desired_method=LXMF.LXMessage.PROPAGATED,  # store-and-forward, good for LoRa
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
            if message.title_as_string != "cot":
                log.debug(f"Ignoring non-CoT LXMF message (title={message.title_as_string!r})")
                return

            # Reject inbound CoT from any source not in the trusted peer list.
            # This prevents a rogue or unknown node from injecting false tracks
            # into FreeTAKServer and poisoning the operator's map.
            source_hex = message.source_hash.hex()
            trusted = self._load_peers()
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
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

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
