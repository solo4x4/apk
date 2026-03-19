"""
bt_hid.py
Android Bluetooth HID Device controller.

The phone registers itself as a Bluetooth HID keyboard/consumer-control device.
Google TV then pairs with it (Settings → Remotes → Add Bluetooth device).
No ADB required – the TV receives standard HID reports.

Requires Android 9+ (API 28).
On desktop/CI the class degrades gracefully to a no-op stub.
"""

import threading
import time

# ─────────────────────────────────────────────────────────────
# HID report descriptor
# Report ID 1 : Keyboard (navigation arrows, enter, escape)
# Report ID 2 : Consumer Control (play/pause, volume)
# ─────────────────────────────────────────────────────────────
HID_DESCRIPTOR = bytes([
    # ── Keyboard ────────────────────────────────────────────
    0x05, 0x01,        # Usage Page (Generic Desktop Controls)
    0x09, 0x06,        # Usage (Keyboard)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x01,        #   Report ID 1
    # Modifier byte (Shift, Ctrl, Alt …)
    0x05, 0x07,        #   Usage Page (Key Codes)
    0x19, 0xE0,        #   Usage Min (0xE0)
    0x29, 0xE7,        #   Usage Max (0xE7)
    0x15, 0x00,        #   Logical Min (0)
    0x25, 0x01,        #   Logical Max (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x08,        #   Report Count (8)
    0x81, 0x02,        #   Input (Data, Var, Abs)
    # Reserved byte
    0x95, 0x01,        #   Report Count (1)
    0x75, 0x08,        #   Report Size (8)
    0x81, 0x01,        #   Input (Const)
    # 6-key rollover keycodes
    0x95, 0x06,        #   Report Count (6)
    0x75, 0x08,        #   Report Size (8)
    0x15, 0x00,        #   Logical Min (0)
    0x26, 0xFF, 0x00,  #   Logical Max (255)
    0x05, 0x07,        #   Usage Page (Key Codes)
    0x19, 0x00,        #   Usage Min (0)
    0x29, 0xFF,        #   Usage Max (255)
    0x81, 0x00,        #   Input (Data, Array)
    0xC0,              # End Collection

    # ── Consumer Control ─────────────────────────────────────
    0x05, 0x0C,        # Usage Page (Consumer Devices)
    0x09, 0x01,        # Usage (Consumer Control)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x02,        #   Report ID 2
    0x15, 0x00,        #   Logical Min (0)
    0x25, 0x01,        #   Logical Max (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x08,        #   Report Count (8)
    # Bits 0-7: Play/Pause, Mute, Vol+, Vol-, Next, Prev, Stop, (reserved)
    0x0A, 0xCD, 0x00,  #   Usage (Play/Pause)      bit 0
    0x0A, 0xE2, 0x00,  #   Usage (Mute)            bit 1
    0x0A, 0xE9, 0x00,  #   Usage (Volume Inc)      bit 2
    0x0A, 0xEA, 0x00,  #   Usage (Volume Dec)      bit 3
    0x0A, 0xB5, 0x00,  #   Usage (Scan Next)       bit 4
    0x0A, 0xB6, 0x00,  #   Usage (Scan Prev)       bit 5
    0x0A, 0xB7, 0x00,  #   Usage (Stop)            bit 6
    0x09, 0x00,        #   Usage (Unassigned)      bit 7
    0x81, 0x02,        #   Input (Data, Var, Abs)
    0xC0,              # End Collection
])

# ─────────────────────────────────────────────────────────────
# HID key-code table
# Keyboard report: bytes[modifier, reserved, key1..key6]
# ─────────────────────────────────────────────────────────────
# Standard HID keyboard usage codes
HID_KEY = {
    "UP":    0x52,   # Up Arrow
    "DOWN":  0x51,   # Down Arrow
    "LEFT":  0x50,   # Left Arrow
    "RIGHT": 0x4F,   # Right Arrow
    "OK":    0x28,   # Enter / Return  → DPAD_CENTER on Android TV
    "BACK":  0x29,   # Escape          → BACK on Android TV
    "HOME":  0x4A,   # Home key
}

