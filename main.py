"""
gesture_tv_android / main.py
Hand-gesture Google TV remote – Android (Kivy)
Primary connection : Bluetooth HID (phone acts as BT keyboard)
Fallback           : ADB over Wi-Fi TCP/IP
"""

import threading
import time

import cv2
import numpy as np
from kivy.app import App
from kivy.clock import Clock
from kivy.graphics.texture import Texture
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.core.window import Window

# Android-specific: only import on device
try:
    from android.permissions import Permission, request_permissions
    from jnius import autoclass
    IS_ANDROID = True
except ImportError:
    IS_ANDROID = False

from gesture_engine import GestureEngine
from bt_hid import BluetoothHIDController
from adb_wifi import ADBWifiController

# ─────────────────────────────────────────────────────────────
# Colour palette
# ─────────────────────────────────────────────────────────────
C_BG     = (0.06, 0.06, 0.08, 1)
C_PANEL  = (0.10, 0.10, 0.14, 1)
C_ACCENT = (0.00, 0.84, 1.00, 1)
C_GREEN  = (0.00, 0.94, 0.43, 1)
C_RED    = (1.00, 0.25, 0.25, 1)
C_TEXT   = (0.85, 0.85, 0.90, 1)


# ─────────────────────────────────────────────────────────────
# Settings screen
# ─────────────────────────────────────────────────────────────
class SettingsScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical", padding=24, spacing=14,
                         size_hint=(1, 1))

        root.add_widget(Label(text="[b]Gesture TV Remote[/b]",
                              markup=True, font_size="22sp",
                              size_hint_y=None, height=44,
                              color=C_ACCENT))

        # ── connection mode toggle ──
        mode_row = BoxLayout(size_hint_y=None, height=44, spacing=8)
        self.btn_bt  = ToggleButton(text="Bluetooth HID", group="mode",
                                    state="down", font_size="14sp")
        self.btn_adb = ToggleButton(text="Wi-Fi ADB",     group="mode",
                                    font_size="14sp")
        self.btn_bt.bind(on_press=self._on_mode)
        self.btn_adb.bind(on_press=self._on_mode)
        mode_row.add_widget(self.btn_bt)
        mode_row.add_widget(self.btn_adb)
        root.add_widget(mode_row)

        # ── Bluetooth section ──
        self.bt_section = BoxLayout(orientation="vertical", spacing=8,
                                    size_hint_y=None, height=120)
        self.bt_section.add_widget(
            Label(text="① Enable BT on phone  ② Pair TV as Bluetooth keyboard\n"
                       "   TV → Settings → Remotes → Add Bluetooth device",
                  font_size="12sp", color=C_TEXT,
                  size_hint_y=None, height=56, halign="left",
                  text_size=(Window.width - 48, None)))
        self.lbl_bt_status = Label(text="Not connected", font_size="13sp",
                                   color=C_RED, size_hint_y=None, height=28)
        self.bt_section.add_widget(self.lbl_bt_status)
        btn_scan = Button(text="Scan / Re-register as HID device",
                          size_hint_y=None, height=36, font_size="13sp")
        btn_scan.bind(on_press=self._on_bt_scan)
        self.bt_section.add_widget(btn_scan)
        root.add_widget(self.bt_section)

        # ── Wi-Fi ADB section ──
        self.adb_section = BoxLayout(orientation="vertical", spacing=6,
                                     size_hint_y=None, height=120,
                                     opacity=0)
        ip_row = BoxLayout(size_hint_y=None, height=36, spacing=8)
        ip_row.add_widget(Label(text="TV IP:", size_hint_x=None, width=60,
                                font_size="13sp", color=C_TEXT))
        self.inp_ip = TextInput(text="192.168.1.109", multiline=False,
                                font_size="13sp")
        ip_row.add_widget(self.inp_ip)
        pt_row = BoxLayout(size_hint_y=None, height=36, spacing=8)
        pt_row.add_widget(Label(text="Port:", size_hint_x=None, width=60,
                                font_size="13sp", color=C_TEXT))
        self.inp_port = TextInput(text="5555", multiline=False,
                                  input_filter="int", font_size="13sp")
        pt_row.add_widget(self.inp_port)
        self.adb_section.add_widget(ip_row)
        self.adb_section.add_widget(pt_row)
        btn_adb_connect = Button(text="Connect via ADB",
                                 size_hint_y=None, height=36, font_size="13sp")
        btn_adb_connect.bind(on_press=self._on_adb_connect)
        self.adb_section.add_widget(btn_adb_connect)
        root.add_widget(self.adb_section)

        root.add_widget(Label())   # spacer

        btn_start = Button(text="▶  Start Camera", size_hint_y=None,
                           height=52, font_size="16sp",
                           background_color=C_ACCENT, color=(0, 0, 0, 1))
        btn_start.bind(on_press=self._on_start)
        root.add_widget(btn_start)

        self.add_widget(root)
        self._mode = "bt"

    # ── internal helpers ──
    def _on_mode(self, btn):
        if btn == self.btn_bt:
            self._mode = "bt"
            self.bt_section.opacity  = 1
            self.adb_section.opacity = 0
        else:
            self._mode = "adb"
            self.bt_section.opacity  = 0
            self.adb_section.opacity = 1

    def _on_bt_scan(self, *_):
        app = App.get_running_app()
        threading.Thread(target=app.bt_ctrl.register_hid, daemon=True).start()
        self.lbl_bt_status.text  = "Registering HID device…"
        self.lbl_bt_status.color = C_ACCENT

    def _on_adb_connect(self, *_):
        app = App.get_running_app()
        ip   = self.inp_ip.text.strip()
        port = int(self.inp_port.text.strip() or "5555")
        threading.Thread(target=app.adb_ctrl.connect,
                         args=(ip, port), daemon=True).start()

    def _on_start(self, *_):
        app = App.get_running_app()
        app.active_mode = self._mode
        self.manager.current = "camera"


