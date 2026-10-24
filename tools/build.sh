#!/bin/bash
# 极速水控 —— APK 构建脚本
#
# 依赖：
#   - JDK 17+（javac / keytool）
#   - Android SDK build-tools（aapt2、d8、apksigner、zipalign）
#   - android.jar（platforms/android-XX/android.jar）
#
# 用法：
#   export ANDROID_HOME=/path/to/android-sdk
#   bash tools/build.sh
#
#   或手动指定：
#   ANDROID_BUILD_TOOLS=/path/build-tools/35.0.0 \
#   ANDROID_JAR=/path/platforms/android-35/android.jar \
#   bash tools/build.sh
#
# 注意：aapt2 与 apksigner 不认含中文/空格的路径，
#       脚本会先把工程同步到系统临时目录（通常是 ASCII 路径）再编译。

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/app-src"

# 转成 Windows 风格路径（Git Bash 下 /d/... 这类 aapt2 不认）
winpath() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$1" | sed 's|\\|/|g'
  else
    echo "$1"
  fi
}

# keytool 未必在 PATH 里（有些 JDK 只把 javac/java 放进 PATH）
KEYTOOL="keytool"
if [ -n "$JAVA_HOME" ] && [ -x "$JAVA_HOME/bin/keytool" ]; then
  KEYTOOL="$JAVA_HOME/bin/keytool"
elif ! command -v keytool >/dev/null 2>&1; then
  for c in "/c/Program Files/Java"/*/bin/keytool.exe "/c/Program Files/Eclipse Adoptium"/*/bin/keytool.exe; do
    [ -x "$c" ] && KEYTOOL="$c" && break
  done
fi

BT="${ANDROID_BUILD_TOOLS:-${ANDROID_HOME:-}/build-tools/35.0.0}"
AJAR="${ANDROID_JAR:-${ANDROID_HOME:-}/platforms/android-35/android.jar}"

AAPT2="$BT/aapt2";     [ -f "$BT/aapt2.exe" ] && AAPT2="$BT/aapt2.exe"
D8="$BT/d8";           [ -f "$BT/d8.bat" ] && D8="$BT/d8.bat"
ZIPALIGN="$BT/zipalign"; [ -f "$BT/zipalign.exe" ] && ZIPALIGN="$BT/zipalign.exe"
APKSIGNER="$BT/apksigner"; [ -f "$BT/apksigner.bat" ] && APKSIGNER="$BT/apksigner.bat"

if [ ! -f "$AAPT2" ]; then
  echo "找不到 aapt2：$BT"
  echo "请设置 ANDROID_BUILD_TOOLS 或 ANDROID_HOME"
  exit 1
fi
if [ ! -f "$AJAR" ]; then
  echo "找不到 android.jar：$AJAR"
  echo "请设置 ANDROID_JAR 或 ANDROID_HOME"
  exit 1
fi

WORK="$(winpath "${TEMP:-${TMPDIR:-/tmp}}")/fastwater-build"
OUT="$WORK/out"
KS="$WORK/debug.keystore"

mkdir -p "$WORK"
rm -rf "$WORK/src" "$OUT"
cp -r "$SRC" "$WORK/src"
mkdir -p "$OUT/classes"

VER=$(sed -n 's/.*android:versionName="\([^"]*\)".*/\1/p' "$WORK/src/AndroidManifest.xml")

echo "[1/7] 编译资源"
"$AAPT2" compile --dir "$WORK/src/res" -o "$OUT/res.zip"

echo "[2/7] 链接资源 + assets"
"$AAPT2" link \
  -o "$OUT/base.apk" \
  -I "$AJAR" \
  --manifest "$WORK/src/AndroidManifest.xml" \
  -R "$OUT/res.zip" \
  -A "$WORK/src/assets" \
  --min-sdk-version 24 \
  --target-sdk-version 30 \
  --auto-add-overlay

echo "[3/7] 编译 Java"
javac -nowarn -source 8 -target 8 \
  -classpath "$AJAR" \
  -encoding UTF-8 \
  -d "$OUT/classes" \
  $(find "$WORK/src/java" -name "*.java")

echo "[4/7] d8 转 dex"
"$D8" --lib "$AJAR" --min-api 24 --output "$OUT" \
  $(find "$OUT/classes" -name "*.class")

echo "[5/7] 打包 dex"
python "$ROOT/tools/pack_dex.py" "$OUT/base.apk" "$OUT/classes.dex" "$OUT/aligned_in.apk"

echo "[6/7] zipalign"
"$ZIPALIGN" -f -p 4 "$OUT/aligned_in.apk" "$OUT/aligned.apk"

echo "[7/7] 签名"
if [ ! -f "$KS" ]; then
  if ! "$KEYTOOL" -genkeypair -v -keystore "$KS" -alias fastwater -keyalg RSA -keysize 2048 \
      -validity 10000 -storepass fastwater -keypass fastwater \
      -dname "CN=FastWater, OU=dev, O=dev, L=NA, S=NA, C=CN"; then
    echo "生成签名失败，检查 keytool（可设置 JAVA_HOME）"
    exit 1
  fi
fi
"$APKSIGNER" sign --ks "$KS" --ks-key-alias fastwater \
  --ks-pass pass:fastwater --key-pass pass:fastwater \
  --out "$OUT/final.apk" "$OUT/aligned.apk"

if [ ! -f "$OUT/final.apk" ]; then
  echo "签名失败：$OUT/final.apk 未生成"
  exit 1
fi

mkdir -p "$ROOT/dist"
cp "$OUT/final.apk" "$ROOT/dist/fastwater-v${VER}.apk"

echo ""
echo "构建完成: $ROOT/dist/fastwater-v${VER}.apk"
ls -lh "$ROOT/dist/fastwater-v${VER}.apk"
