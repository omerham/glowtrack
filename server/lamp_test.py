"""A/B test patterns for finding which way of sending colours looks smooth
on the real lamps. Runs on a thread while the lighting engine is paused."""
import colorsys
import threading
import time

PATTERN_SECS = 15.0
GAP_SECS = 3.0
CYCLE_SECS = 10.0   # how long the colours take to go round once


def _zones(t):
    """A flowing rainbow, one colour per zone, like 7-Zone mode."""
    out = []
    for i in range(7):
        h = (t / CYCLE_SECS + i * 0.05) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, 1.0, 1.0)
        out.append((int(r * 255), int(g * 255), int(b * 255)))
    return out


def run(state):
    gv = state.govee
    ips = [ip for ip in (gv.left_ip, gv.right_ip) if ip]

    def every_zone(segs):
        cmds = [gv.make_mask_b64(*c, 1 << i) for i, c in enumerate(segs)]
        gv.send_cmd({"msg": {"cmd": "ptReal", "data": {"command": cmds}}}, ips=ips)

    def whole_lamp(segs):
        gv.send_cmd({"msg": {"cmd": "ptReal", "data": {"command": [gv.make_all_b64(*segs[0])]}}}, ips=ips)

    def budget(segs):
        for ip in ips:
            gv._send_lamp_segs(ip, segs, False)

    def one_per_packet(segs):
        for i, c in enumerate(segs):
            gv.send_cmd({"msg": {"cmd": "ptReal", "data": {"command": [gv.make_mask_b64(*c, 1 << i)]}}}, ips=ips)

    patterns = [
        ("1 whole lamp, 8/s (deliberately steppy, for reference)", whole_lamp, 8),
        ("2 whole lamp, 30/s", whole_lamp, 30),
        ("3 all 7 zones, 30/s", every_zone, 30),
    ]

    def _go():
        state.engine_paused = True
        time.sleep(0.2)
        try:
            for name, fn, fps in patterns:
                print(f"[test] {name}")
                state.lamp_test_step = name
                state.broadcast()
                gv.forget_sent()
                gv.send_cmd({"msg": {"cmd": "ptReal", "data": {"command": [gv.make_all_b64(0, 0, 0)]}}}, ips=ips)
                time.sleep(GAP_SECS)
                t0 = time.time()
                while time.time() - t0 < PATTERN_SECS:
                    fn(_zones(time.time() - t0))
                    time.sleep(1.0 / fps)
        finally:
            state.lamp_test_step = None
            gv.forget_sent()
            state.engine_paused = False
            state.out_frame = None
            state.request_update(0)

    if not state.engine_paused:
        threading.Thread(target=_go, daemon=True).start()
