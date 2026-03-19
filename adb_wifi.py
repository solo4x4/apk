"""
adb_wifi.py
Wi-Fi ADB fallback – sends keyevents over TCP/IP ADB.
Mirrors the original desktop script but uses the `adb` binary
bundled in the APK (assets/adb-arm64) or the system adb.
On Android, we shell out to the bundled adb binary.
On desktop, we use whatever adb is in PATH.
"""

import os
import shutil
import subprocess
import threading
import time

# ─────────────────────────────────────────────────────────────
# Google TV key codes (same as desktop script)
# ─────────────────────────────────────────────────────────────
KEYS = {
    "UP":         "KEYCODE_DPAD_UP",
    "DOWN":       "KEYCODE_DPAD_DOWN",
    "LEFT":       "KEYCODE_DPAD_LEFT",
    "RIGHT":      "KEYCODE_DPAD_RIGHT",
    "OK":         "KEYCODE_DPAD_CENTER",
    "BACK":       "KEYCODE_BACK",
    "HOME":       "KEYCODE_HOME",
    "PLAY_PAUSE": "KEYCODE_MEDIA_PLAY_PAUSE",
    "VOL_UP":     "KEYCODE_VOLUME_UP",
    "VOL_DOWN":   "KEYCODE_VOLUME_DOWN",
}


def _find_adb() -> str | None:
    """
    Locate the adb binary.
    1. Android: check app private storage for bundled adb-arm64
    2. Fallback: system PATH
    """
    # On Android the APK assets can be copied to private storage at first run
    try:
        from android.storage import app_storage_path  # type: ignore
        bundled = os.path.join(app_storage_path(), "adb")
        if os.path.isfile(bundled):
            os.chmod(bundled, 0o755)
            return bundled
    except ImportError:
        pass
    return shutil.which("adb")


class ADBWifiController:
    """
    Connect to a Google TV over ADB Wi-Fi and send keyevents.
    Thread-safe – keyevent calls return immediately (fire-and-forget).
    """

    def __init__(self):
        self._addr     = ""
        self._exe      = _find_adb()
        self._lock     = threading.Lock()
        self._connected = False

        if self._exe:
            print(f"[ADB-WiFi] Using adb at: {self._exe}")
        else:
            print("[ADB-WiFi] adb binary not found – Wi-Fi mode unavailable.")

    # ── connection ───────────────────────────────────────────
    def connect(self, ip: str, port: int = 5555) -> tuple:
        """
        Connect to TV. Returns (success: bool, message: str).
        Runs synchronously – call from a background thread.
        """
        self._addr = f"{ip}:{port}"
        self._connected = False

        if not self._exe:
            return False, "adb binary not found"

        try:
            r = subprocess.run(
                [self._exe, "connect", self._addr],
                capture_output=True, text=True, timeout=10,
            )
            out = (r.stdout + r.stderr).strip()
            ok  = "connected" in out.lower() or "already" in out.lower()
            self._connected = ok
            print(f"[ADB-WiFi] connect → {out}")
            return ok, out
        except Exception as exc:
            msg = str(exc)
            print(f"[ADB-WiFi] connect failed: {msg}")
            return False, msg

    def disconnect(self):
        if not self._exe or not self._addr:
            return
        subprocess.run([self._exe, "disconnect", self._addr],
                       capture_output=True, timeout=5)
        self._connected = False

    # ── key sending ──────────────────────────────────────────
    def keyevent(self, key_name: str):
        """Fire-and-forget keyevent. Thread-safe."""
        if key_name not in KEYS:
            print(f"[ADB-WiFi] Unknown key: {key_name}")
            return
        threading.Thread(target=self._send, args=(key_name,), daemon=True).start()

    def _send(self, key_name: str):
        if not self._exe or not self._addr:
            print(f"[ADB-WiFi stub] keyevent {key_name}")
            return
        code = KEYS[key_name]
        with self._lock:
            try:
                subprocess.run(
                    [self._exe, "-s", self._addr,
                     "shell", "input", "keyevent", code],
                    capture_output=True, timeout=5,
                )
            except Exception as exc:
                print(f"[ADB-WiFi] send failed ({key_name}): {exc}")
                self._connected = False

    # ── status ───────────────────────────────────────────────
    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def address(self) -> str:
        return self._addr

    # ── adb bundling helper (called at app startup) ──────────
    @staticmethod
    def extract_bundled_adb():
        """
        Copy the adb binary from APK assets to app private storage.
        Call once at startup on Android.
        """
        try:
            from android.storage import app_storage_path       # type: ignore
            from jnius import autoclass                         # type: ignore

            dest = os.path.join(app_storage_path(), "adb")
            if os.path.isfile(dest):
                return dest

            # Read from APK assets
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            context        = PythonActivity.mActivity
            asset_mgr      = context.getAssets()
            stream         = asset_mgr.open("adb-arm64")

            buf = bytearray()
            chunk = stream.read(65536)
            while chunk and chunk != -1:
                buf.extend(bytes(chunk))
                chunk = stream.read(65536)
            stream.close()

            with open(dest, "wb") as f:
                f.write(buf)
            os.chmod(dest, 0o755)
            print(f"[ADB-WiFi] Extracted bundled adb to {dest}")
            return dest

        except Exception as exc:
            print(f"[ADB-WiFi] Could not extract bundled adb: {exc}")
            return None
