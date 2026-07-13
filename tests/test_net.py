"""Networking tests: lobby codes + a real multi-client game over localhost."""
import contextlib
import json
import os
import queue
import random
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine
import net


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def drain_last(q, mtype):
    """Pop everything already queued; return the LAST message of `mtype`."""
    found = None
    while True:
        try:
            msg = q.get_nowait()
        except queue.Empty:
            return found
        if msg.get("t") == mtype:
            found = msg


def raw_hello(port, hello):
    """Open a raw socket, send one hello line, return the first reply."""
    s = socket.create_connection(("127.0.0.1", port), timeout=5.0)
    try:
        s.settimeout(5.0)
        s.sendall((json.dumps(hello) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))


def wait_for(q, mtype, timeout=8.0, keep=None):
    """Pop messages until one of type `mtype` arrives; optionally stash the
    rest via keep(msg). Fails the test on timeout."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            msg = q.get(timeout=0.2)
        except queue.Empty:
            continue
        if msg.get("t") == mtype:
            return msg
        if keep:
            keep(msg)
    raise AssertionError("timed out waiting for %r" % mtype)


class TestLobbyCodes(unittest.TestCase):
    def test_roundtrip(self):
        rng = random.Random(9)
        for _ in range(200):
            ip = ".".join(str(rng.randrange(256)) for _ in range(4))
            port = rng.randrange(1, 65536)
            code = net.encode_code(ip, port)
            self.assertRegex(code, r"^[0-9A-Z]{5}-[0-9A-Z]{5}$")
            self.assertEqual(net.decode_code(code), (ip, port))

    def test_tolerant_decode(self):
        code = net.encode_code("192.168.1.42", 47733)
        sloppy = code.replace("-", " ").lower()
        self.assertEqual(net.decode_code(sloppy), ("192.168.1.42", 47733))
        # confusables: only meaningful if the code contains 1 or 0
        code2 = net.encode_code("10.0.0.1", 47733)
        swapped = code2.replace("1", "I").replace("0", "O")
        self.assertEqual(net.decode_code(swapped), ("10.0.0.1", 47733))

    def test_ip_passthrough(self):
        self.assertEqual(net.decode_code("192.168.0.7:5000"),
                         ("192.168.0.7", 5000))
        self.assertEqual(net.decode_code("192.168.0.7"),
                         ("192.168.0.7", net.DEFAULT_PORT))

    def test_garbage_raises(self):
        for bad in ("", "hello there!", "1.2.3:99", "1.2.3.4:0",
                    "ZZZZZ-ZZZZZ-ZZZZZ", "12345", "999.168.0.1",
                    "256.1.1.1:5000", "1.2.3.4:99999"):
            with self.assertRaises(ValueError, msg=bad):
                net.decode_code(bad)

    def test_leading_zero_octets_normalized(self):
        self.assertEqual(net.decode_code("010.0.0.1"),
                         ("10.0.0.1", net.DEFAULT_PORT))


class TestNetworkedGame(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.server = net.HostServer("Host", self.port)
        self.server.start()
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.server.close()
        time.sleep(0.1)

    def join(self, name):
        c = net.NetClient()
        c.connect("127.0.0.1", self.port, name, timeout=5.0)
        self.clients.append(c)
        return c

    def test_full_game_flow(self):
        # --- lobby ---
        ok, err = self.server.start_game()
        self.assertFalse(ok)  # host alone: below minimum

        names = ["Ann", "Bob", "Cid"]
        for nm in names:
            self.join(nm)
        end = time.time() + 8
        lob = None
        while time.time() < end:  # lobby broadcasts trail the welcomes
            lob = wait_for(self.server.events, "lobby")
            if len(lob["players"]) == 4:
                break
        self.assertEqual(len(lob["players"]), 4)

        ok, err = self.server.start_game()
        self.assertTrue(ok, err)
        states = {}   # participant idx -> latest state dict (0 = host)
        start_host = wait_for(self.server.events, "start")
        states[0] = start_host["state"]
        for i, c in enumerate(self.clients):
            states[i + 1] = wait_for(c.events, "start")["state"]

        # --- joining after start is refused ---
        late = net.NetClient()
        with self.assertRaises((ConnectionError, OSError)):
            late.connect("127.0.0.1", self.port, "Late", timeout=5.0)

        # --- wrong-turn move is rejected with an error ---
        gs0 = engine.GameState.from_dict(states[0])
        not_turn = [c for c in self.clients if c.pid != gs0.turn_pid][0]
        their_cell = next(c for c, pc in
                          engine.GameState.from_dict(states[0]).board.items()
                          if pc.owner == not_turn.pid and pc.type == "P")
        bogus = engine.Move(their_cell,
                            (their_cell[0], their_cell[1] - 1)).to_dict()
        not_turn.send_move(bogus)
        err_msg = wait_for(not_turn.events, "error")
        self.assertIn("turn", err_msg["msg"].lower())

        # --- random-play a real game through the wire ---
        rng = random.Random(42)
        chan = {0: None}
        for c in self.clients:
            chan[c.pid] = c
        winner_seen = None
        for _ply in range(250):
            gs = engine.GameState.from_dict(states[0])
            if gs.winner is not None:
                break
            mover = gs.turn_pid
            mv = rng.choice(gs.all_legal_moves(mover))
            if mover == 0:
                self.server.submit_host_move(mv.to_dict())
            else:
                chan[mover].send_move(mv.to_dict())
            states[0] = wait_for(self.server.events, "state")["state"]
            for i, c in enumerate(self.clients):
                states[i + 1] = wait_for(c.events, "state")["state"]
            # all participants converge to the identical state dict
            for i in range(1, 4):
                self.assertEqual(states[i], states[0], "client %d diverged" % i)
            if states[0]["winner"] is not None:
                winner_seen = states[0]["winner"]
                break
        if winner_seen is not None:
            go_host = wait_for(self.server.events, "gameover")
            self.assertEqual(go_host["winner"], winner_seen)

    def test_disconnect_mid_game_eliminates(self):
        a = self.join("A")
        b = self.join("B")
        ok, err = self.server.start_game()
        self.assertTrue(ok, err)
        wait_for(self.server.events, "start")
        wait_for(a.events, "start")
        wait_for(b.events, "start")

        a_pid = a.pid
        a.close()   # rage-quit
        sd = wait_for(b.events, "state", timeout=8.0)["state"]
        dead = next(p for p in sd["players"] if p["pid"] == a_pid)
        self.assertFalse(dead["alive"])
        self.assertFalse(any(row[3] == a_pid for row in sd["board"]))
        self.assertIsNone(sd["winner"])  # host + B still playing

    def test_lobby_full_kicks_seventh(self):
        for i in range(5):
            self.join("P%d" % i)   # host + 5 = 6 players: full
        extra = net.NetClient()
        with self.assertRaises((ConnectionError, OSError)):
            extra.connect("127.0.0.1", self.port, "Seventh", timeout=5.0)

    def test_lobby_leave_updates(self):
        a = self.join("A")
        self.join("B")
        a.close()
        end = time.time() + 5
        latest = None
        while time.time() < end:
            try:
                msg = self.server.events.get(timeout=0.2)
            except queue.Empty:
                continue
            if msg.get("t") == "lobby":
                latest = msg
                if len(latest["players"]) == 2:
                    break
        self.assertIsNotNone(latest)
        self.assertEqual([p["name"] for p in latest["players"]][:1], ["Host"])
        self.assertEqual(len(latest["players"]), 2)


class TestMatchSettings(unittest.TestCase):
    """v2: HostServer.set_settings validation + lobby broadcast."""

    def setUp(self):
        self.port = free_port()
        self.server = net.HostServer("Host", self.port)
        self.server.start()
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.server.close()
        time.sleep(0.1)

    def join(self, name):
        c = net.NetClient()
        c.connect("127.0.0.1", self.port, name, timeout=5.0)
        self.clients.append(c)
        return c

    def test_defaults_broadcast_in_lobby(self):
        lob = drain_last(self.server.events, "lobby")
        self.assertIsNotNone(lob)
        self.assertEqual(lob["settings"], net.DEFAULT_SETTINGS)

    def test_valid_settings_merge_and_broadcast(self):
        ok, err = self.server.set_settings(
            {"shape": "square", "move_secs": 30, "total_mins": 5,
             "swaps": {"CN": "CT", "GH": "VA", "NE": "GO"}})
        self.assertTrue(ok, err)
        lob = drain_last(self.server.events, "lobby")
        self.assertEqual(lob["settings"]["shape"], "square")
        self.assertEqual(lob["settings"]["move_secs"], 30)
        self.assertEqual(lob["settings"]["total_mins"], 5)
        self.assertEqual(lob["settings"]["swaps"],
                         {"CN": "CT", "GH": "VA", "NE": "GO"})
        # a partial merge keeps the untouched keys
        ok, err = self.server.set_settings({"move_secs": 0})
        self.assertTrue(ok, err)
        self.assertEqual(self.server.get_settings()["shape"], "square")

    def test_joiner_sees_settings(self):
        ok, err = self.server.set_settings({"shape": "octagon",
                                            "total_mins": 10})
        self.assertTrue(ok, err)
        c = self.join("Ann")
        lob = wait_for(c.events, "lobby")
        self.assertEqual(lob["settings"]["shape"], "octagon")
        self.assertEqual(lob["settings"]["total_mins"], 10)

    def test_invalid_settings_rejected_atomically(self):
        bad_partials = [
            {"shape": "pentagon"},
            {"move_secs": 7},
            {"move_secs": True},
            {"move_secs": -1.0},
            {"total_mins": 3},
            {"total_mins": "5"},
            {"swaps": {"K": "CT"}},            # King is not swappable
            {"swaps": {"CN": "XX"}},           # unknown replacement
            {"swaps": {"CN": "CT", "AR": "CT"}},  # CT used twice
            {"swaps": ["CN", "CT"]},           # not a mapping
            {"nonsense": 1},
            "not a dict",
        ]
        for partial in bad_partials:
            # sneak a valid key alongside: the whole partial must be atomic
            if isinstance(partial, dict) and "shape" not in partial:
                partial = dict(partial, shape="square")
            ok, err = self.server.set_settings(partial)
            self.assertFalse(ok, "accepted bad partial %r" % (partial,))
            self.assertTrue(err)
        self.assertEqual(self.server.get_settings(), net.DEFAULT_SETTINGS)

    def test_settings_locked_after_start(self):
        self.join("Ann")
        ok, err = self.server.start_game()
        self.assertTrue(ok, err)
        ok, err = self.server.set_settings({"shape": "square"})
        self.assertFalse(ok)

    def test_start_rejects_too_many_players_for_shape(self):
        for nm in ("Ann", "Bob", "Cid"):
            self.join(nm)   # host + 3 = 4 players
        ok, err = self.server.set_settings({"shape": "triangle"})
        self.assertTrue(ok, err)
        ok, err = self.server.start_game()
        self.assertFalse(ok)
        self.assertIn("Triangle", err)
        self.assertIn("3", err)
        # switching to a roomier shape unblocks the same lobby
        ok, err = self.server.set_settings({"shape": "square"})
        self.assertTrue(ok, err)
        ok, err = self.server.start_game()
        self.assertTrue(ok, err)
        start = wait_for(self.server.events, "start")
        self.assertEqual(start["state"]["shape"], "square")


class TestVersionGate(unittest.TestCase):
    """v4: protocol version 4 enforced at hello (Skeletons + graveyards
    cross the wire, so v3 clients are now kicked too).

    The kick message text is unchanged — old clients must still get a
    readable "grab the new exe" hint.
    """

    def setUp(self):
        self.port = free_port()
        self.server = net.HostServer("Host", self.port)
        self.server.start()

    def tearDown(self):
        self.server.close()
        time.sleep(0.1)

    def test_protocol_version_is_4(self):
        self.assertEqual(net.PROTOCOL_VERSION, 4)

    def test_old_version_kicked(self):
        for old_ver in (1, 2, 3):
            reply = raw_hello(self.port,
                              {"t": "hello", "name": "Old", "ver": old_ver})
            self.assertEqual(reply["t"], "kicked")
            self.assertIn("version mismatch", reply["reason"])

    def test_missing_version_kicked(self):
        reply = raw_hello(self.port, {"t": "hello", "name": "NoVer"})
        self.assertEqual(reply["t"], "kicked")
        self.assertIn("version mismatch", reply["reason"])

    def test_current_version_welcomed(self):
        c = net.NetClient()   # sends ver = PROTOCOL_VERSION = 4
        c.connect("127.0.0.1", self.port, "New", timeout=5.0)
        self.assertEqual(c.pid, 1)
        c.close()


class TestSquareSwapGame(unittest.TestCase):
    """v2: a real localhost game on a square board with a CN->CT swap."""

    def setUp(self):
        self.port = free_port()
        self.server = net.HostServer("Host", self.port)
        self.server.start()
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.server.close()
        time.sleep(0.1)

    def test_square_ct_game_converges(self):
        ok, err = self.server.set_settings({"shape": "square",
                                            "swaps": {"CN": "CT"}})
        self.assertTrue(ok, err)
        c = net.NetClient()
        c.connect("127.0.0.1", self.port, "Bea", timeout=5.0)
        self.clients.append(c)
        end = time.time() + 8
        while time.time() < end:
            if self.server.player_count() == 2:
                break
            time.sleep(0.05)
        ok, err = self.server.start_game()
        self.assertTrue(ok, err)

        start_host = wait_for(self.server.events, "start")
        start_cli = wait_for(c.events, "start")
        # start carries the clock payload (both timers off here)
        self.assertEqual(start_host["clock"],
                         {"move_left": None, "total_left": None})
        states = {0: start_host["state"], 1: start_cli["state"]}
        self.assertEqual(states[0], states[1])
        self.assertEqual(states[0]["shape"], "square")
        types = [row[2] for row in states[0]["board"]]
        self.assertEqual(types.count("CT"), 2)   # one per army
        self.assertNotIn("CN", types)

        rng = random.Random(7)
        for _ply in range(150):
            gs = engine.GameState.from_dict(states[0])
            if gs.winner is not None:
                break
            mv = rng.choice(gs.all_legal_moves(gs.turn_pid))
            if gs.turn_pid == 0:
                self.server.submit_host_move(mv.to_dict())
            else:
                c.send_move(mv.to_dict())
            msg_h = wait_for(self.server.events, "state")
            msg_c = wait_for(c.events, "state")
            self.assertIn("clock", msg_h)
            states[0] = msg_h["state"]
            states[1] = msg_c["state"]
            self.assertEqual(states[0], states[1], "client diverged")


class TestTimers(unittest.TestCase):
    """v2: server-enforced move + total clocks (shrunk tick, float budgets)."""

    def setUp(self):
        self.port = free_port()
        self.server = net.HostServer("Host", self.port)
        self.server.start()
        self.clients = []
        self._old_tick = net._TICK
        net._TICK = 0.05
        self.addCleanup(self._restore_tick)

    def _restore_tick(self):
        net._TICK = self._old_tick

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.server.close()
        t = self.server._timer_thread
        if t is not None:
            t.join(3.0)
            self.assertFalse(t.is_alive(), "timer thread leaked")
        time.sleep(0.1)

    def join(self, name):
        c = net.NetClient()
        c.connect("127.0.0.1", self.port, name, timeout=5.0)
        self.clients.append(c)
        return c

    def test_move_timer_skips_stalled_player(self):
        # 0.5s float budget (internal escape hatch) + 0.05s tick: the skip
        # lands well under a second — never wait the real 15s in tests.
        ok, err = self.server.set_settings({"move_secs": 0.5})
        self.assertTrue(ok, err)
        c = self.join("Slow")
        ok, err = self.server.start_game()
        self.assertTrue(ok, err)
        start = wait_for(self.server.events, "start")
        self.assertIsNotNone(start["clock"]["move_left"])
        self.assertIsNone(start["clock"]["total_left"])
        first_turn = start["state"]["turn_pid"]

        t0 = time.time()
        msg = wait_for(self.server.events, "state", timeout=5.0)
        self.assertLess(time.time() - t0, 3.0, "skip took far too long")
        self.assertIsNone(msg["last_move"])
        sd = msg["state"]
        self.assertNotEqual(sd["turn_pid"], first_turn)
        self.assertIsNone(sd["winner"])
        self.assertTrue(any("ran out of time" in line for line in sd["log"]))
        self.assertIsInstance(msg["clock"]["move_left"], int)
        # the client saw the same skip broadcast
        cmsg = wait_for(c.events, "state", timeout=5.0)
        self.assertIsNone(cmsg["last_move"])
        self.assertEqual(cmsg["state"]["turn_pid"], sd["turn_pid"])

    def test_move_timer_resets_on_move(self):
        ok, err = self.server.set_settings({"move_secs": 1.5})
        self.assertTrue(ok, err)
        self.join("Bea")
        ok, err = self.server.start_game()
        self.assertTrue(ok, err)
        start = wait_for(self.server.events, "start")
        gs = engine.GameState.from_dict(start["state"])
        self.assertEqual(gs.turn_pid, 0)
        # host moves well inside the budget: no skip may precede the move,
        # and the budget must restart for the next player (who then stalls)
        time.sleep(0.7)
        mv = random.Random(3).choice(gs.all_legal_moves(0))
        self.server.submit_host_move(mv.to_dict())
        msg = wait_for(self.server.events, "state", timeout=5.0)
        self.assertIsNotNone(msg["last_move"])   # a real move, not a skip
        skip = wait_for(self.server.events, "state", timeout=5.0)
        self.assertIsNone(skip["last_move"])
        self.assertTrue(any("ran out of time" in line
                            for line in skip["state"]["log"]))

    def test_total_timer_ends_game_most_pieces_wins(self):
        ok, err = self.server.set_settings({"total_mins": 0.02})  # 1.2s
        self.assertTrue(ok, err)
        c = self.join("Bea")
        ok, err = self.server.start_game()
        self.assertTrue(ok, err)
        start = wait_for(self.server.events, "start")
        self.assertIsNotNone(start["clock"]["total_left"])
        wait_for(c.events, "start")
        # tilt the piece count so "most pieces" has a decisive answer:
        # remove one of Bea's pawns straight from the authoritative state
        with self.server._lock:
            cell = next(cl for cl, pc in self.server._gs.board.items()
                        if pc.owner == c.pid and pc.type == "P")
            del self.server._gs.board[cell]
        go_h = wait_for(self.server.events, "gameover", timeout=6.0)
        self.assertEqual(go_h["winner"], 0)
        self.assertEqual(go_h["name"], "Host")
        kept = []
        go_c = wait_for(c.events, "gameover", timeout=6.0, keep=kept.append)
        self.assertEqual(go_c["winner"], 0)
        final_msg = [m for m in kept if m.get("t") == "state"][-1]
        final = final_msg["state"]
        self.assertEqual(final["winner"], 0)
        self.assertTrue(any("Time!" in line for line in final["log"]))
        self.assertIsNone(final_msg["last_move"])
        self.assertEqual(final_msg["clock"]["total_left"], 0)

    def test_total_timer_tie_is_draw(self):
        ok, err = self.server.set_settings({"total_mins": 0.02})  # 1.2s
        self.assertTrue(ok, err)
        c = self.join("Bea")
        ok, err = self.server.start_game()
        self.assertTrue(ok, err)
        # nobody moves, armies stay equal -> draw on time
        go = wait_for(self.server.events, "gameover", timeout=6.0)
        self.assertEqual(go["winner"], -1)
        go_c = wait_for(c.events, "gameover", timeout=6.0)
        self.assertEqual(go_c["winner"], -1)


def two_udp_ports():
    """Two DISTINCT free UDP ports (held simultaneously so they can't collide)."""
    s1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s1.bind(("127.0.0.1", 0))
    s2.bind(("127.0.0.1", 0))
    p1, p2 = s1.getsockname()[1], s2.getsockname()[1]
    s1.close()
    s2.close()
    return p1, p2


class TestPresence(unittest.TestCase):
    """v3: UDP presence beacons + invites.

    Windows loopback broadcast is unreliable, so the two instances live on
    different loopback ports and inject each other's address via the
    _peers_hint test hook (beacons then ALSO go out as unicast).
    """

    def setUp(self):
        self._old_beacon = net._PRESENCE_BEACON
        net._PRESENCE_BEACON = 0.15   # module-level, re-read every cycle
        self.services = []

    def tearDown(self):
        for svc in self.services:
            svc.close()
        net._PRESENCE_BEACON = self._old_beacon

    def make(self, name, port, hints=()):
        svc = net.PresenceService(name, port=port, _peers_hint=list(hints))
        self.services.append(svc)
        return svc

    def make_pair(self):
        pa, pb = two_udp_ports()
        a = self.make("Alice", pa, hints=[("127.0.0.1", pb)])
        b = self.make("Bob", pb, hints=[("127.0.0.1", pa)])
        a.start()
        b.start()
        return a, b, pa, pb

    def wait_peer(self, svc, want_name, timeout=8.0, predicate=None):
        end = time.time() + timeout
        while time.time() < end:
            for p in svc.peers():
                if p["name"] == want_name and (predicate is None
                                               or predicate(p)):
                    return p
            time.sleep(0.05)
        raise AssertionError("%r never saw peer %r" % (svc, want_name))

    def test_discovery_invite_and_clean_close(self):
        a, b, pa, pb = self.make_pair()

        # -- mutual discovery (beacons repeat every 0.15s) --
        bob = self.wait_peer(a, "Bob")
        alice = self.wait_peer(b, "Alice")
        self.assertEqual(tuple(bob["addr"]), ("127.0.0.1", pb))
        self.assertEqual(tuple(alice["addr"]), ("127.0.0.1", pa))
        self.assertFalse(bob["hosting"])
        self.assertIsInstance(bob["last_seen"], float)
        self.assertLess(bob["last_seen"], net.PRESENCE_TTL)
        # own broadcast echo is filtered by iid
        self.assertNotIn("Alice", [p["name"] for p in a.peers()])

        # -- invite only works while a host code is set --
        self.assertFalse(a.invite("Bob"))
        code = net.encode_code("192.168.1.42", 47733)
        a.set_host_code(code)
        self.assertTrue(a.invite("Bob"))
        inv = wait_for(b.events, "invite")
        self.assertEqual(inv["from"], "Alice")
        self.assertEqual(inv["code"], code)
        # hosting flag propagates via the beacons
        self.wait_peer(b, "Alice", predicate=lambda p: p["hosting"])

        # -- clearing the code stops invites (and un-flags hosting) --
        a.set_host_code(None)
        self.assertFalse(a.invite("Bob"))
        self.wait_peer(b, "Alice", predicate=lambda p: not p["hosting"])

        # -- rename shows up in peers --
        b.set_name("Robert")
        self.wait_peer(a, "Robert")

        # -- close() leaves no lingering threads and is re-entrant --
        for svc in (a, b):
            svc.close()
            for t in svc._threads:
                self.assertFalse(t.is_alive(), "presence thread leaked")
            svc.close()   # double close is safe
            self.assertEqual(svc.peers(), [])
            self.assertFalse(svc.invite("Bob"))

    def test_invite_unknown_peer_is_false(self):
        pa, _pb = two_udp_ports()
        a = self.make("Loner", pa)
        a.start()
        a.set_host_code("AAAAA-AAAAA")
        self.assertFalse(a.invite("Nobody"))

    def test_malformed_datagrams_ignored(self):
        a, b, pa, _pb = self.make_pair()
        self.wait_peer(a, "Bob")
        junk = (b"", b"\x00\x01\x02\xff", b"not json at all\n",
                b'"just a string"', b"[1,2,3]",
                b'{"t":"presence"}',                    # no iid/name
                b'{"t":"presence","iid":7,"name":3}',   # wrong types
                b'{"t":"invite"}',                      # no from/code
                b'{"t":"invite","from":"X","code":""}',  # empty code
                b'{"t":"presence","name":"Evil","iid"')  # truncated JSON
        raw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for datagram in junk:
                raw.sendto(datagram, ("127.0.0.1", pa))
        finally:
            raw.close()
        # the receiver survived: fresh beacons still land and invites flow
        time.sleep(0.4)
        self.wait_peer(a, "Bob",
                       predicate=lambda p: p["last_seen"] < 0.4)
        a.set_host_code(net.encode_code("10.0.0.1", 47733))
        self.assertTrue(a.invite("Bob"))
        wait_for(b.events, "invite")
        # none of the junk produced an event on the receiving side
        self.assertTrue(a.events.empty())
        names = [p["name"] for p in a.peers()]
        self.assertEqual(names, ["Bob"])

    def test_bind_failure_degrades_to_noop(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):   # Windows
            port = free_port()
            blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            blocker.setsockopt(socket.SOL_SOCKET,
                               socket.SO_EXCLUSIVEADDRUSE, 1)
            blocker.bind(("", port))
            self.addCleanup(blocker.close)
        else:                                        # anywhere else
            port = 1 << 17   # unbindable: out of range
        svc = self.make("Inert", port)
        svc.start()                     # must NOT raise
        svc.set_host_code("AAAAA-AAAAA")
        svc.set_name("Still Inert")
        self.assertEqual(svc.peers(), [])
        self.assertFalse(svc.invite("Anyone"))
        self.assertEqual(svc._threads, [])   # no threads were spawned
        svc.close()                     # must NOT raise
        self.assertTrue(svc.events.empty())


class TestGraveFlow(unittest.TestCase):
    """v4: dead players curse tiles through the wire.

    Bob is eliminated by a scripted king capture — the authoritative board
    is nudged under the server lock, then the capture is submitted through
    the NORMAL move path — so his NetClient stays CONNECTED and can send
    the grave message afterwards (a disconnected player has no socket).
    """

    def setUp(self):
        self.port = free_port()
        self.server = net.HostServer("Host", self.port)
        self.server.start()
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.server.close()
        time.sleep(0.1)

    def join(self, name):
        c = net.NetClient()
        c.connect("127.0.0.1", self.port, name, timeout=5.0)
        self.clients.append(c)
        return c

    def _start_three(self):
        """Host + Ann + Bob, game running; returns (ann, bob)."""
        ann = self.join("Ann")
        bob = self.join("Bob")
        ok, err = self.server.start_game()
        self.assertTrue(ok, err)
        wait_for(self.server.events, "start")
        wait_for(ann.events, "start")
        wait_for(bob.events, "start")
        return ann, bob

    def _eliminate_bob(self, ann, bob):
        """Scripted king capture over the wire; returns the converged state.

        Teleports Bob's king and the host's queen to the empty board centre
        (3p radius-7 hexagon: armies hug their edges, the middle is free),
        then the host captures the king via submit_host_move. Bob is
        eliminated but still connected; every queue is drained of the
        resulting state broadcast so later steps see clean queues.
        """
        with self.server._lock:
            gs = self.server._gs
            self.assertEqual(gs.turn_pid, 0)   # fresh game: host to move
            bk = next(c for c, pc in gs.board.items()
                      if pc.owner == bob.pid and pc.type == "K")
            hq = next(c for c, pc in gs.board.items()
                      if pc.owner == 0 and pc.type == "Q")
            self.assertNotIn((0, 0), gs.board)
            self.assertNotIn((1, 0), gs.board)
            gs.board[(0, 0)] = gs.board.pop(bk)
            gs.board[(1, 0)] = gs.board.pop(hq)
        self.server.submit_host_move(engine.Move((1, 0), (0, 0)).to_dict())
        sh = wait_for(self.server.events, "state")["state"]
        sa = wait_for(ann.events, "state")["state"]
        sb = wait_for(bob.events, "state")["state"]
        self.assertEqual(sh, sa)
        self.assertEqual(sh, sb)
        dead = next(p for p in sh["players"] if p["pid"] == bob.pid)
        self.assertFalse(dead["alive"])
        self.assertFalse(any(row[3] == bob.pid for row in sh["board"]))
        self.assertIsNone(sh["winner"])   # host + Ann still playing
        self.assertEqual(sh["graves_left"][str(bob.pid)], 1)
        self.assertEqual(sh["graveyards"], [])
        return sh

    def test_grave_flow_and_rejections(self):
        ann, bob = self._start_three()
        sd = self._eliminate_bob(ann, bob)
        turn_before = sd["turn_pid"]
        self.assertEqual(turn_before, ann.pid)   # capture advanced the turn

        # -- alive players cannot curse (client + host entry points) --
        ann.send_grave([0, 1])
        err = wait_for(ann.events, "error")
        self.assertIn("dead", err["msg"].lower())
        self.server.submit_host_grave([0, 1])
        err = wait_for(self.server.events, "error")
        self.assertIn("dead", err["msg"].lower())

        # -- occupied cell: the host queen sits on (0,0) after the capture --
        bob.send_grave([0, 0])
        err = wait_for(bob.events, "error")
        self.assertIn("occupied", err["msg"].lower())

        # -- off-board cell --
        bob.send_grave([99, 99])
        err = wait_for(bob.events, "error")
        self.assertIn("board", err["msg"].lower())

        # -- malformed payloads are rejected, never crash the server --
        for bad in (None, 7, "xy", [1], [1, 2, 3], {"q": 0, "r": 1},
                    ["a", "b"], [None, None]):
            bob.send_grave(bad)
            err = wait_for(bob.events, "error")
            self.assertIn("malformed", err["msg"].lower(),
                          "bad cell %r" % (bad,))

        # -- the real curse: all three participants converge --
        bob.send_grave((0, 1))
        mh = wait_for(self.server.events, "state")
        ma = wait_for(ann.events, "state")
        mb = wait_for(bob.events, "state")
        self.assertEqual(mh["state"], ma["state"])
        self.assertEqual(mh["state"], mb["state"])
        want_last = {"pid": bob.pid, "move": {"from": [0, 1], "to": [0, 1],
                                              "kind": "grave"}}
        self.assertEqual(mh["last_move"], want_last)
        self.assertEqual(ma["last_move"], want_last)
        sd = mh["state"]
        self.assertEqual(sd["graveyards"], [[0, 1]])
        self.assertEqual(sd["graves_left"][str(bob.pid)], 0)
        self.assertIsNone(sd["winner"])
        self.assertEqual(sd["turn_pid"], turn_before)   # NOT turn-based
        self.assertTrue(any("curses a tile from beyond the grave" in line
                            and "Bob" in line for line in sd["log"]))
        gs = engine.GameState.from_dict(sd)
        self.assertIn((0, 1), gs.graveyards)

        # -- a dead player gets exactly one curse --
        bob.send_grave([2, 0])
        err = wait_for(bob.events, "error")
        self.assertIn("no curses left", err["msg"].lower())

        # -- play continues over the cursed board and still converges --
        gs = engine.GameState.from_dict(mh["state"])
        self.assertEqual(gs.turn_pid, ann.pid)
        mv = random.Random(11).choice(gs.all_legal_moves(ann.pid))
        ann.send_move(mv.to_dict())
        mh = wait_for(self.server.events, "state")
        ma = wait_for(ann.events, "state")
        mb = wait_for(bob.events, "state")
        self.assertEqual(mh["state"], ma["state"])
        self.assertEqual(mh["state"], mb["state"])
        self.assertEqual(mh["state"]["graveyards"], [[0, 1]])

    def test_grave_rejected_before_game_starts(self):
        bob = self.join("Bob")
        bob.send_grave([0, 0])
        err = wait_for(bob.events, "error")
        self.assertIn("not started", err["msg"].lower())

    def test_sk_rows_cross_the_wire(self):
        """v4 serialization: a Skeleton (6-element board row incl. `uses`)
        survives the trip through the wire byte-identically."""
        ann = self.join("Ann")
        ok, err = self.server.start_game()
        self.assertTrue(ok, err)
        wait_for(self.server.events, "start")
        wait_for(ann.events, "start")
        with self.server._lock:
            gs = self.server._gs
            self.assertNotIn((0, 0), gs.board)
            gs.board[(0, 0)] = engine.Piece("SK", 0, moved=True, uses=2)
            # a host move that does NOT touch the skeleton (a 3rd move
            # would crumble it) — any other piece's move works
            mv = next(m for m in gs.all_legal_moves(0)
                      if m.from_ != (0, 0))
        self.server.submit_host_move(mv.to_dict())
        sh = wait_for(self.server.events, "state")["state"]
        sa = wait_for(ann.events, "state")["state"]
        self.assertEqual(sh, sa)
        row = next(r for r in sa["board"] if r[2] == "SK")
        self.assertEqual(list(row), [0, 0, "SK", 0, 1, 2])
        piece = engine.GameState.from_dict(sa).board[(0, 0)]
        self.assertEqual((piece.type, piece.owner, piece.moved, piece.uses),
                         ("SK", 0, True, 2))


@contextlib.contextmanager
def one_shot_http(status, body, content_length=None):
    """Serve exactly ONE canned HTTP response on a loopback socket.

    Yields the base URL. `content_length` may LIE (bigger than the body) to
    simulate a connection dropped mid-download.
    """
    ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ls.bind(("127.0.0.1", 0))
    ls.listen(1)
    ls.settimeout(5.0)
    port = ls.getsockname()[1]

    def serve():
        try:
            conn, _addr = ls.accept()
        except OSError:
            return
        try:
            conn.settimeout(5.0)
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                head += chunk
            n = len(body) if content_length is None else content_length
            reply = ("HTTP/1.1 %d Canned\r\n"
                     "Content-Type: application/octet-stream\r\n"
                     "Content-Length: %d\r\n"
                     "Connection: close\r\n\r\n" % (status, n))
            conn.sendall(reply.encode("ascii") + body)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        yield "http://127.0.0.1:%d" % port
    finally:
        try:
            ls.close()
        except OSError:
            pass
        t.join(5.0)


class TestReleaseHelpers(unittest.TestCase):
    """v4: get_latest_release / download_file error paths.

    NEVER touches real GitHub: net.GITHUB_API is repointed at localhost
    (unroutable ports and one-shot canned responses only).
    """

    def setUp(self):
        self._old_api = net.GITHUB_API
        self.addCleanup(lambda: setattr(net, "GITHUB_API", self._old_api))
        self.tmp = tempfile.mkdtemp(prefix="chess3-net-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_repo_constant(self):
        self.assertEqual(net.GITHUB_REPO, "CoopNutt/chess3")

    def test_release_check_unroutable_is_none(self):
        net.GITHUB_API = "http://127.0.0.1:%d" % free_port()  # nothing listens
        t0 = time.time()
        self.assertIsNone(net.get_latest_release(timeout=2.0))
        self.assertLess(time.time() - t0, 5.0)

    def test_release_check_bad_responses_are_none(self):
        exe_less = {"tag_name": "v4.0.0", "body": "x", "assets": [
            {"name": "source.zip",
             "browser_download_url": "http://127.0.0.1:9/s.zip"}]}
        cases = [
            (404, b'{"message":"Not Found"}'),            # no release yet
            (403, b'{"message":"API rate limit exceeded"}'),
            (500, b"boom"),
            (200, b"not json at all"),
            (200, b"[1,2,3]"),                            # wrong JSON shape
            (200, b'{"assets":[]}'),                      # no tag
            (200, b'{"tag_name":"v4","assets":[]}'),      # no assets
            (200, json.dumps(exe_less).encode("utf-8")),  # no .exe asset
        ]
        for status, body in cases:
            with one_shot_http(status, body) as base:
                net.GITHUB_API = base
                self.assertIsNone(net.get_latest_release(timeout=3.0),
                                  "HTTP %d %r" % (status, body[:40]))

    def test_release_check_parses_canned_release(self):
        rel = {"tag_name": "v4.1.0", "body": "bug fixes",
               "assets": [
                   {"name": "notes.txt",
                    "browser_download_url": "http://127.0.0.1:9/notes.txt"},
                   {"name": "Chess3.exe",
                    "browser_download_url": "http://127.0.0.1:9/Chess3.exe"},
               ]}
        with one_shot_http(200, json.dumps(rel).encode("utf-8")) as base:
            net.GITHUB_API = base
            got = net.get_latest_release(timeout=3.0)
        self.assertEqual(got, {"tag": "v4.1.0",
                               "url": "http://127.0.0.1:9/Chess3.exe",
                               "notes": "bug fixes"})

    def test_download_unroutable_is_false_and_leaves_no_file(self):
        dest = os.path.join(self.tmp, "Chess3_new.exe")
        url = "http://127.0.0.1:%d/Chess3.exe" % free_port()
        self.assertFalse(net.download_file(url, dest, timeout=2.0))
        self.assertFalse(os.path.exists(dest))

    def test_download_streams_all_chunks(self):
        payload = bytes(random.Random(4).randrange(256)
                        for _ in range(200 * 1024))   # several 64K chunks
        dest = os.path.join(self.tmp, "ok.exe")
        with one_shot_http(200, payload) as base:
            self.assertTrue(net.download_file(base + "/Chess3.exe", dest,
                                              timeout=5.0))
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), payload)

    def test_download_truncated_removes_partial_file(self):
        dest = os.path.join(self.tmp, "partial.exe")
        # server promises 1 MB but hangs up after 3 bytes
        with one_shot_http(200, b"abc", content_length=1024 * 1024) as base:
            self.assertFalse(net.download_file(base + "/Chess3.exe", dest,
                                               timeout=5.0))
        self.assertFalse(os.path.exists(dest), "partial file left behind")


if __name__ == "__main__":
    unittest.main()
