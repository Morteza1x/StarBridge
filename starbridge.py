#!/usr/bin/env python3
"""
StarBridge MVP

Personal remote exit-node tunnel with three modes:
1) relay       -> public TCP relay (VPS)
2) home-agent  -> runs on home Windows machine (internet egress via Starlink)
3) socks-client-> local SOCKS5 proxy that forwards via relay/home-agent

This is a technical prototype for personal use, not a production VPN.
"""

import argparse
import asyncio
import contextlib
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import secrets
import ssl
import struct
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

HEADER = struct.Struct("!BII")
MAX_PAYLOAD = 4 * 1024 * 1024

OPEN = 1
DATA = 2
CLOSE = 3
OPEN_OK = 4
OPEN_ERR = 5
PING = 6
PONG = 7

LOGGER = logging.getLogger("starbridge")


class ProtocolError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def generate_configs(args: argparse.Namespace) -> None:
    count = args.count
    start_port = args.start_port
    if count < 1:
        raise ValueError("--count must be >= 1")
    if not (1 <= start_port <= 65535):
        raise ValueError("--start-port out of range")
    if start_port + count - 1 > 65535:
        raise ValueError("port range exceeds 65535")
    if args.token_bytes < 8:
        raise ValueError("--token-bytes must be >= 8")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    width = max(2, len(str(count)))
    created_at = utc_now_iso()
    profiles = []

    for idx in range(count):
        n = idx + 1
        relay_port = start_port + idx
        token = secrets.token_urlsafe(args.token_bytes)
        name = f"{args.prefix}-{n:0{width}d}"
        profile = {
            "name": name,
            "created_at_utc": created_at,
            "relay_host": args.relay_host,
            "relay_port": relay_port,
            "token": token,
            "use_tls": not args.no_tls,
            "ca_file": args.ca_file or None,
            "relay_bind_host": args.relay_bind_host or None,
            "egress_bind_host": args.egress_bind_host or None,
            "listen_host": args.listen_host,
            "listen_port": args.listen_port,
            "uri": f"starbridge://{token}@{args.relay_host}:{relay_port}?tls={0 if args.no_tls else 1}",
        }
        profiles.append(profile)
        profile_path = output_dir / f"{name}.json"
        profile_path.write_text(
            json.dumps(profile, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )

    bundle = {
        "generated_at_utc": created_at,
        "count": count,
        "profiles": profiles,
    }
    bundle_path = output_dir / "profiles.json"
    bundle_path.write_text(
        json.dumps(bundle, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    LOGGER.info("generated %s profiles in %s", count, output_dir)
    LOGGER.info("bundle file: %s", bundle_path)


def peer_name(writer: asyncio.StreamWriter) -> str:
    peer = writer.get_extra_info("peername")
    if not peer:
        return "unknown"
    if isinstance(peer, tuple) and len(peer) >= 2:
        return f"{peer[0]}:{peer[1]}"
    return str(peer)


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def read_frame(
    reader: asyncio.StreamReader,
) -> Optional[Tuple[int, int, bytes]]:
    try:
        header = await reader.readexactly(HEADER.size)
    except asyncio.IncompleteReadError as exc:
        if not exc.partial:
            return None
        raise ProtocolError("truncated frame header") from exc

    frame_type, conn_id, payload_size = HEADER.unpack(header)
    if payload_size > MAX_PAYLOAD:
        raise ProtocolError(f"payload too large: {payload_size}")

    try:
        payload = await reader.readexactly(payload_size)
    except asyncio.IncompleteReadError as exc:
        raise ProtocolError("truncated frame payload") from exc

    return frame_type, conn_id, payload


async def send_frame(
    writer: asyncio.StreamWriter,
    lock: Optional[asyncio.Lock],
    frame_type: int,
    conn_id: int,
    payload: bytes = b"",
) -> None:
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError("payload exceeds MAX_PAYLOAD")
    packet = HEADER.pack(frame_type, conn_id, len(payload)) + payload
    if lock is None:
        writer.write(packet)
        await writer.drain()
        return
    async with lock:
        writer.write(packet)
        await writer.drain()


def encode_target(host: str, port: int) -> bytes:
    if not host:
        raise ValueError("host is empty")
    if not (1 <= port <= 65535):
        raise ValueError("port out of range")
    return json.dumps({"host": host, "port": port}, separators=(",", ":")).encode(
        "utf-8"
    )


def decode_target(payload: bytes) -> Tuple[str, int]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid OPEN payload json") from exc
    host = str(data.get("host", "")).strip()
    port = int(data.get("port", 0))
    if not host or not (1 <= port <= 65535):
        raise ProtocolError("invalid host/port in OPEN payload")
    return host, port


def parse_role_line(raw: bytes) -> Tuple[str, str]:
    line = raw.decode("utf-8", errors="ignore").strip()
    parts = line.split()
    if len(parts) != 3 or parts[0] != "ROLE":
        raise ProtocolError("handshake must be: ROLE <AGENT|CLIENT> <token>")
    role = parts[1].upper()
    token = parts[2]
    if role not in {"AGENT", "CLIENT"}:
        raise ProtocolError("role must be AGENT or CLIENT")
    return role, token


def make_server_ssl(certfile: Optional[str], keyfile: Optional[str]) -> Optional[ssl.SSLContext]:
    if not certfile and not keyfile:
        return None
    if not certfile or not keyfile:
        raise ValueError("both --certfile and --keyfile are required")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile, keyfile=keyfile)
    return context


def make_client_ssl(ca_file: Optional[str]) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    if ca_file:
        context.load_verify_locations(cafile=ca_file)
    return context


@dataclass
class ClientState:
    client_id: int
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    write_lock: asyncio.Lock


class RelayServer:
    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        certfile: Optional[str],
        keyfile: Optional[str],
    ) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.certfile = certfile
        self.keyfile = keyfile

        self._state_lock = asyncio.Lock()
        self._agent_reader: Optional[asyncio.StreamReader] = None
        self._agent_writer: Optional[asyncio.StreamWriter] = None
        self._agent_write_lock: Optional[asyncio.Lock] = None

        self._clients: Dict[int, ClientState] = {}
        self._next_client_id = 1
        self._next_relay_conn_id = 1

        self._relay_to_client: Dict[int, Tuple[int, int]] = {}
        self._client_to_relay: Dict[Tuple[int, int], int] = {}

    async def run(self) -> None:
        ssl_context = make_server_ssl(self.certfile, self.keyfile)
        server = await asyncio.start_server(
            self._handle_connection,
            host=self.host,
            port=self.port,
            ssl=ssl_context,
        )
        mode = "TLS" if ssl_context else "plain TCP"
        LOGGER.info("relay listening on %s:%s (%s)", self.host, self.port, mode)
        async with server:
            await server.serve_forever()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        remote = peer_name(writer)
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=15)
            if not raw:
                raise ProtocolError("empty handshake")
            role, token = parse_role_line(raw)
            if token != self.token:
                raise ProtocolError("invalid token")
            if role == "AGENT":
                LOGGER.info("agent connected from %s", remote)
                await self._handle_agent(reader, writer)
                return
            await self._handle_client(reader, writer)
        except ProtocolError as exc:
            LOGGER.warning("rejecting %s: %s", remote, exc)
        except Exception:
            LOGGER.exception("connection failed from %s", remote)
        finally:
            if not writer.is_closing():
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

    async def _handle_agent(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        async with self._state_lock:
            if self._agent_writer and not self._agent_writer.is_closing():
                LOGGER.warning("replacing existing agent connection")
                self._agent_writer.close()
                with contextlib.suppress(Exception):
                    await self._agent_writer.wait_closed()
            self._agent_reader = reader
            self._agent_writer = writer
            self._agent_write_lock = asyncio.Lock()

        try:
            while True:
                frame = await read_frame(reader)
                if frame is None:
                    LOGGER.warning("agent disconnected")
                    break
                frame_type, relay_conn_id, payload = frame
                mapping = self._relay_to_client.get(relay_conn_id)
                if not mapping:
                    continue
                client_id, client_conn_id = mapping
                client = self._clients.get(client_id)
                if not client:
                    self._drop_mapping(relay_conn_id)
                    continue
                await send_frame(
                    client.writer,
                    client.write_lock,
                    frame_type,
                    client_conn_id,
                    payload,
                )
                if frame_type in (CLOSE, OPEN_ERR):
                    self._drop_mapping(relay_conn_id)
        finally:
            async with self._state_lock:
                if writer is self._agent_writer:
                    self._agent_reader = None
                    self._agent_writer = None
                    self._agent_write_lock = None
            await self._notify_clients_agent_offline()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        async with self._state_lock:
            client_id = self._next_client_id
            self._next_client_id += 1
            client = ClientState(
                client_id=client_id,
                reader=reader,
                writer=writer,
                write_lock=asyncio.Lock(),
            )
            self._clients[client_id] = client
        LOGGER.info("client#%s connected from %s", client_id, peer_name(writer))

        try:
            while True:
                frame = await read_frame(reader)
                if frame is None:
                    break
                frame_type, client_conn_id, payload = frame
                if frame_type == OPEN:
                    await self._relay_open(client, client_conn_id, payload)
                    continue
                relay_conn_id = self._client_to_relay.get((client.client_id, client_conn_id))
                if relay_conn_id is None:
                    continue
                agent_writer, agent_lock = self._current_agent()
                if not agent_writer or not agent_lock:
                    await send_frame(
                        client.writer,
                        client.write_lock,
                        OPEN_ERR,
                        client_conn_id,
                        b"agent_offline",
                    )
                    self._drop_mapping(relay_conn_id)
                    continue
                await send_frame(agent_writer, agent_lock, frame_type, relay_conn_id, payload)
                if frame_type == CLOSE:
                    self._drop_mapping(relay_conn_id)
        finally:
            LOGGER.info("client#%s disconnected", client.client_id)
            await self._drop_all_for_client(client.client_id)
            self._clients.pop(client.client_id, None)

    def _current_agent(
        self,
    ) -> Tuple[Optional[asyncio.StreamWriter], Optional[asyncio.Lock]]:
        writer = self._agent_writer
        lock = self._agent_write_lock
        if writer is None or writer.is_closing():
            return None, None
        return writer, lock

    async def _relay_open(
        self, client: ClientState, client_conn_id: int, payload: bytes
    ) -> None:
        try:
            decode_target(payload)
        except ProtocolError:
            await send_frame(
                client.writer,
                client.write_lock,
                OPEN_ERR,
                client_conn_id,
                b"bad_target",
            )
            return
        agent_writer, agent_lock = self._current_agent()
        if not agent_writer or not agent_lock:
            await send_frame(
                client.writer,
                client.write_lock,
                OPEN_ERR,
                client_conn_id,
                b"agent_offline",
            )
            return
        relay_conn_id = self._next_relay_conn_id
        self._next_relay_conn_id += 1
        self._relay_to_client[relay_conn_id] = (client.client_id, client_conn_id)
        self._client_to_relay[(client.client_id, client_conn_id)] = relay_conn_id
        await send_frame(agent_writer, agent_lock, OPEN, relay_conn_id, payload)

    def _drop_mapping(self, relay_conn_id: int) -> None:
        mapping = self._relay_to_client.pop(relay_conn_id, None)
        if not mapping:
            return
        client_id, client_conn_id = mapping
        self._client_to_relay.pop((client_id, client_conn_id), None)

    async def _drop_all_for_client(self, client_id: int) -> None:
        keys = [
            relay_conn_id
            for relay_conn_id, mapping in self._relay_to_client.items()
            if mapping[0] == client_id
        ]
        agent_writer, agent_lock = self._current_agent()
        for relay_conn_id in keys:
            if agent_writer and agent_lock:
                with contextlib.suppress(Exception):
                    await send_frame(agent_writer, agent_lock, CLOSE, relay_conn_id)
            self._drop_mapping(relay_conn_id)

    async def _notify_clients_agent_offline(self) -> None:
        stale = list(self._relay_to_client.items())
        for relay_conn_id, (client_id, client_conn_id) in stale:
            client = self._clients.get(client_id)
            if client:
                with contextlib.suppress(Exception):
                    await send_frame(
                        client.writer,
                        client.write_lock,
                        OPEN_ERR,
                        client_conn_id,
                        b"agent_offline",
                    )
            self._drop_mapping(relay_conn_id)


class HomeAgent:
    def __init__(
        self,
        relay_host: str,
        relay_port: int,
        token: str,
        use_tls: bool,
        ca_file: Optional[str],
        retry_seconds: int,
        relay_bind_host: Optional[str] = None,
        egress_bind_host: Optional[str] = None,
    ) -> None:
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.token = token
        self.use_tls = use_tls
        self.ca_file = ca_file
        self.retry_seconds = retry_seconds
        self.relay_bind_host = relay_bind_host
        self.egress_bind_host = egress_bind_host

        self._relay_writer: Optional[asyncio.StreamWriter] = None
        self._relay_writer_lock = asyncio.Lock()
        self._upstreams: Dict[int, asyncio.StreamWriter] = {}
        self._tasks: Dict[int, asyncio.Task] = {}

    async def run_forever(self) -> None:
        while True:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("home-agent crashed, retrying in %ss", self.retry_seconds)
                await asyncio.sleep(self.retry_seconds)

    async def _run_once(self) -> None:
        ssl_context = make_client_ssl(self.ca_file) if self.use_tls else None
        relay_local_addr = (self.relay_bind_host, 0) if self.relay_bind_host else None
        reader, writer = await asyncio.open_connection(
            host=self.relay_host,
            port=self.relay_port,
            ssl=ssl_context,
            server_hostname=self.relay_host if ssl_context else None,
            local_addr=relay_local_addr,
        )
        self._relay_writer = writer
        writer.write(f"ROLE AGENT {self.token}\n".encode("utf-8"))
        await writer.drain()
        LOGGER.info("home-agent connected to relay %s:%s", self.relay_host, self.relay_port)
        if self.relay_bind_host:
            LOGGER.info("home-agent relay bind host: %s", self.relay_bind_host)
        if self.egress_bind_host:
            LOGGER.info("home-agent egress bind host: %s", self.egress_bind_host)
        try:
            while True:
                frame = await read_frame(reader)
                if frame is None:
                    LOGGER.warning("relay disconnected")
                    return
                frame_type, conn_id, payload = frame
                if frame_type == OPEN:
                    await self._handle_open(conn_id, payload)
                elif frame_type == DATA:
                    await self._handle_data(conn_id, payload)
                elif frame_type == CLOSE:
                    await self._handle_close(conn_id)
                elif frame_type == PING:
                    await self._send(PONG, conn_id)
        finally:
            await self._cleanup_all()
            self._relay_writer = None
            if not writer.is_closing():
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

    async def _send(self, frame_type: int, conn_id: int, payload: bytes = b"") -> None:
        writer = self._relay_writer
        if not writer or writer.is_closing():
            return
        await send_frame(writer, self._relay_writer_lock, frame_type, conn_id, payload)

    async def _handle_open(self, conn_id: int, payload: bytes) -> None:
        try:
            host, port = decode_target(payload)
            egress_local_addr = (self.egress_bind_host, 0) if self.egress_bind_host else None
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection(host=host, port=port, local_addr=egress_local_addr),
                timeout=12,
            )
        except Exception as exc:
            await self._send(OPEN_ERR, conn_id, str(exc).encode("utf-8", errors="ignore")[:256])
            return
        self._upstreams[conn_id] = upstream_writer
        task = asyncio.create_task(self._pump_upstream(conn_id, upstream_reader))
        self._tasks[conn_id] = task
        await self._send(OPEN_OK, conn_id)

    async def _handle_data(self, conn_id: int, payload: bytes) -> None:
        writer = self._upstreams.get(conn_id)
        if not writer:
            await self._send(CLOSE, conn_id)
            return
        writer.write(payload)
        try:
            await writer.drain()
        except Exception:
            await self._handle_close(conn_id)

    async def _handle_close(self, conn_id: int) -> None:
        writer = self._upstreams.pop(conn_id, None)
        if writer and not writer.is_closing():
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        task = self._tasks.pop(conn_id, None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _pump_upstream(self, conn_id: int, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                await self._send(DATA, conn_id, data)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.debug("upstream read failed for conn %s", conn_id, exc_info=True)
        finally:
            await self._send(CLOSE, conn_id)
            writer = self._upstreams.pop(conn_id, None)
            if writer and not writer.is_closing():
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
            self._tasks.pop(conn_id, None)

    async def _cleanup_all(self) -> None:
        conn_ids = list(self._upstreams.keys())
        for conn_id in conn_ids:
            await self._handle_close(conn_id)


class SocksClientGateway:
    def __init__(
        self,
        relay_host: str,
        relay_port: int,
        token: str,
        listen_host: str,
        listen_port: int,
        use_tls: bool,
        ca_file: Optional[str],
        relay_bind_host: Optional[str] = None,
    ) -> None:
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.token = token
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.use_tls = use_tls
        self.ca_file = ca_file
        self.relay_bind_host = relay_bind_host

        self._relay_reader: Optional[asyncio.StreamReader] = None
        self._relay_writer: Optional[asyncio.StreamWriter] = None
        self._relay_lock = asyncio.Lock()
        self._conn_state: Dict[int, Dict[str, object]] = {}
        self._next_conn_id = 1
        self._state_lock = asyncio.Lock()

    async def run(self) -> None:
        await self._connect_relay()
        relay_task = asyncio.create_task(self._relay_loop())
        socks_server = await asyncio.start_server(
            self._handle_socks_client,
            self.listen_host,
            self.listen_port,
        )
        LOGGER.info(
            "SOCKS5 listening on %s:%s", self.listen_host, self.listen_port
        )
        try:
            async with socks_server:
                await socks_server.serve_forever()
        finally:
            relay_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await relay_task
            await self._disconnect_relay()

    async def _connect_relay(self) -> None:
        ssl_context = make_client_ssl(self.ca_file) if self.use_tls else None
        relay_local_addr = (self.relay_bind_host, 0) if self.relay_bind_host else None
        reader, writer = await asyncio.open_connection(
            host=self.relay_host,
            port=self.relay_port,
            ssl=ssl_context,
            server_hostname=self.relay_host if ssl_context else None,
            local_addr=relay_local_addr,
        )
        writer.write(f"ROLE CLIENT {self.token}\n".encode("utf-8"))
        await writer.drain()
        self._relay_reader = reader
        self._relay_writer = writer
        LOGGER.info("SOCKS client connected to relay %s:%s", self.relay_host, self.relay_port)
        if self.relay_bind_host:
            LOGGER.info("SOCKS client relay bind host: %s", self.relay_bind_host)

    async def _disconnect_relay(self) -> None:
        writer = self._relay_writer
        self._relay_reader = None
        self._relay_writer = None
        if writer and not writer.is_closing():
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _relay_send(self, frame_type: int, conn_id: int, payload: bytes = b"") -> None:
        writer = self._relay_writer
        if not writer:
            raise ProtocolError("relay not connected")
        await send_frame(writer, self._relay_lock, frame_type, conn_id, payload)

    async def _relay_loop(self) -> None:
        reader = self._relay_reader
        if reader is None:
            return
        try:
            while True:
                frame = await read_frame(reader)
                if frame is None:
                    raise ProtocolError("relay closed connection")
                frame_type, conn_id, payload = frame
                state = self._conn_state.get(conn_id)
                if not state:
                    continue
                if frame_type == OPEN_OK:
                    state["open_event"].set()
                elif frame_type == OPEN_ERR:
                    state["open_error"] = payload.decode("utf-8", errors="ignore") or "open_error"
                    state["open_event"].set()
                    state["close_event"].set()
                elif frame_type == DATA:
                    client_writer = state["client_writer"]
                    client_writer.write(payload)
                    await client_writer.drain()
                elif frame_type == CLOSE:
                    state["close_event"].set()
                    state["open_event"].set()
                    client_writer = state["client_writer"]
                    if not client_writer.is_closing():
                        client_writer.close()
        except Exception:
            LOGGER.exception("relay loop ended")
            for state in self._conn_state.values():
                state["open_error"] = "relay_disconnected"
                state["open_event"].set()
                state["close_event"].set()

    async def _handle_socks_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        conn_id = 0
        try:
            host, port = await self._socks_handshake(reader, writer)
            async with self._state_lock:
                conn_id = self._next_conn_id
                self._next_conn_id += 1
                state = {
                    "client_writer": writer,
                    "open_event": asyncio.Event(),
                    "close_event": asyncio.Event(),
                    "open_error": None,
                }
                self._conn_state[conn_id] = state

            await self._relay_send(OPEN, conn_id, encode_target(host, port))
            await asyncio.wait_for(state["open_event"].wait(), timeout=15)
            if state["open_error"]:
                raise ProtocolError(str(state["open_error"]))

            self._send_socks_success(writer)
            await self._pipe_client_to_relay(conn_id, reader, state["close_event"])
        except Exception as exc:
            LOGGER.debug("SOCKS client %s failed: %s", peer_name(writer), exc)
            self._send_socks_fail(writer, 0x01)
        finally:
            if conn_id:
                self._conn_state.pop(conn_id, None)
                with contextlib.suppress(Exception):
                    await self._relay_send(CLOSE, conn_id)
            if not writer.is_closing():
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()

    async def _pipe_client_to_relay(
        self,
        conn_id: int,
        reader: asyncio.StreamReader,
        close_event: asyncio.Event,
    ) -> None:
        while not close_event.is_set():
            read_task = asyncio.create_task(reader.read(65536))
            close_task = asyncio.create_task(close_event.wait())
            done, pending = await asyncio.wait(
                {read_task, close_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for pending_task in pending:
                pending_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pending_task
            if close_task in done and close_event.is_set():
                if not read_task.done():
                    read_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await read_task
                break
            data = read_task.result()
            if not data:
                break
            await self._relay_send(DATA, conn_id, data)

    async def _socks_handshake(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> Tuple[str, int]:
        header = await reader.readexactly(2)
        ver, nmethods = header[0], header[1]
        if ver != 5:
            raise ProtocolError("SOCKS version must be 5")
        _ = await reader.readexactly(nmethods)
        writer.write(b"\x05\x00")
        await writer.drain()

        req = await reader.readexactly(4)
        ver, cmd, _rsv, atyp = req
        if ver != 5 or cmd != 1:
            raise ProtocolError("only SOCKS5 CONNECT is supported")
        if atyp == 1:
            addr = await reader.readexactly(4)
            host = ".".join(str(part) for part in addr)
        elif atyp == 3:
            name_len = (await reader.readexactly(1))[0]
            host = (await reader.readexactly(name_len)).decode("utf-8", errors="ignore")
        elif atyp == 4:
            addr = await reader.readexactly(16)
            chunks = [f"{addr[i] << 8 | addr[i+1]:x}" for i in range(0, 16, 2)]
            host = ":".join(chunks)
        else:
            raise ProtocolError("invalid ATYP")
        port = int.from_bytes(await reader.readexactly(2), byteorder="big", signed=False)
        return host, port

    def _send_socks_success(self, writer: asyncio.StreamWriter) -> None:
        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")

    def _send_socks_fail(self, writer: asyncio.StreamWriter, rep_code: int) -> None:
        if writer.is_closing():
            return
        writer.write(bytes([0x05, rep_code, 0x00, 0x01, 0, 0, 0, 0, 0, 0]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="StarBridge MVP - personal remote exit node prototype"
    )
    parser.add_argument("--verbose", action="store_true", help="enable debug logs")
    sub = parser.add_subparsers(dest="mode", required=True)

    relay = sub.add_parser("relay", help="run relay server on a public host")
    relay.add_argument("--host", default="0.0.0.0")
    relay.add_argument("--port", type=int, default=9443)
    relay.add_argument("--token", required=True, help="shared secret token")
    relay.add_argument("--certfile", help="TLS certificate path (optional)")
    relay.add_argument("--keyfile", help="TLS private key path (optional)")

    agent = sub.add_parser("home-agent", help="run on home Windows machine")
    agent.add_argument("--relay-host", required=True)
    agent.add_argument("--relay-port", type=int, default=9443)
    agent.add_argument("--token", required=True)
    agent.add_argument("--no-tls", action="store_true")
    agent.add_argument("--ca-file", help="custom CA file for relay certificate")
    agent.add_argument("--retry-seconds", type=int, default=5)
    agent.add_argument(
        "--relay-bind-host",
        help="local source IP for connecting to relay (e.g., SIM adapter IP)",
    )
    agent.add_argument(
        "--egress-bind-host",
        help="local source IP for outbound target traffic (e.g., Starlink adapter IP)",
    )

    socks = sub.add_parser("socks-client", help="local SOCKS5 endpoint using relay")
    socks.add_argument("--relay-host", required=True)
    socks.add_argument("--relay-port", type=int, default=9443)
    socks.add_argument("--token", required=True)
    socks.add_argument("--listen-host", default="127.0.0.1")
    socks.add_argument("--listen-port", type=int, default=1080)
    socks.add_argument("--no-tls", action="store_true")
    socks.add_argument("--ca-file", help="custom CA file for relay certificate")
    socks.add_argument(
        "--relay-bind-host",
        help="local source IP for connecting to relay",
    )

    gen = sub.add_parser(
        "generate-configs",
        help="generate multiple StarBridge profile JSON files",
    )
    gen.add_argument("--relay-host", required=True)
    gen.add_argument("--count", type=int, default=20)
    gen.add_argument("--start-port", type=int, default=9443)
    gen.add_argument("--listen-host", default="127.0.0.1")
    gen.add_argument("--listen-port", type=int, default=1080)
    gen.add_argument("--prefix", default="sb")
    gen.add_argument("--token-bytes", type=int, default=18)
    gen.add_argument("--no-tls", action="store_true")
    gen.add_argument("--ca-file", help="CA file path to include in generated profiles")
    gen.add_argument("--relay-bind-host", help="relay bind IP to include in profiles")
    gen.add_argument("--egress-bind-host", help="egress bind IP to include in profiles")
    gen.add_argument("--output-dir", default="generated-configs")
    return parser


async def async_main(args: argparse.Namespace) -> None:
    if args.mode == "relay":
        relay = RelayServer(
            host=args.host,
            port=args.port,
            token=args.token,
            certfile=args.certfile,
            keyfile=args.keyfile,
        )
        await relay.run()
        return

    if args.mode == "home-agent":
        agent = HomeAgent(
            relay_host=args.relay_host,
            relay_port=args.relay_port,
            token=args.token,
            use_tls=not args.no_tls,
            ca_file=args.ca_file,
            retry_seconds=args.retry_seconds,
            relay_bind_host=args.relay_bind_host,
            egress_bind_host=args.egress_bind_host,
        )
        await agent.run_forever()
        return

    if args.mode == "socks-client":
        gateway = SocksClientGateway(
            relay_host=args.relay_host,
            relay_port=args.relay_port,
            token=args.token,
            listen_host=args.listen_host,
            listen_port=args.listen_port,
            use_tls=not args.no_tls,
            ca_file=args.ca_file,
            relay_bind_host=args.relay_bind_host,
        )
        await gateway.run()
        return

    if args.mode == "generate-configs":
        generate_configs(args)
        return

    raise ValueError(f"unknown mode: {args.mode}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        LOGGER.info("stopped")


if __name__ == "__main__":
    main()
