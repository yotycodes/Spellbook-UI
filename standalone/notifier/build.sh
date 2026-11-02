#!/bin/bash
# Build the notifier helper into Spellbook Beta.app (Contents/Helpers) with the Beta icon, then re-sign the app.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="${1:-$HOME/Applications/Spellbook Beta.app}"
H="$APP/Contents/Helpers/Spellbook Beta.app"
mkdir -p "$H/Contents/MacOS" "$H/Contents/Resources"
swiftc -O "$HERE/SpellbookNotifier.swift" -o "$H/Contents/MacOS/SpellbookNotifier"
cp "$APP/Contents/Resources/AppIcon.icns" "$H/Contents/Resources/AppIcon.icns"
cat > "$H/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Spellbook Beta</string>
<key>CFBundleDisplayName</key><string>Spellbook Beta</string>
<key>CFBundleIdentifier</key><string>com.yoty.spellbook.beta.notifier</string>
<key>CFBundleExecutable</key><string>SpellbookNotifier</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1.0</string>
<key>LSUIElement</key><true/>
<key>LSMinimumSystemVersion</key><string>12.0</string>
</dict></plist>
PL
codesign --force -s - "$H"
codesign --force --deep -s - "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$H"
echo "built $H"
