"""Chess 3 networking: lobby-code TCP multiplayer.

Protocol: newline-delimited JSON (UTF-8), one object per line.
The host runs HostServer in-process and plays as pid 0 (no socket);
joiners use NetClient. Lobby codes encode IPv4+port in Crockford base32.
NO pygame imports here.

v2: match settings (board shape, timers, troop swaps) validated + merged by
HostServer.set_settings and broadcast in every "lobby" message; a server-side
timer thread enforces the move/total clocks; "start" and "state" messages
carry a "clock" payload.

v3: PresenceService — LAN/VPN peer discovery over UDP broadcast beacons on
PRESENCE_PORT plus Steam-style invites carrying the lobby code; protocol
version bumped to 3 (new piece types cross the wire; old clients kicked with
the same message as before).

v4: dead players curse tiles — a {"t":"grave","cell":[q,r]} message feeds
engine.apply_grave (HostServer.submit_host_grave for the host,
NetClient.send_grave for joiners); GitHub release-check helpers
(get_latest_release / download_file) for the in-app updater; protocol
version bumped to 4 (Skeletons + graveyards cross the wire).
"""
import json
import math
import os
import queue
import random
import re
import select
import socket
import threading
import time
import urllib.request
from urllib.parse import urljoin

import engine

DEFAULT_PORT = 47733
PROTOCOL_VERSION = 4
MAX_PLAYERS = 6
MIN_PLAYERS = 2
_MAX_LINE = 64 * 1024

# -- match settings (v2) -----------------------------------------------------

DEFAULT_SETTINGS = {"shape": "hexagon", "move_secs": 0, "total_mins": 0,
                    "swaps": {}}
MOVE_SECS_CHOICES = (0, 15, 30, 60, 120)
TOTAL_MINS_CHOICES = (0, 5, 10, 20, 30)

_VERSION_MISMATCH = ("version mismatch — ask the host for the new "
                     "Chess3.exe")

# Timer-thread poll interval in seconds. Module-level so tests can shrink it
# (the loop re-reads it every tick).
_TICK = 0.5


def _copy_settings(settings):
    out = dict(settings)
    out["swaps"] = dict(settings.get("swaps", {}))
    return out


def _validate_swaps(swaps):
    """Return an error string for a bad swaps mapping, else None."""
    if not isinstance(swaps, dict):
        return "swaps must be a mapping"
    used = set()
    for slot, rep in swaps.items():
        if slot not in engine.SWAPPABLE_TYPES:
            return "troop %r cannot be swapped out" % (slot,)
        if rep not in engine.SWAP_TROOPS:
            return "bad replacement troop %r" % (rep,)
        if rep in used:
            return "replacement %r used more than once" % (rep,)
        used.add(rep)
    return None

# ---------------------------------------------------------------------------
# Lobby codes
# ---------------------------------------------------------------------------

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford: no I, L, O, U
_B32_INDEX = {c: i for i, c in enumerate(_B32)}
_CONFUSABLES = {"I": "1", "L": "1", "O": "0"}
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def encode_code(ip, port):
    """Encode IPv4 + port (6 bytes) as a 10-char code like 'XXXXX-XXXXX'."""
    parts = ip.split(".")
    if len(parts) != 4:
        raise ValueError("not an IPv4 address: %r" % ip)
    val = 0
    for p in parts:
        b = int(p)
        if not 0 <= b <= 255:
            raise ValueError("bad IPv4 octet: %r" % p)
        val = (val << 8) | b
    if not 0 < int(port) <= 65535:
        raise ValueError("bad port: %r" % port)
    val = (val << 16) | int(port)
    chars = []
    for _ in range(10):
        chars.append(_B32[val & 31])
        val >>= 5
    s = "".join(reversed(chars))
    return s[:5] + "-" + s[5:]


def decode_code(text):
    """Decode a lobby code (tolerant) or a raw 'ip:port' / bare 'ip' string.

    Returns (ip, port). Raises ValueError if the input is unusable.
    """
    if not isinstance(text, str):
        raise ValueError("code must be a string")
    raw = text.strip()
    if not raw:
        raise ValueError("empty code")

    def valid_ip(s):
        # normalizes octets (kills leading zeros) and range-checks 0-255
        if not _IP_RE.match(s):
            return None
        octets = [int(o) for o in s.split(".")]
        if any(o > 255 for o in octets):
            return None
        return ".".join(str(o) for o in octets)

    # Raw ip:port or bare ip passthrough.
    bare = raw.replace(" ", "")
    if "." in bare:
        host, sep, ptxt = bare.rpartition(":")
        if not sep:
            host, ptxt = bare, None
        ip = valid_ip(host)
        if ip is None:
            raise ValueError("bad ip: %r" % raw)
        if ptxt is None:
            return ip, DEFAULT_PORT
        try:
            port = int(ptxt)
        except ValueError:
            raise ValueError("bad port in %r" % raw)
        if not 0 < port <= 65535:
            raise ValueError("bad port in %r" % raw)
        return ip, port
    # Lobby code.
    s = raw.upper()
    s = "".join(_CONFUSABLES.get(c, c) for c in s if c not in " -\t")
    if len(s) != 10 or any(c not in _B32_INDEX for c in s):
        raise ValueError("not a lobby code: %r" % raw)
    val = 0
    for c in s:
        val = (val << 5) | _B32_INDEX[c]
    port = val & 0xFFFF
    val >>= 16
    octets = [(val >> shift) & 0xFF for shift in (24, 16, 8, 0)]
    if port == 0:
        raise ValueError("code decodes to port 0")
    return ".".join(str(o) for o in octets), port