# ─────────────────────────────────────────────────────────────
# Camera / live feed screen
# ─────────────────────────────────────────────────────────────
class CameraScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation="vertical")

        # Feed canvas
        self.img = Image(allow_stretch=True, keep_ratio=False)
        root.add_widget(self.img)

        # Bottom bar
        bar = BoxLayout(size_hint_y=None, height=52, spacing=10, padding=8)
        self.lbl_action = Label(text="", font_size="17sp",
                                color=C_ACCENT, bold=True)
        bar.add_widget(self.lbl_action)

        self.lbl_conn = Label(text="●  Connecting…", font_size="12sp",
                              color=C_RED, size_hint_x=None, width=160)
        bar.add_widget(self.lbl_conn)

        btn_back = Button(text="⚙", size_hint_x=None, width=48,
                          font_size="20sp")
        btn_back.bind(on_press=self._go_settings)
        bar.add_widget(btn_back)
        root.add_widget(bar)

        self.add_widget(root)

        self._cap     = None
        self._running = False
        self._thread  = None

    # ── lifecycle ──
    def on_enter(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        Clock.schedule_interval(self._update_conn_label, 1.5)

    def on_leave(self):
        self._running = False
        if self._cap:
            self._cap.release()
            self._cap = None

    # ── camera + processing thread ──
    def _loop(self):
        app  = App.get_running_app()
        cap  = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT,  720)
        cap.set(cv2.CAP_PROP_FPS, 30)
        self._cap = cap

        engine = app.gesture_engine
        action_label = ""
        label_until  = 0.0

        while self._running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            frame = cv2.flip(frame, 1)
            frame, cursor, fired, is_pinched = engine.process(frame)

            if fired:
                action_label = fired
                label_until  = time.time() + 1.2
                # send key
                if app.active_mode == "bt":
                    app.bt_ctrl.send_key(fired)
                else:
                    app.adb_ctrl.keyevent(fired)

            if time.time() > label_until:
                action_label = ""

            # draw overlay
            frame = _draw_cursor(frame, cursor, is_pinched,
                                  engine.pad_anchor)
            frame = _draw_hud(frame, action_label)

            # push to texture (must flip vertically for OpenGL)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_rgb = cv2.flip(frame_rgb, 0)
            h, w = frame_rgb.shape[:2]

            Clock.schedule_once(
                lambda dt, f=frame_rgb, fw=w, fh=h: self._blit(f, fw, fh))

        cap.release()

    def _blit(self, frame_rgb, w, h):
        tex = Texture.create(size=(w, h), colorfmt="rgb")
        tex.blit_buffer(frame_rgb.tobytes(), colorfmt="rgb", bufferfmt="ubyte")
        self.img.texture = tex

    def _update_conn_label(self, *_):
        app = App.get_running_app()
        if app.active_mode == "bt":
            connected = app.bt_ctrl.is_connected
            self.lbl_conn.text  = "●  BT HID connected" if connected else "●  BT not connected"
            self.lbl_conn.color = C_GREEN if connected else C_RED
        else:
            connected = app.adb_ctrl.is_connected
            self.lbl_conn.text  = "●  ADB connected" if connected else "●  ADB offline"
            self.lbl_conn.color = C_GREEN if connected else C_RED

    def _go_settings(self, *_):
        self.manager.current = "settings"


