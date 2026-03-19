"""
gesture_engine.py
MediaPipe-based hand gesture recogniser.
Identical logic to the desktop version but without ADB calls –
it only classifies gestures and returns them as strings.
"""

import os
import sys
import time
import urllib.request

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.tasks.python.components.containers import NormalizedLandmark

# ─────────────────────────────────────────────────────────────
# Config  (mirrors desktop script)
# ─────────────────────────────────────────────────────────────
SMOOTHING         = 0.28
DPAD_THRESHOLD    = 0.13
DPAD_MIN_INTERVAL = 0.35
PINCH_THRESH      = 0.038
PINCH_COOLDOWN    = 1.0
GESTURE_COOLDOWN  = 2.2

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
)

# On Android the writable data dir is accessed via the app's files dir;
# fall back to script directory on desktop.
def _model_path() -> str:
    try:
        from android.storage import app_storage_path  # type: ignore
        base = app_storage_path()
    except ImportError:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "hand_landmarker.task")


HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (0,9),(9,10),(10,11),(11,12),
    (0,13),(13,14),(14,15),(15,16),
    (0,17),(17,18),(18,19),(19,20),
    (5,9),(9,13),(13,17),(5,17),
]


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _dist(a: NormalizedLandmark, b: NormalizedLandmark) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def _tip_up(lm, tip, pip) -> bool:
    """Finger extended: tip y is above (lower value) than pip y."""
    return lm[tip].y < lm[pip].y


def _fingers_ext(lm) -> list:
    return [_tip_up(lm, t, p) for t, p in [(8, 6), (12, 10), (16, 14), (20, 18)]]


# ─────────────────────────────────────────────────────────────
# EMA smoother
# ─────────────────────────────────────────────────────────────
class EMA:
    def __init__(self, alpha=SMOOTHING):
        self.a = alpha
        self.x = self.y = None

    def update(self, x, y):
        if self.x is None:
            self.x, self.y = x, y
        else:
            self.x += self.a * (x - self.x)
            self.y += self.a * (y - self.y)
        return self.x, self.y

    def reset(self):
        self.x = self.y = None


# ─────────────────────────────────────────────────────────────
# Virtual trackpad
# ─────────────────────────────────────────────────────────────
class Trackpad:
    def __init__(self):
        self._ax = self._ay = None
        self._last = 0.0

    def reset(self):
        self._ax = self._ay = None

    def update(self, nx, ny):
        """Returns direction string or None."""
        if self._ax is None:
            self._ax, self._ay = nx, ny
            return None
        dx = nx - self._ax
        dy = ny - self._ay
        if (dx ** 2 + dy ** 2) * 4 < DPAD_THRESHOLD:
            return None
        now = time.time()
        if (now - self._last) < DPAD_MIN_INTERVAL:
            return None
        direction = (
            ("LEFT" if dx > 0 else "RIGHT")
            if abs(dx) >= abs(dy)
            else ("DOWN" if dy > 0 else "UP")
        )
        self._ax, self._ay = nx, ny
        self._last = now
        return direction

    @property
    def anchor(self):
        return (self._ax, self._ay) if self._ax is not None else None


# ─────────────────────────────────────────────────────────────
# Model download
# ─────────────────────────────────────────────────────────────
def _ensure_model(path: str):
    if os.path.isfile(path):
        return
    print(f"[GestureEngine] Downloading hand landmark model to {path} …")
    try:
        urllib.request.urlretrieve(MODEL_URL, path)
        print("[GestureEngine] Model downloaded successfully.")
    except Exception as exc:
        raise RuntimeError(
            f"Cannot download model: {exc}\n"
            f"Download manually from:\n  {MODEL_URL}\n"
            f"and place as: {path}"
        ) from exc


