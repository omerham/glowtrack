"""Other lights besides the Govee lamps: WiZ, LIFX and WLED.

EXPERIMENTAL: written from each product's published local-network protocol and
checked against fake devices in the tests, but not yet tried on real hardware.

Every device follows one lamp's colours ("left" or "right"). A single-colour light
(WiZ, LIFX) shows the average of the 7 zone colours; a WLED strip spreads the 7 zones
along its length. Colours are only sent when they change, at a rate each device copes with.
"""
import colorsys
import ipaddress
import json
import socket
import struct
import threading
import time
import urllib.request

REFRESH = 2.0        # resend an unchanged colour this often, in case a packet was lost
MIN_CHANGE = 2       # ignore colour changes smaller than this (0-255 per channel)


def is_lan_ip(ip):
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return a.is_private or a.is_link_local


def average_colour(segs):
    n = max(1, len(segs))
    return tuple(int(round(sum(c[i] for c in segs) / n)) for i in range(3))


def scale(c, factor):
    return tuple(max(0, min(255, int(round(v * factor)))) for v in c)


class Device:
    kind = "device"
    label = "Light"
    min_interval = 0.08         # seconds between updates

    def __init__(self, ip, side="left"):
        self.ip = ip
        self.side = side if side in ("left", "right") else "left"
        self.last_seen = 0.0
        self._last = None       # what was last sent
        self._sent_at = 0.0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # -- to override ---------------------------------------------------
    def _send_colours(self, colours, persistent):
        raise NotImplementedError

    def set_power(self, on):
        pass

    def ping(self):
        """Marks the device online if it answers. Returns True if it did."""
        return False

    # -- shared --------------------------------------------------------
    def send_frame(self, segs, persistent, brightness_pct):
        """segs: 7 zone colours (index 0 = base). Skips sends that wouldn't change anything."""
        colours = self.shape([scale(c, brightness_pct / 100.0) for c in segs])
        now = time.time()
        if not persistent:
            if now - self._sent_at < self.min_interval:
                return
            if self._last is not None and now - self._sent_at < REFRESH and self._close(colours, self._last):
                return
        try:
            self._send_colours(colours, persistent)
        except OSError:
            return
        self._last, self._sent_at = colours, now

    def shape(self, segs):
        """Turns 7 zone colours into what this device shows. Default: one colour."""
        return [average_colour(segs)]

    @staticmethod
    def _close(a, b):
        return len(a) == len(b) and all(max(abs(x - y) for x, y in zip(c1, c2)) < MIN_CHANGE for c1, c2 in zip(a, b))

    def forget_sent(self):
        self._last = None

    def is_online(self, window=50.0):
        return (time.time() - self.last_seen) < window

    def to_config(self):
        return {"kind": self.kind, "ip": self.ip, "side": self.side}

    def to_dict(self):
        return {"kind": self.kind, "label": self.label, "ip": self.ip, "side": self.side, "online": self.is_online()}

    def _request(self, payload, port, timeout=0.6):
        """Sends one UDP packet and waits briefly for an answer (None if there is none)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            s.sendto(payload, (self.ip, port))
            return s.recvfrom(4096)[0]
        except OSError:
            return None
        finally:
            s.close()


# ---------------------------------------------------------------------------
# WiZ  (UDP 38899, JSON)
# ---------------------------------------------------------------------------
class WizLight(Device):
    kind, label = "wiz", "WiZ"
    PORT = 38899

    def _send_colours(self, colours, persistent):
        r, g, b = colours[0]
        msg = {"id": 1, "method": "setPilot", "params": {"r": r, "g": g, "b": b, "dimming": 100}}
        if r == g == b == 0:
            msg = {"id": 1, "method": "setPilot", "params": {"state": False}}
        else:
            msg["params"]["state"] = True
        self.sock.sendto(json.dumps(msg).encode("utf-8"), (self.ip, self.PORT))

    def set_power(self, on):
        self._last = None
        msg = {"id": 1, "method": "setState", "params": {"state": bool(on)}}
        try:
            self.sock.sendto(json.dumps(msg).encode("utf-8"), (self.ip, self.PORT))
        except OSError:
            pass

    def ping(self):
        res = self._request(json.dumps({"method": "getPilot", "params": {}}).encode("utf-8"), self.PORT)
        if res:
            self.last_seen = time.time()
        return bool(res)

    @staticmethod
    def discover(wait=1.5):
        """Broadcasts a registration request; WiZ bulbs answer with their address."""
        found = []
        msg = json.dumps({"method": "registration", "id": 1,
                          "params": {"phoneMac": "AAAAAAAAAAAA", "register": False,
                                     "phoneIp": "1.2.3.4", "id": "1"}}).encode("utf-8")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.3)
        try:
            s.sendto(msg, ("255.255.255.255", WizLight.PORT))
            end = time.time() + wait
            while time.time() < end:
                try:
                    data, addr = s.recvfrom(2048)
                except socket.timeout:
                    continue
                if is_lan_ip(addr[0]) and addr[0] not in found and b"result" in data:
                    found.append(addr[0])
        except OSError:
            pass
        finally:
            s.close()
        return found


# ---------------------------------------------------------------------------
# LIFX  (UDP 56700, binary)
# ---------------------------------------------------------------------------
LIFX_SOURCE = 0x474C4F57   # "GLOW"
LIFX_GET_SERVICE, LIFX_STATE_SERVICE = 2, 3
LIFX_SET_COLOR, LIFX_SET_POWER = 102, 117


def lifx_packet(msg_type, payload=b"", tagged=False, sequence=0, res_required=False):
    """36-byte LIFX header + payload."""
    size = 36 + len(payload)
    protocol = 1024 | (1 << 12) | ((1 << 13) if tagged else 0)     # protocol 1024, addressable, tagged
    flags = 1 if res_required else 0
    header = struct.pack("<HHI8s6sBBQHH", size, protocol, LIFX_SOURCE, b"\x00" * 8, b"\x00" * 6,
                         flags, sequence & 0xFF, 0, msg_type, 0)
    return header + payload


def lifx_set_color(rgb, duration_ms=60):
    r, g, b = (v / 255.0 for v in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    payload = struct.pack("<BHHHHI", 0, int(h * 65535) & 0xFFFF, int(s * 65535), int(v * 65535), 3500, duration_ms)
    return lifx_packet(LIFX_SET_COLOR, payload)


class LifxLight(Device):
    kind, label = "lifx", "LIFX"
    PORT = 56700
    min_interval = 0.06

    def __init__(self, ip, side="left"):
        super().__init__(ip, side)
        self._seq = 0

    def _send_colours(self, colours, persistent):
        self._seq = (self._seq + 1) & 0xFF
        pkt = lifx_set_color(colours[0], 0 if persistent else 60)
        pkt = pkt[:23] + bytes([self._seq]) + pkt[24:]
        self.sock.sendto(pkt, (self.ip, self.PORT))

    def set_power(self, on):
        self._last = None
        payload = struct.pack("<HI", 65535 if on else 0, 0)
        try:
            self.sock.sendto(lifx_packet(LIFX_SET_POWER, payload), (self.ip, self.PORT))
        except OSError:
            pass

    def ping(self):
        res = self._request(lifx_packet(LIFX_GET_SERVICE, res_required=True), self.PORT)
        ok = bool(res) and len(res) >= 36 and struct.unpack_from("<H", res, 32)[0] == LIFX_STATE_SERVICE
        if ok:
            self.last_seen = time.time()
        return ok

    @staticmethod
    def discover(wait=1.5):
        found = []
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.3)
        try:
            s.sendto(lifx_packet(LIFX_GET_SERVICE, tagged=True, res_required=True), ("255.255.255.255", LifxLight.PORT))
            end = time.time() + wait
            while time.time() < end:
                try:
                    data, addr = s.recvfrom(2048)
                except socket.timeout:
                    continue
                if (len(data) >= 36 and struct.unpack_from("<H", data, 32)[0] == LIFX_STATE_SERVICE
                        and is_lan_ip(addr[0]) and addr[0] not in found):
                    found.append(addr[0])
        except OSError:
            pass
        finally:
            s.close()
        return found


# ---------------------------------------------------------------------------
# WLED  (LED strips; UDP realtime "DRGB" on 21324 + small HTTP calls)
# ---------------------------------------------------------------------------
class WledStrip(Device):
    kind, label = "wled", "WLED strip"
    UDP_PORT = 21324
    MAX_LEDS = 490            # most LEDs one DRGB packet can carry
    min_interval = 0.04

    def __init__(self, ip, side="left"):
        super().__init__(ip, side)
        self.led_count = 30

    def shape(self, segs):
        """Spreads the 7 zones along the strip, blending between neighbouring zones."""
        n = max(1, min(self.led_count, self.MAX_LEDS))
        if n == 1:
            return [average_colour(segs)]
        out = []
        for i in range(n):
            pos = i / (n - 1) * (len(segs) - 1)
            lo = int(pos)
            hi = min(len(segs) - 1, lo + 1)
            t = pos - lo
            out.append(tuple(int(round(segs[lo][k] * (1 - t) + segs[hi][k] * t)) for k in range(3)))
        return out

    def _send_colours(self, colours, persistent):
        # Timeout byte: 255 = stay until changed (held colour); otherwise it falls back to the
        # strip's own pattern after a couple of seconds, so a stopped server never leaves it stuck.
        timeout = 255 if persistent else 2
        pkt = bytes([2, timeout]) + b"".join(bytes(c) for c in colours[:self.MAX_LEDS])
        self.sock.sendto(pkt, (self.ip, self.UDP_PORT))

    def _http(self, path, body=None, timeout=1.0):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(f"http://{self.ip}{path}", data=data,
                                     headers={"Content-Type": "application/json"} if data else {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def set_power(self, on):
        self._last = None
        try:
            self._http("/json/state", {"on": bool(on)})
        except Exception:
            pass

    def ping(self):
        try:
            info = self._http("/json/info")
            count = int(((info or {}).get("leds") or {}).get("count") or 0)
            if count > 0:
                self.led_count = count
            self.last_seen = time.time()
            return True
        except Exception:
            return False

    @staticmethod
    def discover(wait=1.5):
        return []      # WLED has no broadcast discovery we can use without extra libraries: add by IP


KINDS = {cls.kind: cls for cls in (WizLight, LifxLight, WledStrip)}
DISCOVERABLE = (WizLight, LifxLight)


def make_device(kind, ip, side="left"):
    """Builds a device, or raises ValueError for a bad kind / address."""
    if kind not in KINDS:
        raise ValueError("unknown device type")
    if not is_lan_ip(ip):
        raise ValueError("that isn't an address on your local network")
    return KINDS[kind](ip, side)


def discover_all():
    """[{kind, ip}] for every WiZ / LIFX light that answers on the network."""
    results, lock = [], threading.Lock()

    def run(cls):
        for ip in cls.discover():
            with lock:
                results.append({"kind": cls.kind, "ip": ip})

    threads = [threading.Thread(target=run, args=(c,), daemon=True) for c in DISCOVERABLE]
    for t in threads:
        t.start()
    for t in threads:
        t.join(4)
    return results
