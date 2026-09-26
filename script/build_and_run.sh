#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="4G Bridge"
BUNDLE_ID="com.pameda.fourgbridge"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
elif command -v python3.14 >/dev/null 2>&1; then
  PYTHON="$(command -v python3.14)"
else
  PYTHON="$(command -v python3)"
fi
APP_BUNDLE="$ROOT_DIR/dist/$APP_NAME.app"
APP_BINARY="$APP_BUNDLE/Contents/MacOS/$APP_NAME"
ARTIFACTS="$ROOT_DIR/artifacts"

build_app() {
  "$ROOT_DIR/script/test.sh"
  /bin/rm -rf "$ROOT_DIR/build" "$APP_BUNDLE"
  cd "$ROOT_DIR/packaging"
  "$PYTHON" py2app_setup.py py2app --arch=arm64

  while IFS= read -r -d '' component; do
    if /usr/bin/file "$component" | /usr/bin/grep -q 'Mach-O'; then
      /usr/bin/codesign --force --sign - --timestamp=none "$component"
    fi
  done < <(/usr/bin/find "$APP_BUNDLE" -type f -perm -111 -print0)
  /usr/bin/codesign --force --sign - --timestamp=none "$APP_BUNDLE"
}

verify_app() {
  /usr/bin/codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"
  /usr/bin/codesign -dvvv --entitlements :- "$APP_BUNDLE"
  /usr/bin/plutil -lint "$APP_BUNDLE/Contents/Info.plist"
  [[ "$(/usr/bin/plutil -extract LSUIElement raw -o - "$APP_BUNDLE/Contents/Info.plist")" == "true" ]]
  [[ "$(/usr/bin/plutil -extract CFBundleIdentifier raw -o - "$APP_BUNDLE/Contents/Info.plist")" == "$BUNDLE_ID" ]]
  /usr/bin/file "$APP_BINARY" | /usr/bin/grep -q 'arm64'
  "$PYTHON" "$ROOT_DIR/script/verify_ui.py" "$APP_BINARY" "$ARTIFACTS/ui-smoke"
}

package_dmg() {
  local stage mount_point dmg sha_file
  mkdir -p "$ARTIFACTS"
  stage="$(/usr/bin/mktemp -d /private/tmp/4g-bridge-dmg.XXXXXX)"
  mount_point="$(/usr/bin/mktemp -d /private/tmp/4g-bridge-mount.XXXXXX)"
  dmg="$ARTIFACTS/4G-Bridge-0.1.10-arm64.dmg"
  sha_file="$dmg.sha256"
  trap '/bin/rm -rf "$stage" "$mount_point"' RETURN
  /bin/cp -R "$APP_BUNDLE" "$stage/"
  /bin/ln -s /Applications "$stage/Applications"
  /usr/bin/hdiutil create -volname "4G Bridge" -srcfolder "$stage" -ov -format UDZO "$dmg"
  /usr/bin/hdiutil attach -readonly -nobrowse -mountpoint "$mount_point" "$dmg"
  [[ -d "$mount_point/$APP_NAME.app" ]]
  /usr/bin/hdiutil detach "$mount_point"
  (cd "$ARTIFACTS" && /usr/bin/shasum -a 256 "$(basename "$dmg")") > "$sha_file"
  echo "$dmg"
  echo "$sha_file"
}

/usr/bin/pkill -x "$APP_NAME" >/dev/null 2>&1 || true
build_app
verify_app

case "$MODE" in
  run)
    /usr/bin/open -n "$APP_BUNDLE"
    ;;
  --debug|debug)
    /usr/bin/lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    /usr/bin/open -n "$APP_BUNDLE"
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    /usr/bin/open -n "$APP_BUNDLE"
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    /usr/bin/open -n "$APP_BUNDLE"
    /bin/sleep 2
    /usr/bin/pgrep -x "$APP_NAME" >/dev/null
    ;;
  --package|package)
    package_dmg
    ;;
  --build-only|build-only)
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--package|--build-only]" >&2
    exit 2
    ;;
esac