# ─────────────────────────────────────────────────────────────
# Main gesture engine
# ─────────────────────────────────────────────────────────────
class GestureEngine:
    """
    Processes a BGR camera frame.
    Returns (annotated_frame, cursor_norm | None, key_name | None, is_pinched).
    key_name is one of: UP DOWN LEFT RIGHT OK BACK HOME PLAY_PAUSE VOL_UP VOL_DOWN
    """

    def __init__(self):
        model_path = _model_path()
        _ensure_model(model_path)

        options = mp_vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=model_path),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.6,
            min_hand_presence_confidence=0.6,
            min_tracking_confidence=0.55,
        )
        self._lm         = mp_vision.HandLandmarker.create_from_options(options)
        self._ema        = EMA()
        self._pad        = Trackpad()
        self._pinch_down = False
        self._last_pinch = 0.0
        self._last_btn   = ""
        self._last_btn_t = 0.0
        self._prev_y     = None
        self._prev_t     = None
        self._ts_ms      = 0     # synthetic monotonic ts for VIDEO mode

    # ── skeleton overlay ─────────────────────────────────────
    @staticmethod
    def _draw_hand(frame, lm, h, w):
        pts = [(int(l.x * w), int(l.y * h)) for l in lm]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], (80, 200, 120), 1, cv2.LINE_AA)
        for i, (px, py) in enumerate(pts):
            r = 5 if i in (4, 8, 12, 16, 20) else 3
            cv2.circle(frame, (px, py), r, (0, 240, 100), -1)
            cv2.circle(frame, (px, py), r, (255, 255, 255), 1)

    # ── gesture classifier ───────────────────────────────────
    @staticmethod
    def _classify_gesture(lm) -> str | None:
        ext = _fingers_ext(lm)
        n   = sum(ext)
        idx, mid, ring, _ = ext
        if n == 0:
            return "BACK"
        if n >= 4:
            return "PLAY_PAUSE"
        if n == 3 and idx and mid and ring:
            return "HOME"
        return None

    # ── public process ───────────────────────────────────────
    def process(self, bgr):
        h, w    = bgr.shape[:2]
        rgb     = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        mp_img  = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        self._ts_ms += 33
        result  = self._lm.detect_for_video(mp_img, self._ts_ms)
        frame   = bgr.copy()
        cursor  = None
        fired   = None

        if not result.hand_landmarks:
            self._ema.reset()
            self._pad.reset()
            self._pinch_down = False
            self._prev_y     = None
            return frame, None, None, False

        lm  = result.hand_landmarks[0]
        ext = _fingers_ext(lm)
        n   = sum(ext)
        idx = ext[0]

        self._draw_hand(frame, lm, h, w)
        now = time.time()

        # ── POINTER MODE: only index finger up ───────────────
        if n == 1 and idx:
            sx, sy = self._ema.update(lm[8].x, lm[8].y)
            cursor = (sx, sy)

            direction = self._pad.update(sx, sy)
            if direction:
                fired = direction

            # Pinch → OK
            is_pinched = _dist(lm[4], lm[8]) < PINCH_THRESH
            if self._pinch_down and not is_pinched:
                if (now - self._last_pinch) > PINCH_COOLDOWN:
                    fired = "OK"
                    self._last_pinch = now
            self._pinch_down = is_pinched

            # Velocity-swipe → Volume
            if self._prev_y is not None:
                dt = now - self._prev_t
                if dt > 0:
                    vy = (sy - self._prev_y) / dt
                    if abs(vy) > 1.5 and (now - self._last_btn_t) > 0.5:
                        fired = "VOL_DOWN" if vy > 0 else "VOL_UP"
                        self._last_btn_t = now
            self._prev_y = sy
            self._prev_t = now

        # ── GESTURE MODE ─────────────────────────────────────
        else:
            self._pad.reset()
            self._ema.reset()
            self._prev_y = None
            cursor       = None

            raw = self._classify_gesture(lm)
            if raw:
                if raw != self._last_btn or (now - self._last_btn_t) > GESTURE_COOLDOWN:
                    self._last_btn   = raw
                    self._last_btn_t = now
                    fired = raw

        return frame, cursor, fired, self._pinch_down

    @property
    def pad_anchor(self):
        return self._pad.anchor

    def close(self):
        try:
            self._lm.close()
        except Exception:
            pass
