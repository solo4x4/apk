[app]
title           = Gesture TV Remote
package.name    = gesturetvremote
package.domain  = com.gesturetv

source.dir      = .
source.include_exts = py,png,jpg,kv,atlas,task

version         = 1.0.0

# ─── Dependencies ────────────────────────────────────────────
# Note: mediapipe wheels for Android ARM64 may need to be fetched
# from PyPI. If the build fails, substitute with opencv-python +
# a pure-Python hand detector (see gesture_engine_fallback.py).
requirements = python3,\
               kivy==2.3.0,\
               numpy,\
               opencv-python,\
               mediapipe

# ─── Android permissions ─────────────────────────────────────
android.permissions = \
    CAMERA,\
    BLUETOOTH,\
    BLUETOOTH_ADMIN,\
    BLUETOOTH_CONNECT,\
    BLUETOOTH_SCAN,\
    BLUETOOTH_ADVERTISE,\
    INTERNET,\
    ACCESS_NETWORK_STATE,\
    ACCESS_WIFI_STATE

# ─── Android API ─────────────────────────────────────────────
android.api         = 33
android.minapi      = 28          # BluetoothHidDevice requires API 28+
android.ndk         = 25b
android.sdk         = 33
android.ndk_api     = 28

android.archs       = arm64-v8a  # BluetoothHidDevice is 64-bit only

# ─── Features ────────────────────────────────────────────────
android.uses_library    = android.bluetooth
android.add_aars        =
android.gradle_dependencies =

# Required hardware features
android.manifest.extra_tags = \
    <uses-feature android:name="android.hardware.bluetooth" android:required="true"/>\
    <uses-feature android:name="android.hardware.camera" android:required="true"/>

# Bundle the adb binary for Wi-Fi ADB fallback
# Download from https://developer.android.com/tools/releases/platform-tools
# Extract adb binary (ARM64), rename to adb-arm64, place here.
android.add_src         =
android.assets          = adb-arm64

# ─── Build options ───────────────────────────────────────────
[buildozer]
log_level   = 2
warn_on_root = 1

[app:android]
orientation = landscape

# ─── Presplash / icon ────────────────────────────────────────
# presplash.filename = %(source.dir)s/presplash.png
# icon.filename      = %(source.dir)s/icon.png
