"""Settings, constants and the saved config file."""
import json
import os
import secrets
import threading

VERSION = "3.2.2"               # keep in step with mac/Info.plist
ISSUES_URL = "https://github.com/omerham/glowtrack/issues/new"

# Lamps are found automatically on the local network (and remembered in the
# config file). Add IPs here only to force specific lamps.
TARGET_IPS = []
GOVEE_UDP_PORT = 4003        # lamps listen for commands here
GOVEE_REPLY_PORT = 4002      # lamps send scan / status replies here
GOVEE_SCAN_PORT = 4001       # multicast discovery port
SERVER_PORT = int(os.environ.get("GOVEE_PORT", "8765"))
CONFIG_FILE = os.environ.get("GOVEE_CONFIG_FILE") or os.path.expanduser("~/.govee_spotify_config.json")

# Phones/iPads on the same Wi-Fi can use the dashboard (http://<this Mac's IP>:8765
# or http://<Mac name>.local:8765). Set GOVEE_LOCAL_ONLY=1 to allow this Mac only.
LOCAL_ONLY = os.environ.get("GOVEE_LOCAL_ONLY", "").strip() in ("1", "true", "yes")
ALLOW_LAN = not LOCAL_ONLY
BIND_HOST = "0.0.0.0" if ALLOW_LAN else "127.0.0.1"

# A lamp counts as online if it answered within this many seconds.
LAMP_ONLINE_WINDOW = 50.0   # ~3 missed checks before a lamp shows as offline

def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

_SAVE_LOCK = threading.Lock()

def save_config(cfg):
    """Writes the config atomically. Saves can arrive from several threads at once (a dashboard
    change while the lamps are renamed, say), so they take turns instead of fighting over one temp file."""
    with _SAVE_LOCK:
        try:
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(cfg, f, indent=2)
            os.replace(tmp, CONFIG_FILE)
        except Exception as e:
            print(f"[!] Could not save config: {e}")


# Other devices on the Wi-Fi must be "paired" once (open the link shown in Settings on
# this Mac). GOVEE_OPEN_LAN=1 turns that off (anyone on the network can then control it).
DEFAULT_THEME = os.environ.get("GOVEE_DEFAULT_THEME", "classic").strip().lower()
if DEFAULT_THEME not in ("classic", "a", "b", "c", "d"):
    DEFAULT_THEME = "classic"

OPEN_LAN = os.environ.get("GOVEE_OPEN_LAN", "").strip() in ("1", "true", "yes")


def get_pair_token():
    """Secret for pairing phones/tablets; made once and kept in the config file."""
    cfg = load_config()
    token = cfg.get("pair_token")
    if not isinstance(token, str) or len(token) < 12:
        token = secrets.token_urlsafe(16)
        cfg["pair_token"] = token
        save_config(cfg)
    return token


def clamp(v, lo, hi):
    return max(lo, min(hi, v))

# Colours shown before the first song loads
STARTUP_PALETTE = [(255, 120, 20), (255, 195, 30)]
# Lamps go plain white during Spotify ads
AD_WHITE = (255, 255, 255)