def get_lan_ip():
    """This machine's LAN IP (UDP-connect trick); falls back to 127.0.0.1."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def get_public_ip(timeout=3.0):
    """Public IPv4 via api.ipify.org, or None on any failure."""
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=timeout) as r:
            ip = r.read(64).decode("ascii", "replace").strip()
        return ip if _IP_RE.match(ip) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# UPnP (best effort, exception-proof)
# ---------------------------------------------------------------------------

_upnp_control = None  # (control_url, service_type) cached after discovery


def _upnp_discover(timeout):
    """SSDP-discover the gateway; returns (control_url, service_type) or None."""
    global _upnp_control
    if _upnp_control:
        return _upnp_control
    msg = ("M-SEARCH * HTTP/1.1\r\n"
           "HOST: 239.255.255.250:1900\r\n"
           'MAN: "ssdp:discover"\r\n'
           "MX: 2\r\n"
           "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n"
           "\r\n").encode()
    locations = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        s.sendto(msg, ("239.255.255.250", 1900))
        while True:
            try:
                data, _addr = s.recvfrom(4096)
            except socket.timeout:
                break
            for line in data.decode("utf-8", "replace").splitlines():
                if line.lower().startswith("location:"):
                    locations.append(line.split(":", 1)[1].strip())
    finally:
        s.close()
    import xml.etree.ElementTree as ET
    for loc in locations:
        try:
            with urllib.request.urlopen(loc, timeout=timeout) as r:
                tree = ET.fromstring(r.read(256 * 1024))
            base = loc
            for svc in tree.iter():
                if not svc.tag.endswith("service"):
                    continue
                stype = ctrl = None
                for child in svc:
                    if child.tag.endswith("serviceType"):
                        stype = (child.text or "").strip()
                    elif child.tag.endswith("controlURL"):
                        ctrl = (child.text or "").strip()
                if stype and ctrl and ("WANIPConnection" in stype
                                       or "WANPPPConnection" in stype):
                    _upnp_control = (urljoin(base, ctrl), stype)
                    return _upnp_control
        except Exception:
            continue
    return None


def _upnp_soap(control_url, service_type, action, args_xml, timeout):
    body = ('<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            "<s:Body><u:%s xmlns:u=\"%s\">%s</u:%s></s:Body></s:Envelope>"
            % (action, service_type, args_xml, action)).encode()
    req = urllib.request.Request(
        control_url, data=body,
        headers={"Content-Type": 'text/xml; charset="utf-8"',
                 "SOAPAction": '"%s#%s"' % (service_type, action)})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(64 * 1024).decode("utf-8", "replace")


def upnp_map_port(port, timeout=3.0):
    """Try to AddPortMapping TCP `port` on the gateway. Returns (ok, msg)."""
    try:
        found = _upnp_discover(timeout)
        if not found:
            return False, "no UPnP gateway found"
        control_url, stype = found
        args = ("<NewRemoteHost></NewRemoteHost>"
                "<NewExternalPort>%d</NewExternalPort>"
                "<NewProtocol>TCP</NewProtocol>"
                "<NewInternalPort>%d</NewInternalPort>"
                "<NewInternalClient>%s</NewInternalClient>"
                "<NewEnabled>1</NewEnabled>"
                "<NewPortMappingDescription>Chess3</NewPortMappingDescription>"
                "<NewLeaseDuration>0</NewLeaseDuration>"
                % (port, port, get_lan_ip()))
        status, text = _upnp_soap(control_url, stype, "AddPortMapping", args,
                                  timeout)
        if status == 200 and "Fault" not in text:
            return True, "mapped TCP %d" % port
        return False, "gateway refused mapping (HTTP %s)" % status
    except Exception as e:
        return False, "UPnP failed: %s" % e


def upnp_unmap_port(port, timeout=3.0):
    """Best-effort DeletePortMapping; never raises."""
    try:
        found = _upnp_discover(timeout)
        if not found:
            return
        control_url, stype = found
        args = ("<NewRemoteHost></NewRemoteHost>"
                "<NewExternalPort>%d</NewExternalPort>"
                "<NewProtocol>TCP</NewProtocol>" % port)
        _upnp_soap(control_url, stype, "DeletePortMapping", args, timeout)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Release check (v4) — best effort, exception-proof
# ---------------------------------------------------------------------------

GITHUB_REPO = "CoopNutt/chess3"
# Base URL split out so tests can point it at an unroutable localhost server
# (tests must NEVER hit real GitHub).
GITHUB_API = "https://api.github.com"
_HTTP_HEADERS = {"User-Agent": "Chess3-Updater",   # GitHub requires a UA
                 "Accept": "application/vnd.github+json"}


def _close_quietly(exc):
    """HTTPError carries an open response object; close it so swallowing
    the exception does not leak the socket (ResourceWarning)."""
    try:
        close = getattr(exc, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


def get_latest_release(timeout=4.0):
    """Latest GitHub release as {"tag", "url", "notes"}, or None.

    `url` is the browser_download_url of the first .exe asset. Returns None
    on ANY failure: no network, rate limit, no release yet, no exe asset,
    malformed response. Never raises.
    """
    try:
        api = "%s/repos/%s/releases/latest" % (GITHUB_API, GITHUB_REPO)
        req = urllib.request.Request(api, headers=dict(_HTTP_HEADERS))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read(1024 * 1024).decode("utf-8", "replace"))
        if not isinstance(data, dict):
            return None
        tag = data.get("tag_name")
        if not isinstance(tag, str) or not tag:
            return None
        url = None
        assets = data.get("assets")
        for asset in (assets if isinstance(assets, list) else []):
            if not isinstance(asset, dict):
                continue
            name = asset.get("name")
            dl = asset.get("browser_download_url")
            if (isinstance(name, str) and name.lower().endswith(".exe")
                    and isinstance(dl, str) and dl):
                url = dl
                break
        if url is None:
            return None
        notes = data.get("body")
        return {"tag": tag, "url": url,
                "notes": notes if isinstance(notes, str) else ""}
    except Exception as e:
        _close_quietly(e)
        return None


def download_file(url, dest_path, timeout=30.0):
    """Stream `url` to `dest_path` in chunks. True on success.

    On ANY failure returns False and removes the partial file — including a
    connection dropped mid-download: chunked HTTPResponse.read() reports a
    premature EOF as a plain end-of-stream, so the byte count is checked
    against Content-Length explicitly. Never raises.
    """
    opened = False
    try:
        req = urllib.request.Request(url, headers=dict(_HTTP_HEADERS))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            try:
                expected = int(r.headers.get("Content-Length"))
            except (AttributeError, TypeError, ValueError):
                expected = None
            with open(dest_path, "wb") as f:
                opened = True
                written = 0
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
        if expected is not None and written != expected:
            raise OSError("truncated download (%d of %d bytes)"
                          % (written, expected))
        return True
    except Exception as e:
        _close_quietly(e)
        if opened:   # never delete a pre-existing file we didn't touch
            try:
                os.remove(dest_path)
            except OSError:
                pass
        return False


# ---------------------------------------------------------------------------
# Wire helpers
# ---------------------------------------------------------------------------

def _send_line(sock, obj, lock, deadline=None):
    """Send one JSON line. With `deadline` (seconds), raise OSError instead
    of blocking forever on a peer that stopped reading (a frozen client must
    not stall the host's broadcast loop).

    The deadline is enforced across the WHOLE payload: select() only proves
    a single send() won't wedge, so large payloads are sent chunk by chunk,
    re-checking writability against the remaining time budget each round.
    """
    data = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
    if deadline is None:
        with lock:
            sock.sendall(data)
        return
    # The deadline budget covers LOCK ACQUISITION too: if another thread is
    # wedged sending to this same socket, waiting forever on its lock would
    # defeat the whole point of the deadline.
    end = time.monotonic() + deadline
    if not lock.acquire(timeout=deadline):
        raise OSError("send lock stalled")
    try:
        view = memoryview(data)
        while view:
            left = end - time.monotonic()
            if left <= 0:
                raise OSError("send stalled")
            _, writable, _ = select.select([], [sock], [], left)
            if not writable:
                raise OSError("send stalled")
            sent = sock.send(view[:16384])
            view = view[sent:]
    finally:
        lock.release()


def _read_lines(sock):
    """Yield parsed JSON objects from a socket until EOF/error.

    Raises ValueError on oversized or malformed lines (caller drops peer).
    """
    buf = b""
    while True:
        try:
            chunk = sock.recv(4096)
        except OSError:
            return
        if not chunk:
            return
        buf += chunk
        if len(buf) > _MAX_LINE:
            raise ValueError("line too long")
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            yield json.loads(line.decode("utf-8"))


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class _Remote:
    """One connected joiner."""

    def __init__(self, sock, pid, name):
        self.sock = sock
        self.pid = pid
        self.name = name
        self.send_lock = threading.Lock()


class HostServer:
    """Authoritative game server; the host plays in-process as pid 0."""

    def __init__(self, host_name, port=DEFAULT_PORT):
        self.host_name = host_name or "Host"
        self.port = port
        self.events = queue.Queue()
        self._listener = None
        self._remotes = {}            # pid -> _Remote
        self._names = {0: self.host_name}
        self._join_order = [0]
        self._next_pid = 1
        self._gs = None
        self._phase = "lobby"         # lobby | game
        self._lock = threading.Lock()
        # Serializes message emission so wire/queue order always matches
        # state-generation order (state must never overtake start, etc.).
        # Ordering: acquire _out_lock BEFORE _lock, never the other way.
        self._out_lock = threading.Lock()
        self._closing = False
        # v2 match settings + server-enforced timers (all under _lock).
        self._settings = _copy_settings(DEFAULT_SETTINGS)
        self._move_secs = 0.0         # active move budget (0 = off)
        self._move_started = 0.0      # monotonic time the current turn began
        self._turn_seen = None        # last observed turn_pid (reset detector)
        self._total_deadline = None   # monotonic deadline or None
        self._timer_thread = None

    # -- lifecycle --

    def start(self):
        """Bind and start accepting joiners. Raises OSError if port is busy."""
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("0.0.0.0", self.port))
        ls.listen(8)
        self._listener = ls
        threading.Thread(target=self._accept_loop, daemon=True).start()
        self._push_lobby()

    def close(self):
        with self._lock:
            # under _lock so no registration can slip between the flag and
            # the remotes snapshot (a late joiner would be stranded forever)
            self._closing = True
            remotes = list(self._remotes.values())
        try:
            if self._listener:
                self._listener.close()
        except OSError:
            pass
        for rm in remotes:
            try:
                rm.sock.close()
            except OSError:
                pass

    def player_count(self):
        with self._lock:
            return len(self._join_order)

    # -- lobby / game flow --

    def set_settings(self, partial):
        """Validate + merge match settings (host UI calls this directly).

        Returns (ok, err). On success the merged settings are re-broadcast
        to everyone via a "lobby" message. Accepted keys/values:
          shape       in engine.SHAPE_NAMES
          move_secs   in MOVE_SECS_CHOICES (a positive float is also
                      accepted as an internal/testing escape hatch)
          total_mins  in TOTAL_MINS_CHOICES (same float escape hatch)
          swaps       {default_troop: replacement} per engine swap rules
        The whole partial is rejected atomically if any entry is bad.
        """
        if not isinstance(partial, dict):
            return False, "settings must be a mapping"
        clean = {}
        for key, val in partial.items():
            if key == "shape":
                if val not in engine.SHAPE_NAMES:
                    return False, "unknown shape: %r" % (val,)
                clean[key] = val
            elif key in ("move_secs", "total_mins"):
                choices = (MOVE_SECS_CHOICES if key == "move_secs"
                           else TOTAL_MINS_CHOICES)
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    return False, "bad %s: %r" % (key, val)
                if isinstance(val, int) and val not in choices:
                    return False, ("bad %s: %r (allowed: %s)"
                                   % (key, val,
                                      "/".join(str(c) for c in choices)))
                if isinstance(val, float) and not val > 0:
                    return False, "bad %s: %r" % (key, val)
                clean[key] = val
            elif key == "swaps":
                err = _validate_swaps(val)
                if err is not None:
                    return False, err
                clean[key] = dict(val)
            else:
                return False, "unknown setting %r" % (key,)
        with self._lock:
            if self._phase != "lobby":
                return False, "Game already started"
            self._settings.update(clean)
        self._push_lobby()
        return True, None

    def get_settings(self):
        with self._lock:
            return _copy_settings(self._settings)

    def start_game(self):
        """Host presses START. Returns (ok, err)."""
        start_timer = False
        with self._out_lock:
            with self._lock:
                if self._phase != "lobby":
                    return False, "Game already started"
                if len(self._join_order) < MIN_PLAYERS:
                    return False, "Need at least %d players" % MIN_PLAYERS
                shape = self._settings["shape"]
                limit = engine.SHAPE_MAX_PLAYERS[shape]
                if len(self._join_order) > limit:
                    return False, ("%s maps allow up to %d players"
                                   % (engine.SHAPE_NAMES[shape], limit))
                players = [(pid, self._names[pid])
                           for pid in self._join_order]
                try:
                    self._gs = engine.GameState.new_game(
                        players, shape=shape,
                        swaps=dict(self._settings["swaps"]))
                except ValueError as e:   # settings were validated; belt+braces
                    return False, str(e)
                self._phase = "game"
                now = time.monotonic()
                self._move_secs = float(self._settings["move_secs"])
                self._turn_seen = self._gs.turn_pid
                self._move_started = now
                total = float(self._settings["total_mins"]) * 60.0
                self._total_deadline = (now + total) if total > 0 else None
                start_timer = (self._move_secs > 0
                               or self._total_deadline is not None)
                msg = {"t": "start", "state": self._gs.to_dict(),
                       "clock": self._clock()}
            self._emit(msg)
        if start_timer:
            self._timer_thread = threading.Thread(
                target=self._timer_loop, name="chess3-timer", daemon=True)
            self._timer_thread.start()
        return True, None

    def submit_host_move(self, move_dict):
        self._handle_move(0, move_dict)

    def submit_host_grave(self, cell):
        """The (dead) host curses a tile; result arrives on `events`."""
        self._handle_grave(0, cell)

    # -- internals --

    def _accept_loop(self):
        while not self._closing:
            try:
                sock, _addr = self._listener.accept()
            except OSError:
                return
            threading.Thread(target=self._client_session, args=(sock,),
                             daemon=True).start()

    def _client_session(self, sock):
        sock.settimeout(10.0)
        send_lock = threading.Lock()
        pid = None
        try:
            lines = _read_lines(sock)
            hello = next(lines, None)
            if (not isinstance(hello, dict) or hello.get("t") != "hello"
                    or not isinstance(hello.get("name"), str)):
                _send_line(sock, {"t": "kicked", "reason": "bad hello"},
                           send_lock)
                sock.close()
                return
            if hello.get("ver") != PROTOCOL_VERSION:
                _send_line(sock, {"t": "kicked",
                                  "reason": _VERSION_MISMATCH}, send_lock)
                sock.close()
                return
            name = hello["name"].strip()[:16] or "Player"
            with self._lock:
                if self._closing:
                    reason = "host closed the lobby"
                elif self._phase != "lobby":
                    reason = "game already started"
                elif len(self._join_order) >= MAX_PLAYERS:
                    reason = "lobby is full"
                else:
                    reason = None
                if reason is None:
                    pid = self._next_pid
                    self._next_pid += 1
                    rm = _Remote(sock, pid, name)
                    rm.send_lock = send_lock
                    self._remotes[pid] = rm
                    self._names[pid] = name
                    self._join_order.append(pid)
            if reason is not None:
                _send_line(sock, {"t": "kicked", "reason": reason}, send_lock)
                sock.close()
                return
            _send_line(sock, {"t": "welcome", "pid": pid}, send_lock)
            self._push_lobby()
            sock.settimeout(None)
            for msg in lines:
                if not isinstance(msg, dict):
                    continue
                t = msg.get("t")
                if t == "move":
                    self._handle_move(pid, msg.get("move"))
                elif t == "grave":
                    self._handle_grave(pid, msg.get("cell"))
                elif t == "leave":
                    break
        except (ValueError, OSError, json.JSONDecodeError):
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass
            if pid is not None:
                self._drop_player(pid)

    def _handle_move(self, pid, move_dict):
        # NB: never send from inside _lock — _send_error/_emit can block on
        # slow sockets, and they take locks of their own (non-reentrant).
        gameover = None
        reject = None
        state = last = clock = None
        with self._out_lock:
            with self._lock:
                if self._phase != "game" or self._gs is None:
                    reject = "Game has not started"
                else:
                    try:
                        move = engine.Move.from_dict(move_dict)
                    except ValueError:
                        move = None
                        reject = "Malformed move"
                    if move is not None:
                        ok, err = self._gs.apply_move(pid, move)
                        if not ok:
                            reject = err or "Illegal move"
                        else:
                            self._sync_move_timer()
                            state = self._gs.to_dict()
                            clock = self._clock()
                            last = {"pid": pid, "move": move.to_dict()}
                            if self._gs.winner is not None:
                                gameover = {"t": "gameover",
                                            "winner": self._gs.winner,
                                            "name": self._winner_name()}
            if reject is None:
                self._emit({"t": "state", "state": state, "last_move": last,
                            "clock": clock})
                if gameover:
                    self._emit(gameover)
        if reject is not None:
            self._send_error(pid, reject)

    def _handle_grave(self, pid, cell):
        """A dead player curses one tile (v4). Same locking discipline as
        _handle_move: mutate under _lock, emit under _out_lock only, send
        errors outside both. A grave never ends the game (nobody dies), so
        there is no gameover leg. Malformed `cell` payloads are rejected,
        never raised."""
        reject = None
        state = last = clock = None
        with self._out_lock:
            with self._lock:
                if self._phase != "game" or self._gs is None:
                    reject = "Game has not started"
                else:
                    c = None
                    if isinstance(cell, (list, tuple)) and len(cell) == 2:
                        try:
                            c = (int(cell[0]), int(cell[1]))
                        except (TypeError, ValueError):
                            c = None
                    if c is None:
                        reject = "Malformed cell"
                    else:
                        ok, err = self._gs.apply_grave(pid, c)
                        if not ok:
                            reject = err or "Cannot curse that tile"
                        else:
                            # a curse can strand the player to move with zero
                            # legal moves — skip them so the game can't stall
                            gs = self._gs
                            if (gs.winner is None
                                    and not gs.all_legal_moves(gs.turn_pid)):
                                gs.force_skip(gs.turn_pid)
                            state = gs.to_dict()
                            clock = self._clock()
                            last = {"pid": pid,
                                    "move": {"from": [c[0], c[1]],
                                             "to": [c[0], c[1]],
                                             "kind": "grave"}}
            if reject is None:
                self._emit({"t": "state", "state": state, "last_move": last,
                            "clock": clock})
        if reject is not None:
            self._send_error(pid, reject)

    def _winner_name(self):
        if self._gs.winner in (None, -1):
            return "draw"
        return self._names.get(self._gs.winner, "???")

    def _drop_player(self, pid):
        gameover = None
        state = clock = None
        with self._out_lock:
            with self._lock:
                if self._closing:
                    return
                self._remotes.pop(pid, None)
                if pid not in self._join_order:
                    return
                if self._phase == "lobby":
                    self._join_order.remove(pid)
                    self._names.pop(pid, None)
                    lobby_changed = True
                else:
                    lobby_changed = False
                    if self._gs is not None and self._gs.winner is None:
                        self._gs.eliminate(pid, "disconnected")
                        self._sync_move_timer()
                        state = self._gs.to_dict()
                        clock = self._clock()
                        if self._gs.winner is not None:
                            gameover = {"t": "gameover",
                                        "winner": self._gs.winner,
                                        "name": self._winner_name()}
            if state is not None:
                self._emit({"t": "state", "state": state, "last_move": None,
                            "clock": clock})
            if gameover:
                self._emit(gameover)
        if lobby_changed:
            self._push_lobby()

    def _push_lobby(self):
        with self._out_lock:
            with self._lock:
                players = [{"pid": pid, "name": self._names[pid], "color": i}
                           for i, pid in enumerate(self._join_order)]
                settings = _copy_settings(self._settings)
            self._emit({"t": "lobby", "players": players,
                        "settings": settings,
                        "max": MAX_PLAYERS, "min": MIN_PLAYERS})

    # -- timers (v2) --

    def _clock(self):
        """The {"move_left","total_left"} payload. Call with _lock held."""
        move_left = total_left = None
        if self._phase == "game":
            now = time.monotonic()
            if self._move_secs > 0:
                left = self._move_started + self._move_secs - now
                move_left = max(0, int(math.ceil(left)))
            if self._total_deadline is not None:
                total_left = max(0, int(math.ceil(self._total_deadline - now)))
        return {"move_left": move_left, "total_left": total_left}

    def _sync_move_timer(self):
        """Restart the move budget if turn_pid changed. Call with _lock held."""
        if self._gs is not None and self._gs.turn_pid != self._turn_seen:
            self._turn_seen = self._gs.turn_pid
            self._move_started = time.monotonic()

    def _timer_loop(self):
        """Server-side clock enforcement (daemon thread, one per game).

        Locking discipline (this file deadlocked before — do not "simplify"):
        mutate the GameState only under _lock, emit ONLY under _out_lock via
        _emit, acquire _out_lock BEFORE _lock and NEVER the other way around,
        and never hold _lock across a send. Exits when the server closes or
        the game ends.
        """
        while True:
            time.sleep(_TICK)   # module-level so tests can shrink it
            state = clock = gameover = None
            with self._out_lock:
                with self._lock:
                    if (self._closing or self._phase != "game"
                            or self._gs is None or self._gs.winner is not None):
                        return
                    gs = self._gs
                    now = time.monotonic()
                    self._sync_move_timer()   # catch turn flips between ticks
                    if (self._move_secs > 0
                            and now - self._move_started >= self._move_secs):
                        gs.force_skip(gs.turn_pid)
                        # restart the budget even if the turn wrapped back to
                        # the same pid (everyone else moveless)
                        self._turn_seen = gs.turn_pid
                        self._move_started = time.monotonic()
                        state = gs.to_dict()
                    if (self._total_deadline is not None
                            and now >= self._total_deadline):
                        gs.end_by_time()
                        state = gs.to_dict()
                    if state is not None:
                        clock = self._clock()
                        if gs.winner is not None:
                            gameover = {"t": "gameover", "winner": gs.winner,
                                        "name": self._winner_name()}
                if state is not None:
                    self._emit({"t": "state", "state": state,
                                "last_move": None, "clock": clock})
                if gameover:
                    self._emit(gameover)

    def _emit(self, msg):
        """Deliver one message to the host queue + every remote, in order.
        MUST be called with _out_lock held and _lock NOT held."""
        self.events.put(msg)
        with self._lock:
            remotes = list(self._remotes.values())
        for rm in remotes:
            try:
                _send_line(rm.sock, msg, rm.send_lock, deadline=6.0)
            except (OSError, ValueError):
                # Stalled or dead client (ValueError = select on a socket
                # that just closed): closing the socket makes its session
                # thread run the normal drop/eliminate path.
                try:
                    rm.sock.close()
                except OSError:
                    pass

    def _send_error(self, pid, text):
        msg = {"t": "error", "msg": text}
        if pid == 0:
            self.events.put(msg)
            return
        with self._lock:
            rm = self._remotes.get(pid)
        if rm is not None:
            try:
                _send_line(rm.sock, msg, rm.send_lock, deadline=6.0)
            except (OSError, ValueError):
                try:
                    rm.sock.close()
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class NetClient:
    """Joiner-side connection; server messages arrive on `events`."""

    def __init__(self):
        self.pid = None
        self.events = queue.Queue()
        self._sock = None
        self._lines = None
        self._send_lock = threading.Lock()
        self._closing = False

    def connect(self, ip, port, name, timeout=6.0):
        """Connect + handshake. Raises OSError/ConnectionError on failure."""
        sock = socket.create_connection((ip, port), timeout=timeout)
        sock.settimeout(timeout)
        self._sock = sock
        _send_line(sock, {"t": "hello", "name": name,
                          "ver": PROTOCOL_VERSION}, self._send_lock)
        # ONE generator for the connection's whole life: its internal buffer
        # may already hold bytes that arrived right behind the welcome line
        # (lobby/start broadcasts), so _reader must keep consuming THIS
        # generator — a fresh one would silently drop those messages.
        self._lines = _read_lines(sock)
        pending = []
        try:
            for msg in self._lines:
                if not isinstance(msg, dict):
                    continue
                t = msg.get("t")
                if t == "welcome":
                    self.pid = msg.get("pid")
                    break
                if t == "kicked":
                    sock.close()
                    raise ConnectionError(msg.get("reason", "rejected"))
                pending.append(msg)
        except (ValueError, json.JSONDecodeError):
            sock.close()
            raise ConnectionError("garbled handshake")
        if self.pid is None:
            sock.close()
            raise ConnectionError("host did not answer")
        for msg in pending:
            self.events.put(msg)
        sock.settimeout(None)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            for msg in self._lines:
                if isinstance(msg, dict):
                    self.events.put(msg)
        except (ValueError, json.JSONDecodeError):
            pass
        finally:
            if not self._closing:
                self.events.put({"t": "disconnected"})

    def send_move(self, move_dict):
        try:
            _send_line(self._sock, {"t": "move", "move": move_dict},
                       self._send_lock)
        except OSError:
            pass

    def send_grave(self, cell):
        """Curse a tile (dead players only, v4): cell = (q, r).

        Sent as-is; the server validates and answers with state or error.
        """
        cell = list(cell) if isinstance(cell, tuple) else cell
        try:
            _send_line(self._sock, {"t": "grave", "cell": cell},
                       self._send_lock)
        except OSError:
            pass

    def close(self):
        self._closing = True
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Presence & invites (v3) — LAN/VPN only
# ---------------------------------------------------------------------------

PRESENCE_PORT = 47734
PRESENCE_TTL = 15.0        # seconds until a silent peer expires

# Beacon interval in seconds. Module-level so tests can shrink it (the beacon
# loop re-reads it every cycle).
_PRESENCE_BEACON = 4.0


class PresenceService:
    """LAN presence + invites over UDP broadcast.

    Every ~4s a beacon `{"t":"presence","name",...,"iid",...,"hosting":bool}`
    is broadcast to 255.255.255.255:port and the directed broadcast address;
    the same socket listens for peers' beacons and for unicast invites.
    Peers are keyed by `iid` (random per instance) which filters our own
    broadcast echo; entries expire after PRESENCE_TTL seconds.

    Totally exception-proof: beacons never raise even with no network, and if
    the port cannot bind the service degrades to an inert no-op — start()
    does not raise, peers() == [], invite() == False, close() is safe.

    Test hook (Windows loopback broadcast is unreliable): addresses passed
    via `_peers_hint` or `add_peer_addr()` receive every beacon by unicast,
    so two instances on different loopback ports can discover each other.
    """

    def __init__(self, my_name, port=PRESENCE_PORT, _peers_hint=None):
        self.port = port
        self.events = queue.Queue()   # {"t":"invite","from":str,"code":str}
        self._name = self._clean_name(my_name)
        self._iid = "%016x" % random.getrandbits(64)
        self._host_code = None
        self._sock = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._peers = {}        # iid -> {"name","addr","hosting","last_seen"}
        self._extra_addrs = []  # unicast beacon targets (test hook)
        self._threads = []
        self._started = False
        for addr in (_peers_hint or []):
            self.add_peer_addr(addr)

    @staticmethod
    def _clean_name(name):
        try:
            return str(name or "Player").strip()[:16] or "Player"
        except Exception:
            return "Player"

    # -- lifecycle --

    def start(self):
        """Bind the UDP socket and start the beacon + receiver threads.

        NEVER raises: on any bind/setup failure the service goes inert.
        """
        if self._started:
            return
        self._started = True
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", self.port))
        except Exception:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            self._sock = None
            return
        # Windows quirk: a sendto that draws an ICMP port-unreachable makes
        # the NEXT recvfrom raise ConnectionResetError. Turn that off where
        # supported (SIO_UDP_CONNRESET); the recv loop tolerates it anyway.
        try:
            sock.ioctl(0x9800000C, b"\x00\x00\x00\x00")
        except (AttributeError, OSError, ValueError):
            pass
        self._sock = sock
        for target, tag in ((self._recv_loop, "recv"),
                            (self._beacon_loop, "beacon")):
            t = threading.Thread(target=target, daemon=True,
                                 name="chess3-presence-" + tag)
            t.start()
            self._threads.append(t)

    def close(self):
        """Stop both threads promptly. Never raises; safe to call twice."""
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(2.0)
        with self._lock:
            self._peers.clear()

    # -- public API --

    def set_name(self, name):
        with self._lock:
            self._name = self._clean_name(name)

    def set_host_code(self, code):
        """Advertise `code` while hosting; None = stopped hosting."""
        with self._lock:
            self._host_code = code if (isinstance(code, str) and code) else None
        # Push the new hosting flag out promptly (best effort).
        if self._sock is not None and not self._stop.is_set():
            try:
                self._send_beacon()
            except Exception:
                pass

    def add_peer_addr(self, addr):
        """Beacons are ALSO unicast to `addr` = (ip, port). Test hook for
        environments where loopback broadcast does not deliver."""
        try:
            addr = (str(addr[0]), int(addr[1]))
        except Exception:
            return
        with self._lock:
            if addr not in self._extra_addrs:
                self._extra_addrs.append(addr)

    def peers(self):
        """Fresh (< PRESENCE_TTL) peers, expired entries pruned.

        Returns [{"name", "addr", "hosting", "last_seen"}] where last_seen
        is seconds since the peer's most recent beacon.
        """
        now = time.monotonic()
        out = []
        with self._lock:
            for iid in list(self._peers):
                entry = self._peers[iid]
                age = now - entry["last_seen"]
                if age >= PRESENCE_TTL:
                    del self._peers[iid]
                    continue
                out.append({"name": entry["name"], "addr": entry["addr"],
                            "hosting": entry["hosting"], "last_seen": age})
        return out

    def invite(self, peer_name):
        """Unicast the current host code to `peer_name`.

        False if not hosting (no host code set), the peer is unknown/stale,
        or the service is inert/closed. Never raises.
        """
        if self._sock is None:
            return False
        now = time.monotonic()
        with self._lock:
            code = self._host_code
            frm = self._name
            peer = None
            for entry in self._peers.values():
                if (entry["name"] == peer_name
                        and now - entry["last_seen"] < PRESENCE_TTL):
                    peer = entry
                    break
        if code is None or peer is None:
            return False
        # The advertised code encodes the PHYSICAL-LAN ip — a peer reached
        # over a VPN (Radmin/Hamachi) can't connect to that. Re-encode the
        # code with OUR ip on the route to this specific peer.
        send_code = code
        try:
            _ip, game_port = decode_code(code)
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.connect((peer["addr"][0], self.port))
                route_ip = probe.getsockname()[0]
            finally:
                probe.close()
            if _IP_RE.match(route_ip) and not route_ip.startswith("127."):
                send_code = encode_code(route_ip, game_port)
        except Exception:
            send_code = code
        try:
            data = json.dumps({"t": "invite", "from": frm, "code": send_code},
                              separators=(",", ":")).encode("utf-8")
            self._sock.sendto(data, tuple(peer["addr"]))
        except Exception:
            return False
        return True

    # -- internals --

    def _beacon_loop(self):
        while not self._stop.is_set():
            try:
                self._send_beacon()
            except Exception:
                pass   # beacons NEVER raise (no network, closed socket, ...)
            self._stop.wait(_PRESENCE_BEACON)

    def _send_beacon(self):
        with self._lock:
            payload = {"t": "presence", "name": self._name, "iid": self._iid,
                       "hosting": self._host_code is not None}
            extras = list(self._extra_addrs)
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        targets = [("255.255.255.255", self.port)]
        try:
            octets = get_lan_ip().split(".")
            octets[3] = "255"
            directed = ".".join(octets)
            if directed != "255.255.255.255":
                targets.append((directed, self.port))
        except Exception:
            pass
        targets.extend(extras)
        for addr in targets:
            try:
                self._sock.sendto(data, addr)
            except Exception:
                pass

    def _recv_loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(4096)
            except OSError:
                if self._stop.is_set():
                    return
                # Transient (e.g. Windows ConnectionResetError after a
                # beacon hit an unreachable port): keep listening, but
                # don't hot-spin if the socket is genuinely broken.
                self._stop.wait(0.05)
                continue
            except Exception:
                return
            try:
                self._handle_datagram(data, addr)
            except Exception:
                pass   # malformed datagrams never kill the thread

    def _handle_datagram(self, data, addr):
        msg = json.loads(data.decode("utf-8"))
        if not isinstance(msg, dict):
            return
        t = msg.get("t")
        if t == "presence":
            iid = msg.get("iid")
            name = msg.get("name")
            if (not isinstance(iid, str) or not iid or iid == self._iid
                    or not isinstance(name, str)):
                return
            entry = {"name": self._clean_name(name),
                     "addr": (addr[0], addr[1]),
                     "hosting": bool(msg.get("hosting")),
                     "last_seen": time.monotonic()}
            with self._lock:
                self._peers[iid] = entry
        elif t == "invite":
            frm = msg.get("from")
            code = msg.get("code")
            if isinstance(frm, str) and isinstance(code, str) and code:
                self.events.put({"t": "invite",
                                 "from": self._clean_name(frm),
                                 "code": code})
