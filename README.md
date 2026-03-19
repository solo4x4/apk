# Gesture TV Remote – Android (Python/Kivy)

Control your **Google TV** with hand gestures, using your Android phone as the remote.

---

## ⚡ How Bluetooth Works Here

> **ADB does not support Bluetooth natively.**

Instead, this app uses the **Android Bluetooth HID Device profile** (API 28+):

```
Phone (HID peripheral)  ←→  Google TV (HID host)
      acts as a Bluetooth keyboard
```

The phone registers itself as a Bluetooth keyboard. Google TV pairs with it
exactly like any other Bluetooth remote. No ADB, no developer mode needed on the TV.

A **Wi-Fi ADB** fallback is also built in for power users who already have ADB over TCP/IP set up.

---

## Architecture

```
gesture_tv_android/
├── main.py                    # Kivy app, UI screens, camera loop
├── gesture_engine.py          # MediaPipe hand tracking (same logic as desktop)
├── gesture_engine_fallback.py # OpenCV-only fallback (if mediapipe fails to build)
├── bt_hid.py                  # Bluetooth HID Device controller (pyjnius)
├── adb_wifi.py                # Wi-Fi ADB controller (fallback)
├── buildozer.spec             # APK build configuration
└── adb-arm64                  # (optional) bundled adb binary for Wi-Fi mode
```

### Gesture → Key mapping

| Gesture | Mode | Key sent |
|---------|------|----------|
| Index finger up – move | Pointer | ▲▼◀▶ DPAD |
| Pinch and release | Pointer | ✓ OK / Select |
| Fast vertical swipe | Pointer | Volume Up/Down |
| Fist (0 fingers) | Gesture | Back |
| Open palm (4+ fingers) | Gesture | Play / Pause |
| 3 fingers (index+mid+ring) | Gesture | Home |

---

## Requirements

### Build machine (Linux recommended)
```
Python 3.10+
buildozer          pip install buildozer
Cython             pip install Cython
Android SDK/NDK    auto-installed by buildozer
```

### Android device
- Android 9.0+ (API 28) – required for `BluetoothHidDevice`
- Bluetooth enabled
- Camera permission granted

### Google TV
- No developer mode needed for BT HID mode ✓
- For Wi-Fi ADB: Settings → System → Developer Options → USB Debugging ON

---

## Build Steps

### 1 – Install buildozer
```bash
pip install buildozer cython
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip \
     autoconf libtool pkg-config zlib1g-dev libncurses5-dev \
     libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev
```

### 2 – (Optional) Bundle the adb binary for Wi-Fi fallback
```bash
# Download Android Platform Tools for Linux-arm64 from:
# https://developer.android.com/tools/releases/platform-tools
# Extract and copy:
cp platform-tools/adb gesture_tv_android/adb-arm64
```

### 3 – Build the APK
```bash
cd gesture_tv_android
buildozer android debug
```

First build downloads the Android SDK/NDK (~2 GB) and takes 15–30 min.
Subsequent builds take ~2 min.

Output: `bin/gesturetvremote-1.0.0-arm64-v8a-debug.apk`

### 4 – Install on your Android phone
```bash
buildozer android deploy run
# or manually:
adb install bin/gesturetvremote-*.apk
```

---

## Pairing with Google TV (Bluetooth HID mode)

1. Open the app → tap **"Scan / Re-register as HID device"**
2. On your **Google TV**:
   `Settings → Remotes & Accessories → Add accessory`
3. TV will discover **"Gesture TV Remote"** → select it → Pair
4. Green dot appears in the app → you're connected!
5. Point your index finger at the camera to navigate.

> The pairing only needs to be done once. After that the TV remembers the phone.

---

## Wi-Fi ADB mode (alternative)

1. On Google TV: enable ADB over Wi-Fi  
   `Settings → System → About → Build number (tap 7×) → Developer options → USB Debugging`
2. Open the app → switch to **"Wi-Fi ADB"** tab
3. Enter the TV's IP address → **Connect**
4. Done — gestures send ADB keyevents over your local network

---

## mediapipe Build Issues

If `mediapipe` fails to compile for ARM64 during `buildozer android debug`:

1. Replace `gesture_engine.py` with the fallback version:
   ```bash
   cp gesture_engine_fallback.py gesture_engine.py
   ```
2. Remove `mediapipe` from `requirements` in `buildozer.spec`
3. Rebuild

The fallback uses skin-colour segmentation + convex hull finger counting.
It's less accurate but has zero native dependencies.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Bluetooth HID not connected" | Re-register HID, then re-pair from TV settings |
| Camera black screen | Grant Camera permission in Android Settings |
| mediapipe crash on start | Switch to `gesture_engine_fallback.py` |
| ADB "failed to connect" | Ensure TV and phone on same Wi-Fi; recheck TV IP |
| Gestures too sensitive | Increase `DPAD_THRESHOLD` / `PINCH_THRESH` in `gesture_engine.py` |
| Gestures fire too slowly | Decrease `GESTURE_COOLDOWN` / `DPAD_MIN_INTERVAL` |

---

## Permissions Used

| Permission | Why |
|-----------|-----|
| `CAMERA` | Hand tracking via front/back camera |
| `BLUETOOTH` + `BLUETOOTH_ADMIN` | Bluetooth stack access |
| `BLUETOOTH_CONNECT` (API 31+) | Connect to paired HID host |
| `BLUETOOTH_SCAN` (API 31+) | Discover TV during pairing |
| `BLUETOOTH_ADVERTISE` (API 31+) | Advertise as HID peripheral |
| `INTERNET` + `ACCESS_WIFI_STATE` | Wi-Fi ADB fallback |
