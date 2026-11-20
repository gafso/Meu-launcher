#!/usr/bin/env bash
# Build script for Orbit Launcher (AIR SDK 51+)
set -euo pipefail
: "${AIR_SDK:?defina AIR_SDK}"
: "${ANDROID_JAR:?defina ANDROID_JAR}"
KEYSTORE="${KEYSTORE:-keystore.p12}"
STOREPASS="${STOREPASS:-changeit}"
ARCH="${ARCH:-armv8}"
cd "$(dirname "$0")"
ROOT="$PWD"
ADT="java -jar $AIR_SDK/lib/adt.jar"

SDK_VER=$(sed -n 's:.*<version>\(.*\)</version>.*:\1:p' "$AIR_SDK/air-sdk-description.xml" | head -1)
SDK_MAJOR="${SDK_VER%%.*}"
rest="${SDK_VER#*.}"; SDK_MINOR="${rest%%.*}"
NS="$SDK_MAJOR.$SDK_MINOR"
echo "AIR SDK $SDK_VER (namespace $NS)"

rm -rf build && mkdir -p build/classes build/ane_android build/ane_default build/ext build/app
sed -e "s/NS_VERSION/$NS/" -e "s/VERSION_NUMBER/${VERSION_NUMBER:-1.0.0}/" app.xml > build/app/app.xml
sed "s/NS_VERSION/$NS/" ane/extension.xml > build/extension.xml

echo "==> Compilando Java do ANE"
javac -source 8 -target 8 -Xlint:-options -d build/classes \
  -cp "$AIR_SDK/lib/android/FlashRuntimeExtensions.jar:$ANDROID_JAR" \
  ane/android/src/com/orbit/air/*.java
jar cf build/ane_android/bridge.jar -C build/classes .

echo "==> Compilando SWC do Bridge"
"$AIR_SDK/bin/acompc" -source-path ane/as -include-classes com.orbit.air.Bridge -output build/bridge.swc
unzip -o -q build/bridge.swc library.swf -d build/ane_android
cp build/ane_android/library.swf build/ane_default/library.swf

echo "==> Empacotando ANE"
$ADT -package -target ane build/ext/bridge.ane build/extension.xml \
  -swc build/bridge.swc \
  -platform Android-ARM   -C build/ane_android bridge.jar library.swf \
  -platform Android-ARM64 -C build/ane_android bridge.jar library.swf \
  -platform default       -C build/ane_default library.swf

echo "==> Compilando Main.swf"
"$AIR_SDK/bin/amxmlc" -source-path src -external-library-path+=build/bridge.swc \
  -default-size 1280 720 -output build/app/Main.swf src/Main.as
cp -r assets build/app/assets 2>/dev/null || true

echo "==> Empacotando APK"
$ADT -package -target apk-captive-runtime -arch "$ARCH" \
  -storetype pkcs12 -keystore "$KEYSTORE" -storepass "$STOREPASS" \
  build/Orbit.apk build/app/app.xml \
  -C build/app Main.swf -C build/app assets \
  -extdir build/ext

ls -la build/Orbit.apk
echo "Pronto: build/Orbit.apk"
