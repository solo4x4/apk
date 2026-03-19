"""
gesture_engine_fallback.py
Pure-OpenCV hand gesture detector – fallback for devices / build
environments where mediapipe cannot be installed.

Replaces gesture_engine.py – just rename it:
    mv gesture_engine_fallback.py gesture_engine.py

Detection strategy
──────────────────
1. Skin-colour segmentation (HSV + YCrCb)
2. Largest contour → convex hull → defect analysis
3. Finger count drives the same gesture table as the mediapipe version.
4. Index-finger tip is estimated as the topmost hull point when count == 1.

Limitations vs mediapipe: less accurate in varied lighting; no wrist-based
anchor → trackpad sensitivity is lower.
"""

import time
import cv2
import numpy as np

# ─────────────────────────────────────────────────────────────
# Config (mirrors main engine)
# ─────────────────────────────────────────────────────────────
SMOOTHING         = 0.28
DPAD_THRESHOLD    = 0.13
DPAD_MIN_INTERVAL = 0.35
GESTURE_COOLDOWN  = 2.2

# Skin colour ranges (HSV)
HSV_LOW  = np.array([0,  20,  70], dtype=np.uint8)
HSV_HIGH = np.array([20, 255, 255], dtype=np.uint8)

HAND_CONNECTIONS = []  # not used in contour mode; kept for API compat


# ─────────────────────────────────────────────────────────────
# EMA + Trackpad (same as main engine)
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


class Trackpad:
    def __init__(self):
        self._ax = self._ay = None
        self._last = 0.0

    def reset(self):
        self._ax = self._ay = None

    def update(self, nx, ny):
        if self._ax is None:
            self._ax, self._ay = nx, ny
            return None
        dx = nx - self._ax
        dy = ny - self._ay
        if (dx ** 2 + dy ** 2) * 4 < DPAD_THRESHOLD:
            return None
        now = time.time()
        if now - self._last < DPAD_MIN_INTERVAL:
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
# Skin mask helper
# ─────────────────────────────────────────────────────────────
def _skin_mask(bgr):
    blurred = cv2.GaussianBlur(bgr, (5, 5), 0)
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
    mask_hsv = cv2.inRange(hsv, HSV_LOW, HSV_HIGH)

    ycrcb = cv2.cvtColor(blurred, cv2.COLOR_BGR2YCrCb)
    mask_y = cv2.inRange(ycrcb,
                         np.array([0,  133,  77], dtype=np.uint8),
                         np.array([255, 173, 127], dtype=np.uint8))

    mask = cv2.bitwise_and(mask_hsv, mask_y)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return mask


# ─────────────────────────────────────────────────────────────
# Finger counter from convex defects
# ─────────────────────────────────────────────────────────────
def _count_fingers(contour, hull_idx, defects, h):
    if defects is None:
        return 0
    count = 0
    for d in defects:
        s, e, f, depth = d[0]
        start = tuple(contour[s][0])
        end   = tuple(contour[e][0])
        far   = tuple(contour[f][0])
        depth_px = depth / 256.0

        # Angle at the defect point (law of cosines)
        a = np.linalg.norm(np.subtract(start, end))
        b = np.linalg.norm(np.subtract(far, start))
        c = np.linalg.norm(np.subtract(far, end))
        if b * c == 0:
            continue
        angle = np.arccos((b**2 + c**2 - a**2) / (2 * b * c + 1e-6))

        if angle < np.pi / 2 and depth_px > h * 0.04:
            count += 1
    return count


# ─────────────────────────────────────────────────────────────
# Main engine (same public API as gesture_engine.GestureEngine)
# ─────────────────────────────────────────────────────────────
class GestureEngine:
    def __init__(self):
        self._ema        = EMA()
        self._pad        = Trackpad()
        self._last_btn   = ""
        self._last_btn_t = 0.0

    def process(self, bgr):
        h, w = bgr.shape[:2]
        frame = bgr.copy()
        mask  = _skin_mask(bgr)

        # draw mask outline for feedback
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            self._ema.reset()
            self._pad.reset()
            return frame, None, None, False

        cnt = max(contours, key=cv2.contourArea)
        if cv2.contourArea(cnt) < 5000:
            self._ema.reset()
            self._pad.reset()
            return frame, None, None, False

        cv2.drawContours(frame, [cnt], -1, (80, 200, 120), 2)

        # Convex hull & defects
        hull_idx = cv2.convexHull(cnt, returnPoints=False)
        hull_pts = cv2.convexHull(cnt)
        cv2.drawContours(frame, [hull_pts], -1, (0, 215, 255), 1)

        defects = None
        if hull_idx is not None and len(hull_idx) > 3:
            try:
                defects = cv2.convexityDefects(cnt, hull_idx)
            except cv2.error:
                pass

        n_fingers = _count_fingers(cnt, hull_idx, defects, h)

        # Topmost point as fingertip proxy
        topmost = tuple(cnt[cnt[:, :, 1].argmin()][0])
        nx = topmost[0] / w
        ny = topmost[1] / h
        sx, sy = self._ema.update(nx, ny)

        now    = time.time()
        fired  = None
        cursor = None

        # ── POINTER: 0 or 1 extended finger ─────────────────
        if n_fingers <= 1:
            cursor    = (sx, sy)
            direction = self._pad.update(sx, sy)
            if direction:
                fired = direction
        # ── GESTURES ─────────────────────────────────────────
        else:
            self._pad.reset()
            raw = None
            if n_fingers == 0:
                raw = "BACK"
            elif n_fingers >= 4:
                raw = "PLAY_PAUSE"
            elif n_fingers == 3:
                raw = "HOME"

            if raw:
                if raw != self._last_btn or (now - self._last_btn_t) > GESTURE_COOLDOWN:
                    self._last_btn   = raw
                    self._last_btn_t = now
                    fired = raw

        # Finger count label
        cv2.putText(frame, f"Fingers: {n_fingers}", (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 215, 255), 2)

        return frame, cursor, fired, False

    @property
    def pad_anchor(self):
        return self._pad.anchor

    def close(self):
        pass