# Consumer control report byte (bit positions in the 1-byte consumer report)
# Bit 0 = Play/Pause, Bit 2 = Vol+, Bit 3 = Vol−
CONSUMER_BIT = {
    "PLAY_PAUSE": 0b00000001,  # bit 0
    "VOL_UP":     0b00000100,  # bit 2
    "VOL_DOWN":   0b00001000,  # bit 3
}

KEY_PRESS_DURATION = 0.05   # seconds hold before releasing


# ─────────────────────────────────────────────────────────────
# Android imports (graceful fallback when running on desktop)
# ─────────────────────────────────────────────────────────────
try:
    from jnius import autoclass, PythonJavaClass, java_method  # type: ignore

    BluetoothAdapter  = autoclass("android.bluetooth.BluetoothAdapter")
    BluetoothHidDev   = autoclass("android.bluetooth.BluetoothHidDevice")
    BluetoothHidDevAR = autoclass("android.bluetooth.BluetoothHidDeviceAppSdpSettings")
    BluetoothProfile  = autoclass("android.bluetooth.BluetoothProfile")
    BluetoothDevice   = autoclass("android.bluetooth.BluetoothDevice")
    Executors         = autoclass("java.util.concurrent.Executors")
    PythonActivity    = autoclass("org.kivy.android.PythonActivity")

    _ANDROID = True
except Exception:
    _ANDROID = False


# ─────────────────────────────────────────────────────────────
# Java callback implementations (pyjnius)
# ─────────────────────────────────────────────────────────────
if _ANDROID:
    class _ServiceListener(PythonJavaClass):
        """BluetoothProfile.ServiceListener – called when HID proxy is ready."""
        __javainterfaces__ = ["android/bluetooth/BluetoothProfile$ServiceListener"]
        __javacontext__    = "app"

        def __init__(self, ctrl):
            super().__init__()
            self._ctrl = ctrl

        @java_method("(ILandroid/bluetooth/BluetoothProfile;)V")
        def onServiceConnected(self, profile, proxy):
            print("[BT-HID] Service connected – registering app …")
            self._ctrl._on_proxy_ready(proxy)

        @java_method("(I)V")
        def onServiceDisconnected(self, profile):
            print("[BT-HID] Service disconnected.")
            self._ctrl._hid_device = None

    class _HidCallback(PythonJavaClass):
        """BluetoothHidDevice.Callback – host connection events."""
        __javainterfaces__ = ["android/bluetooth/BluetoothHidDevice$Callback"]
        __javacontext__    = "app"

        def __init__(self, ctrl):
            super().__init__()
            self._ctrl = ctrl

        @java_method("(Landroid/bluetooth/BluetoothDevice;)V")
        def onAppStatusChanged(self, device, registered):
            print(f"[BT-HID] App status changed – registered={registered}")

        @java_method("(Landroid/bluetooth/BluetoothDevice;I)V")
        def onConnectionStateChanged(self, device, state):
            # 2 = STATE_CONNECTED, 0 = STATE_DISCONNECTED
            connected = (state == 2)
            print(f"[BT-HID] Connection state → {'CONNECTED' if connected else 'DISCONNECTED'}")
            self._ctrl._connected_device = device if connected else None

        @java_method("(Landroid/bluetooth/BluetoothDevice;IBI[B)V")
        def onGetReport(self, device, type_, reportId, bufferSize):
            pass   # not needed for this use-case

        @java_method("(Landroid/bluetooth/BluetoothDevice;BI[B)V")
        def onSetReport(self, device, type_, reportId, data):
            pass

        @java_method("(Landroid/bluetooth/BluetoothDevice;B)V")
        def onSetProtocol(self, device, protocol):
            pass

        @java_method("(Landroid/bluetooth/BluetoothDevice;[B)V")
        def onInterruptData(self, device, data):
            pass

        @java_method("(Landroid/bluetooth/BluetoothDevice;)V")
        def onVirtualCableUnplug(self, device):
            print("[BT-HID] Virtual cable unplugged.")
            self._ctrl._connected_device = None