# ─────────────────────────────────────────────────────────────
# Overlay drawing helpers
# ─────────────────────────────────────────────────────────────
KEY_LABELS = {
    "UP":         "▲  Up",
    "DOWN":       "▼  Down",
    "LEFT":       "◀  Left",
    "RIGHT":      "▶  Right",
    "OK":         "✓  OK",
    "BACK":       "↩  Back",
    "HOME":       "⌂  Home",
    "PLAY_PAUSE": "⏯  Play/Pause",
    "VOL_UP":     "🔊 Vol+",
    "VOL_DOWN":   "🔉 Vol−",
}

MARGIN = 0.06

def _draw_cursor(frame, cursor_norm, is_pinched, anchor):
    h, w = frame.shape[:2]
    mx, my = int(MARGIN * w), int(MARGIN * h)
    cv2.rectangle(frame, (mx, my), (w - mx, h - my), (50, 80, 180), 1)

    if cursor_norm is None:
        return frame

    nx, ny = cursor_norm
    cx, cy = int(nx * w), int(ny * h)

    if anchor:
        ax, ay = int(anchor[0] * w), int(anchor[1] * h)
        cv2.circle(frame, (ax, ay), 4, (120, 120, 120), -1)
        cv2.line(frame, (ax, ay), (cx, cy), (80, 80, 80), 1)

    col = (0, 60, 255) if is_pinched else (0, 215, 255)
    cv2.circle(frame, (cx, cy), 11, col, -1)
    cv2.circle(frame, (cx, cy), 13, (255, 255, 255), 1)
    return frame


def _draw_hud(frame, label):
    h, w = frame.shape[:2]
    # Semi-transparent bottom strip
    if label:
        ov = frame.copy()
        cv2.rectangle(ov, (0, h - 52), (w, h), (10, 10, 12), -1)
        cv2.addWeighted(ov, 0.6, frame, 0.4, 0, frame)
        disp = KEY_LABELS.get(label, label)
        cv2.putText(frame, disp, (16, h - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 215, 255), 2,
                    cv2.LINE_AA)
    return frame


# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────
class GestureTVApp(App):
    def build(self):
        # Request Android permissions
        if IS_ANDROID:
            request_permissions([
                Permission.CAMERA,
                Permission.BLUETOOTH,
                Permission.BLUETOOTH_ADMIN,
                Permission.BLUETOOTH_CONNECT,
                Permission.BLUETOOTH_SCAN,
                Permission.BLUETOOTH_ADVERTISE,
            ])

        # Shared controllers
        self.bt_ctrl       = BluetoothHIDController()
        self.adb_ctrl      = ADBWifiController()
        self.gesture_engine = GestureEngine()
        self.active_mode   = "bt"

        sm = ScreenManager()
        sm.add_widget(SettingsScreen(name="settings"))
        sm.add_widget(CameraScreen(name="camera"))
        return sm

    def on_stop(self):
        self.gesture_engine.close()
        self.bt_ctrl.close()


if __name__ == "__main__":
    GestureTVApp().run()
