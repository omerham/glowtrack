"""Govee LAN protocol: discovery, online status and sending colours over UDP."""
import base64
import collections
import ipaddress
import json
import socket
import threading
import time

from config import GOVEE_REPLY_PORT, GOVEE_SCAN_PORT, GOVEE_UDP_PORT, LAMP_ONLINE_WINDOW, clamp


def _is_local_ip(ip):
    """True for a plain private/link-local IPv4 address (what a lamp on your Wi-Fi has)."""
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return a.is_private or a.is_link_local


class GoveeController:
    def __init__(self, ips):
        self.all_ips = list(ips)
        self.left_ip = ips[0] if len(ips) > 0 else ""
        self.right_ip = ips[1] if len(ips) > 1 else ""
        self.ips = [self.left_ip, self.right_ip] if (self.left_ip and self.right_ip) else list(ips)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_lock = threading.Lock()
        self.is_powered_on = True
        self.get_envelope = None
        # What each lamp was last told per zone, so moving frames only send
        # the zones that changed (the lamps choke on 7 zone commands x 15 fps)
        self._sent = {}            # ip -> [rgb]*7
        self._zone_t = {}          # ip -> [time each zone was last sent]
        self.record = None         # debug: list of (time, ips, msg) while recording
        self.devices = []          # other lights (WiZ, LIFX, WLED), see devices.py
        self.brightness_pct = 100
        self.skus = {}             # ip -> Govee model name (from the scan reply), e.g. "H6076"

        # Lamp reply tracking (scan + devStatus answers arrive on port 4002)
        self.last_seen = {}            # ip -> time of last reply
        self.status = {}               # ip -> what the lamp last said about itself: on/off, brightness, colour
        self._probe = None             # while a link check runs: ip -> {"sent": [times], "got": [times]}
        self._link_log = {}            # ip -> recent link checks, True when a lamp answered (see probe_links)
        self._link_rtt = {}            # ip -> how long the first answer of the last check took, in ms
        self._heal_tries = {}          # ip -> brightness corrections sent in a row
        self._heal_gave_up = {}        # ip -> when we stopped correcting it
        self._revived = {}             # ip -> when it was last switched off and on to unstick it
        self.listener_ok = False       # False if port 4002 could not be opened
        self.listener_error = ""
        self.ip_lock = threading.Lock()
        self.on_lamps_changed = None   # callback when the lamp list changes
        self.first_check_done_at = None  # status isn't known until the first check had time to answer

    # ---------------------------------------------------------------
    # Discovery & online status
    # ---------------------------------------------------------------
    def start_listener(self):
        """One long-lived socket on port 4002 that hears every lamp reply.
        It is opened BEFORE any scan is sent, so fast replies are never missed."""
        try:
            ls = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            ls.bind(("", GOVEE_REPLY_PORT))
            self.listener_ok = True
        except Exception as e:
            self.listener_ok = False
            self.listener_error = f"Port {GOVEE_REPLY_PORT} unavailable: {e}"
            print(f"[!] Lamp listener could not start: {e}")
            return

        def _listen():
            while True:
                try:
                    data, addr = ls.recvfrom(2048)
                except Exception:
                    time.sleep(0.5)
                    continue
                src_ip = addr[0]
                try:
                    resp = json.loads(data.decode("utf-8"))
                    data_ = resp.get("msg", {}).get("data", {})
                    reported_ip = data_.get("ip") or src_ip
                    if resp.get("msg", {}).get("cmd") == "devStatus" and self._probe is not None and src_ip in self._probe:
                        self._probe[src_ip]["got"].append(time.time())
                    if resp.get("msg", {}).get("cmd") == "devStatus" and "brightness" in data_:
                        self.status[src_ip] = {"on": data_.get("onOff"), "brightness": data_.get("brightness"),
                                               "color": data_.get("color"), "kelvin": data_.get("colorTemInKelvin"), "t": time.time()}
                    if data_.get("sku") and _is_local_ip(reported_ip):
                        self.skus[reported_ip] = str(data_["sku"])
                except Exception:
                    reported_ip = src_ip
                now = time.time()
                changed = False
                with self.ip_lock:
                    for ip in {src_ip, reported_ip}:
                        if not _is_local_ip(ip):
                            continue     # ignore anything that isn't a LAN address
                        self.last_seen[ip] = now
                        if ip not in self.all_ips:
                            self.all_ips.append(ip)
                            changed = True
                    if changed:
                        if not self.left_ip:
                            self.left_ip = self.all_ips[0]
                        if not self.right_ip and len(self.all_ips) > 1:
                            self.right_ip = next((i for i in self.all_ips if i != self.left_ip), "")
                        self.sync_ordered_ips()
                if changed and self.on_lamps_changed:
                    self.on_lamps_changed()
        threading.Thread(target=_listen, daemon=True).start()

    def is_online(self, ip):
        t = self.last_seen.get(ip)
        return bool(t and (time.time() - t) < LAMP_ONLINE_WINDOW)

    def ping_status(self):
        """Asks every known lamp for its status; replies mark it online."""
        self.send_cmd({"msg": {"cmd": "devStatus", "data": {}}}, ips=list(self.all_ips))

    def send_scan(self):
        """Multicast "who's there?" - lamps answer this more reliably than devStatus."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.sendto(json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode("utf-8"),
                     ("239.255.255.250", GOVEE_SCAN_PORT))
            s.close()
        except Exception:
            pass

    def status_loop(self):
        """Checks the lamps every 15 s. Some lamps ignore the odd devStatus request,
        so every check also sends a scan - any reply counts as online."""
        self.first_check_done_at = time.time() + 3.0
        while True:
            self.probe_links()                    # a few status requests per lamp: marks them online and measures the link
            self.send_scan()
            for d in list(self.devices):
                try:
                    d.ping()
                except Exception:
                    pass
            try:
                self.heal_brightness()
            except Exception as e:
                print(f"[!] Brightness check failed: {e}")
            time.sleep(12.5)

    PROBES = 5                      # status requests per lamp in one link check
    PROBE_GAP = 0.4                 # seconds between them: lamps answer only some requests that arrive in a quick burst
    LINK_SAMPLES = 40               # answers remembered per lamp (about eight checks)

    def probe_links(self):
        """Sends a few status requests to every lamp, spaced out, and counts the answers. The count is only
        information: a lamp may answer just some requests because it limits its replies, not because packets are
        lost, so it is never used to change how colours are sent."""
        ips = list(self.ips)
        probe = {ip: {"sent": [], "got": []} for ip in ips}
        self._probe = probe
        try:
            for _ in range(self.PROBES):
                for ip in ips:
                    probe[ip]["sent"].append(time.time())
                    self.send_cmd({"msg": {"cmd": "devStatus", "data": {}}}, ips=[ip])
                time.sleep(self.PROBE_GAP)
            time.sleep(0.5)
        finally:
            self._probe = None
        for ip in ips:
            got = min(len(probe[ip]["got"]), self.PROBES)
            log = self._link_log.setdefault(ip, collections.deque(maxlen=self.LINK_SAMPLES))
            log.extend([True] * got + [False] * (self.PROBES - got))
            if probe[ip]["got"]:
                self._link_rtt[ip] = round((min(probe[ip]["got"]) - probe[ip]["sent"][0]) * 1000)
        # lamps outside the configured pair (extra lamps) still count as online when they answer
        for ip in self.all_ips:
            if ip not in ips:
                self.send_cmd({"msg": {"cmd": "devStatus", "data": {}}}, ips=[ip])

    def link_info(self):
        """{ip: {"answered_pct": 0-100, "rtt_ms": int or None, "samples": n}} for the state shown in the dashboard."""
        out = {}
        for ip, log in self._link_log.items():
            if log:
                out[ip] = {"answered_pct": round(100.0 * sum(log) / len(log)), "rtt_ms": self._link_rtt.get(ip), "samples": len(log)}
        return out

    SYNC_COLOUR = (200, 60, 60)

    @staticmethod
    def compare_lamps(a, b, name_a="left", name_b="right"):
        """What two lamps' own status reports say about whether they match. Returns a list of plain-language problems."""
        problems = []
        if a is None or b is None:
            return [f"the {name_a if a is None else name_b} lamp did not answer"]
        if bool(a.get("on")) != bool(b.get("on")):
            problems.append(f"one lamp is on and the other is off ({name_a}: {'on' if a.get('on') else 'off'})")
        try:
            if abs(int(a["brightness"]) - int(b["brightness"])) > 3:
                problems.append(f"brightness differs: {name_a} {a['brightness']}%, {name_b} {b['brightness']}%")
        except (KeyError, TypeError, ValueError):
            pass
        ca, cb = a.get("color"), b.get("color")
        if ca and cb:
            worst = max(abs(int(ca[k]) - int(cb[k])) for k in "rgb")
            if worst > 20:
                problems.append(f"the colours differ: {name_a} ({ca['r']}, {ca['g']}, {ca['b']}), {name_b} ({cb['r']}, {cb['g']}, {cb['b']})")
        return problems

    def sync_check(self):
        """Sets both lamps to the same colour and asks each what it is showing. The lamps' own answers say whether they
        match, so this checks the real thing and not what Glowtrack believes it sent. Takes about three seconds."""
        left = self.left_ip or (self.ips[0] if self.ips else None)
        right = self.right_ip or (self.ips[1] if len(self.ips) > 1 else None)
        if not left or not right:
            return {"ok": False, "lines": ["This check needs two lamps."]}
        started = time.time()
        r, g, b = self.SYNC_COLOUR
        for _ in range(2):
            self.send_cmd({"msg": {"cmd": "colorwc", "data": {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0}}}, ips=[left, right])
            time.sleep(0.15)
        time.sleep(0.8)
        self.probe_links()
        sa, sb = self.status.get(left), self.status.get(right)
        sa = sa if sa and sa["t"] >= started else None
        sb = sb if sb and sb["t"] >= started else None
        problems = self.compare_lamps(sa, sb)
        link = self.link_info()
        if not problems:
            lines = ["Both lamps report the same colour and brightness."]
            if link and len(link) >= 2 and None not in (link[left]["rtt_ms"], link[right]["rtt_ms"]) and abs(link[left]["rtt_ms"] - link[right]["rtt_ms"]) > 40:
                lines.append(f"They answer at different speeds ({link[left]['rtt_ms']} ms and {link[right]['rtt_ms']} ms), so one may lag the other a little.")
            return {"ok": True, "lines": lines}
        return {"ok": False, "lines": problems}

    BRIGHTNESS_TOLERANCE = 3       # a lamp within this many percent of the wanted level counts as right
    BRIGHTNESS_TRIES = 8           # corrections tried in a row (one every 15 s) before giving up for a while
    BRIGHTNESS_BURST = 3           # copies of each correction: UDP drops packets, and a lamp busy with colour frames misses some

    def heal_brightness(self, now=None):
        """Makes every lamp match the brightness Glowtrack is set to. The brightness command is only sent when the
        slider moves (and once at start), so a lamp that missed it, was offline at that moment or was changed from
        the Govee app stays at its own level while the other lamp is right. Each lamp reports its brightness in its
        status reply: when it differs, send the command to that lamp alone."""
        now = time.time() if now is None else now
        want = max(1, min(100, int(self.brightness_pct)))
        for ip in list(self.ips):
            st = self.status.get(ip)
            if not st or now - st["t"] > 30 or not st.get("on"):
                continue                         # no fresh report, or the lamp is off: nothing to compare
            try:
                have = int(st["brightness"])
            except (TypeError, ValueError):
                continue
            if abs(have - want) <= self.BRIGHTNESS_TOLERANCE:
                self._heal_tries[ip] = 0
                continue
            tries = self._heal_tries.get(ip, 0)
            if tries >= self.BRIGHTNESS_TRIES:
                if ip not in self._heal_gave_up:
                    self._heal_gave_up[ip] = now
                    self.revive(ip, now)                     # it ignored every correction: it is stuck, so switch it off and on once
                elif now - self._heal_gave_up[ip] > 300:     # then try again every five minutes
                    self._heal_tries[ip] = 0
                    del self._heal_gave_up[ip]
                continue
            self._heal_tries[ip] = tries + 1
            print(f"[*] Lamp {ip} was at {have}% brightness, wanted {want}%: correcting")
            for _ in range(self.BRIGHTNESS_BURST):
                self.send_cmd({"msg": {"cmd": "brightness", "data": {"value": want}}}, ips=[ip])
                time.sleep(0.12)

    REVIVE_GAP = 600                # a lamp is switched off and on at most once in this many seconds

    def revive(self, ip, now=None):
        """A lamp that ignores brightness corrections is stuck (it needs a power cycle, which is what unplugging does).
        This switches that one lamp off and on over the network, then resends everything to it."""
        now = time.time() if now is None else now
        if now - self._revived.get(ip, -1e9) < self.REVIVE_GAP:
            return False
        self._revived[ip] = now
        print(f"[*] Lamp {ip} ignored every correction: switching it off and on")
        self.send_cmd({"msg": {"cmd": "turn", "data": {"value": 0}}}, ips=[ip])
        time.sleep(self.REVIVE_PAUSE)
        self.send_cmd({"msg": {"cmd": "turn", "data": {"value": 1}}}, ips=[ip])
        time.sleep(self.REVIVE_PAUSE)
        self._sent.pop(ip, None)
        self._zone_t.pop(ip, None)
        for _ in range(self.BRIGHTNESS_BURST):
            self.send_cmd({"msg": {"cmd": "brightness", "data": {"value": max(1, min(100, int(self.brightness_pct)))}}}, ips=[ip])
            time.sleep(0.12)
        self._heal_tries[ip] = 0
        self._heal_gave_up.pop(ip, None)
        return True

    REVIVE_PAUSE = 1.0

    def sync_ordered_ips(self):
        new_ips = []
        if self.left_ip:
            new_ips.append(self.left_ip)
        if self.right_ip and self.right_ip not in new_ips:
            new_ips.append(self.right_ip)
        for ip in self.all_ips:
            if ip not in new_ips:
                new_ips.append(ip)
        self.ips = new_ips

    def discover_lamps(self, wait_sec=2.5):
        """Sends a multicast scan (plus a status ping to known lamps) and waits
        for the always-on listener to collect replies."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            msg = {"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}
            payload = json.dumps(msg).encode("utf-8")
            # Send twice - UDP multicast can drop a packet
            s.sendto(payload, ("239.255.255.250", GOVEE_SCAN_PORT))
            time.sleep(0.3)
            s.sendto(payload, ("239.255.255.250", GOVEE_SCAN_PORT))
            s.close()
        except Exception as e:
            print(f"[!] Lamp scan failed: {e}")
        self.ping_status()
        time.sleep(wait_sec)
        return self.ips

    def identify_lamp(self, target_ip, on_start=None, on_done=None):
        """Flashes the target lamp 3 times in cyan so you can see which one it is.
        The lighting engine pauses while this runs so it doesn't overwrite the blink."""
        def _blink():
            b64_cyan = self.make_all_b64(0, 255, 255)
            b64_off = self.make_all_b64(0, 0, 0)
            msg_on = {"msg": {"cmd": "ptReal", "data": {"command": [b64_cyan]}}}
            msg_off = {"msg": {"cmd": "ptReal", "data": {"command": [b64_off]}}}
            if on_start:
                on_start(target_ip)
            try:
                for _ in range(3):
                    self.send_cmd(msg_on, ips=[target_ip])
                    time.sleep(0.25)
                    self.send_cmd(msg_off, ips=[target_ip])
                    time.sleep(0.18)
            finally:
                self.forget_sent()
                if on_done:
                    on_done(target_ip)
        threading.Thread(target=_blink, daemon=True).start()

    def flash(self, rgb=(255, 0, 0), times=3, on_start=None, on_done=None):
        """Flashes every lamp in one colour (e.g. red 3x as a "needs your
        attention" signal). Lamps that were off are switched on for the flash
        and back off afterwards."""
        targets = [ip for ip in (self.left_ip, self.right_ip) if ip] or list(self.ips)

        def _blink():
            msg_on = {"msg": {"cmd": "ptReal", "data": {"command": [self.make_all_b64(*rgb)]}}}
            msg_off = {"msg": {"cmd": "ptReal", "data": {"command": [self.make_all_b64(0, 0, 0)]}}}
            if on_start:
                on_start()
            try:
                for _ in range(times):
                    self.send_cmd(msg_on, ips=targets)
                    time.sleep(0.3)
                    self.send_cmd(msg_off, ips=targets)
                    time.sleep(0.22)
            finally:
                self.forget_sent()
                if on_done:
                    on_done()
        threading.Thread(target=_blink, daemon=True).start()

    # ---------------------------------------------------------------
    # Unified frame output (used by the lighting engine only)
    # ---------------------------------------------------------------
    def send_frame(self, left_segs, right_segs, persistent=False):
        """Sends one frame: 7 zone colours for the left lamp and 7 for the right.
        Picks the cheapest packet: one solid colour per lamp when the lamp is a
        single colour, otherwise all 7 zones in one atomic packet."""
        if not self.is_powered_on:
            return
        env = self.get_envelope() if self.get_envelope else 1.0

        def scaled(c):
            return (clamp(int(round(c[0] * env)), 0, 255),
                    clamp(int(round(c[1] * env)), 0, 255),
                    clamp(int(round(c[2] * env)), 0, 255))

        left_ip = self.left_ip or (self.ips[0] if self.ips else None)
        right_ip = self.right_ip or (self.ips[1] if len(self.ips) > 1 else None)
        extra_ips = [ip for ip in self.ips if ip not in (left_ip, right_ip)]

        for ip, segs in ((left_ip, left_segs), (right_ip, right_segs)):
            if not ip:
                continue
            self._send_lamp_segs(ip, [scaled(c) for c in segs], persistent)
        # Any extra lamps mirror the left lamp
        for ip in extra_ips:
            self._send_lamp_segs(ip, [scaled(c) for c in left_segs], persistent)
        # Other brands: each follows the left or right lamp
        for d in list(self.devices):
            d.send_frame([scaled(c) for c in (left_segs if d.side == "left" else right_segs)],
                         persistent, self.brightness_pct)


    # Moving frames: at most this many zone commands per lamp per frame, the
    # zones that are furthest from their target first. Zones within
    # SEG_SKIP of what the lamp already shows are left alone, and zones whose
    # target colours are within SEG_GROUP of each other share one command.
    SEG_BUDGET = 3
    SEG_SKIP = 2
    SEG_GROUP = 6
    SEG_REFRESH = 2.0   # a zone that hasn't been sent for this long is re-sent, in case a packet was lost

    def forget_sent(self):
        """Something else changed the lamps (flash, identify): resend everything."""
        self._sent.clear()
        self._zone_t.clear()
        for d in list(self.devices):
            d.forget_sent()

    # Models whose 7-zone packets we know. Any other Govee model that identified itself
    # gets one averaged colour instead (zone packets could be ignored or misread).
    ZONE_MODELS = {"H6076"}

    def _send_lamp_segs(self, ip, segs, persistent, now=None):
        segs = [tuple(c) for c in segs[:7]]
        now = time.time() if now is None else now
        sku = self.skus.get(ip)
        if sku and sku not in self.ZONE_MODELS:
            n = max(1, len(segs))
            avg = tuple(int(round(sum(c[i] for c in segs) / n)) for i in range(3))
            segs = [avg] * 7
        solid = all(c == segs[0] for c in segs)
        if solid:
            r, g, b = segs[0]
            if persistent:
                self.send_cmd({"msg": {"cmd": "colorwc", "data": {
                    "color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0}}}, ips=[ip])
            else:
                self.send_cmd({"msg": {"cmd": "ptReal", "data": {
                    "command": [self.make_all_b64(r, g, b)]}}}, ips=[ip])
            self._sent[ip] = list(segs)
            self._zone_t[ip] = [now] * 7
            return

        last = self._sent.get(ip)
        times = self._zone_t.setdefault(ip, [0.0] * 7)
        if persistent or last is None:
            groups = self._group_zones(segs, range(7))
        else:
            # Only a few zone commands fit in each frame. Zones that have waited longest and
            # are furthest from their colour go first, so every zone is updated at a steady
            # pace. (Chasing only the biggest difference left some zones hanging back and then
            # jumping, and a resend-everything every 2 s made them all pop at once.)
            diff = lambda i: max(abs(segs[i][k] - last[i][k]) for k in range(3))
            cand = []
            for i in range(7):
                d, age = diff(i), now - times[i]
                if d > self.SEG_SKIP or (d > 0 and age >= self.SEG_REFRESH):
                    cand.append((d * (age + 0.05), i))
            if not cand:
                return
            order = [i for _, i in sorted(cand, reverse=True)]
            groups = self._group_zones(segs, order)[:self.SEG_BUDGET]
        commands = []
        sent = list(last) if last else list(segs)
        for colour, mask in groups:
            commands.append(self.make_mask_b64(colour[0], colour[1], colour[2], mask))
            for i in range(7):
                if mask & (1 << i):
                    sent[i] = colour
                    times[i] = now
        self._sent[ip] = sent
        self.send_cmd({"msg": {"cmd": "ptReal", "data": {"command": commands}}}, ips=[ip])

    def _group_zones(self, segs, order):
        """[(colour, mask)] in the given zone order; zones with nearly the same
        target colour are folded into the first one's command."""
        groups, used = [], set()
        order = list(order)
        for i in order:
            if i in used:
                continue
            mask = 1 << i
            used.add(i)
            for j in order:
                if j not in used and max(abs(segs[i][k] - segs[j][k]) for k in range(3)) <= self.SEG_GROUP:
                    mask |= 1 << j
                    used.add(j)
            groups.append((segs[i], mask))
        return groups

    def send_cmd(self, msg, ips=None):
        targets = ips if ips is not None else self.ips
        if self.record is not None:
            self.record.append((time.time(), list(targets), msg))
        payload = json.dumps(msg).encode("utf-8")
        with self.udp_lock:
            for ip in targets:
                try:
                    self.sock.sendto(payload, (ip, GOVEE_UDP_PORT))
                except Exception:
                    pass

    RELEASE_WAIT = 0.6

    def release(self):
        """Hands the lamps back: a plain warm-white colour command, which ends the zone-by-zone control Glowtrack
        used, so the Govee app (and the lamps' own buttons) work normally again. Lamps that are off stay off.
        Each lamp is then asked what it shows; one that did not take the command is switched off and on, because a
        lamp left stuck would ignore the Govee app too."""
        if not self.is_powered_on:
            return
        def plain():
            for _ in range(2):                   # UDP can drop a packet; the second one costs nothing
                self.send_cmd({"msg": {"cmd": "colorwc", "data": {
                    "color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": 3500}}})
                time.sleep(0.12)
        asked = time.time()
        plain()
        self.send_cmd({"msg": {"cmd": "devStatus", "data": {}}})
        time.sleep(self.RELEASE_WAIT)
        stuck = [ip for ip in self.ips if self._ignored_release(ip, asked)]
        if stuck:
            print(f"[*] Lamps {stuck} did not take the release: switching them off and on")
            for ip in stuck:
                self.send_cmd({"msg": {"cmd": "turn", "data": {"value": 0}}}, ips=[ip])
            time.sleep(0.5)
            for ip in stuck:
                self.send_cmd({"msg": {"cmd": "turn", "data": {"value": 1}}}, ips=[ip])
            time.sleep(0.5)
            for _ in range(2):
                self.send_cmd({"msg": {"cmd": "colorwc", "data": {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": 3500}}}, ips=stuck)
                time.sleep(0.12)

    def _ignored_release(self, ip, asked):
        """True when the lamp answered after the release and still shows something other than plain warm white.
        A lamp that did not answer is left alone: there is no proof it is stuck."""
        st = self.status.get(ip)
        if not st or st["t"] < asked or not st.get("on"):
            return False
        return st.get("kelvin") != 3500

    def set_power(self, on_off):
        self.is_powered_on = bool(on_off)
        self.send_cmd({"msg": {"cmd": "turn", "data": {"value": 1 if on_off else 0}}})
        for d in list(self.devices):
            d.set_power(on_off)

    def set_brightness(self, val):
        val = max(1, min(100, int(val)))
        self.brightness_pct = val
        for d in list(self.devices):
            d.forget_sent()
        self.send_cmd({"msg": {"cmd": "brightness", "data": {"value": val}}})

    @staticmethod
    def make_all_b64(r, g, b):
        """Constructs an instantaneous ptReal packet for all 7 segments (0x7F mask)."""
        pkt = bytearray(20)
        pkt[0] = 0x33
        pkt[1] = 0x05
        pkt[2] = 0x15
        pkt[3] = 0x01
        pkt[4] = max(0, min(255, int(r)))
        pkt[5] = max(0, min(255, int(g)))
        pkt[6] = max(0, min(255, int(b)))
        pkt[12] = 0x7F
        pkt[13] = 0x00
        chk = 0
        for byte in pkt[:19]:
            chk ^= byte
        pkt[19] = chk
        return base64.b64encode(pkt).decode("ascii")

    @staticmethod
    def make_mask_b64(r, g, b, mask):
        """One 20-byte ptReal colour command for every zone set in mask."""
        pkt = bytearray(20)
        pkt[0:4] = b"\x33\x05\x15\x01"
        pkt[4] = max(0, min(255, int(r)))
        pkt[5] = max(0, min(255, int(g)))
        pkt[6] = max(0, min(255, int(b)))
        pkt[12] = mask & 0xFF
        pkt[13] = (mask >> 8) & 0xFF
        chk = 0
        for byte in pkt[:19]:
            chk ^= byte
        pkt[19] = chk
        return base64.b64encode(pkt).decode("ascii")

    @staticmethod
    def make_segment_b64(r, g, b, segment_idx):
        """Constructs a 20-byte ptReal segment packet for one specific zone."""
        pkt = bytearray(20)
        pkt[0] = 0x33
        pkt[1] = 0x05
        pkt[2] = 0x15
        pkt[3] = 0x01
        pkt[4] = max(0, min(255, int(r)))
        pkt[5] = max(0, min(255, int(g)))
        pkt[6] = max(0, min(255, int(b)))
        pkt[12] = (1 << segment_idx) & 0xFF
        pkt[13] = ((1 << segment_idx) >> 8) & 0xFF
        chk = 0
        for byte in pkt[:19]:
            chk ^= byte
        pkt[19] = chk
        return base64.b64encode(pkt).decode("ascii")