# ─────────────────────────────────────────────────────────────
# Public controller
# ─────────────────────────────────────────────────────────────
class BluetoothHIDController:
    """
    Register the phone as a Bluetooth HID keyboard.
    Usage:
        ctrl = BluetoothHIDController()
        ctrl.register_hid()            # call once (or from Settings button)
        ctrl.send_key("UP")            # call from gesture engine
    """

    def __init__(self):
        self._hid_device       = None   # BluetoothHidDevice proxy
        self._connected_device = None   # paired host (Google TV)
        self._lock             = threading.Lock()

        if not _ANDROID:
            print("[BT-HID] Not on Android – running in stub mode.")

    # ── registration ─────────────────────────────────────────
    def register_hid(self):
        """
        Request the BluetoothHidDevice proxy from the system.
        Must be called from a background thread (already done via main.py).
        """
        if not _ANDROID:
            print("[BT-HID stub] register_hid() – no-op on desktop")
            return

        adapter = BluetoothAdapter.getDefaultAdapter()
        if adapter is None or not adapter.isEnabled():
            print("[BT-HID] Bluetooth is OFF – please enable it.")
            return

        # Make device discoverable so Google TV can find it
        context  = PythonActivity.mActivity
        listener = _ServiceListener(self)

        ok = adapter.getProfileProxy(
            context,
            listener,
            BluetoothProfile.HID_DEVICE,   # = 19
        )
        print(f"[BT-HID] getProfileProxy requested → {ok}")

    def _on_proxy_ready(self, proxy):
        """Called by _ServiceListener.onServiceConnected."""
        self._hid_device = proxy

        sdp = BluetoothHidDevAR(
            "Gesture TV Remote",          # name
            "GestureTVRemote",            # description
            "PythonKivy",                 # provider
            0x0100,                       # subclass: keyboard
            HID_DESCRIPTOR,
        )
        executor = Executors.newSingleThreadExecutor()
        callback = _HidCallback(self)
        self._hid_device.registerApp(sdp, None, None, executor, callback)
        print("[BT-HID] registerApp() called – discoverable as Bluetooth keyboard.")

    # ── key sending ──────────────────────────────────────────
    def send_key(self, key_name: str):
        """Send a key event to the connected TV. Thread-safe."""
        threading.Thread(target=self._send_key_bg, args=(key_name,),
                         daemon=True).start()

    def _send_key_bg(self, key_name: str):
        if not _ANDROID:
            print(f"[BT-HID stub] send_key({key_name})")
            return

        with self._lock:
            dev = self._connected_device
            hid = self._hid_device
            if hid is None or dev is None:
                print(f"[BT-HID] Not connected – cannot send {key_name}")
                return

            if key_name in HID_KEY:
                self._send_keyboard(hid, dev, HID_KEY[key_name])
            elif key_name in CONSUMER_BIT:
                self._send_consumer(hid, dev, CONSUMER_BIT[key_name])

    def _send_keyboard(self, hid, device, hid_code: int):
        """Send key-down then key-up for a standard keyboard HID code."""
        # Report: [modifier, reserved, key1, key2, key3, key4, key5, key6]
        key_down = bytes([0x00, 0x00, hid_code, 0, 0, 0, 0, 0])
        key_up   = bytes([0x00, 0x00,         0, 0, 0, 0, 0, 0])
        hid.sendReport(device, 1, key_down)
        time.sleep(KEY_PRESS_DURATION)
        hid.sendReport(device, 1, key_up)

    def _send_consumer(self, hid, device, bit_mask: int):
        """Send consumer control (media / volume) report."""
        # 1-byte bitmask: bit on → key down, then all-zero → key up
        hid.sendReport(device, 2, bytes([bit_mask]))
        time.sleep(KEY_PRESS_DURATION)
        hid.sendReport(device, 2, bytes([0x00]))

    # ── status ───────────────────────────────────────────────
    @property
    def is_connected(self) -> bool:
        return self._connected_device is not None

    @property
    def paired_device_name(self) -> str:
        if not _ANDROID or self._connected_device is None:
            return ""
        try:
            return self._connected_device.getName() or "Unknown"
        except Exception:
            return "Unknown"

    def close(self):
        if not _ANDROID or self._hid_device is None:
            return
        try:
            self._hid_device.unregisterApp()
        except Exception:
            pass
