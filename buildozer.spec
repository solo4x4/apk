[app]
title = Gesture TV Remote
package.name = gesturetvremote
package.domain = com.gesturetv

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,task

version = 1.0.0

requirements = python3,kivy==2.3.0,numpy,opencv-python,mediapipe

android.permissions = CAMERA,BLUETOOTH,BLUETOOTH_ADMIN,BLUETOOTH_CONNECT,BLUETOOTH_SCAN,BLUETOOTH_ADVERTISE,INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE

android.api = 33
android.minapi = 28
android.ndk = 25b
android.ndk_api = 28
android.sdk = 33
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 1
