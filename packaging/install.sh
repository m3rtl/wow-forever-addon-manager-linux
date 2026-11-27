#!/bin/sh
# Installiert den Addon-Manager fuer Pakete (AUR, Flatpak) nach $DESTDIR$PREFIX.
# Aufruf: packaging/install.sh [PREFIX] [KANAL]    Standard: /usr package
#   AUR:     DESTDIR="$pkgdir" sh packaging/install.sh /usr aur
#   Flatpak: sh packaging/install.sh /app flatpak
set -eu
src=$(cd "$(dirname "$0")/.." && pwd)
prefix=${1:-/usr}
channel=${2:-package}
id=io.github.m3rtl.WowForeverAddonManager
name=wow-forever-addon-manager
root="${DESTDIR:-}$prefix"
lib="$root/share/$name"

install -d "$lib" "$lib/assets" "$root/bin"
for f in "$src"/wfa_*.py; do
    install -m644 "$f" "$lib/"
done
install -m644 "$src/$name.py" "$src/CHANGELOG.md" "$lib/"
cp -R "$src/assets/." "$lib/assets/"
find "$lib/assets" -type d -exec chmod 755 {} + -o -type f -exec chmod 644 {} +
# Marker: Programm wird von der Paketverwaltung aktualisiert, Daten liegen in den XDG-Ordnern
printf '%s\n' "$channel" > "$lib/PACKAGED"
chmod 644 "$lib/PACKAGED"

cat > "$root/bin/$name" <<LAUNCHER
#!/bin/sh
exec python3 $prefix/share/$name/$name.py "\$@"
LAUNCHER
chmod 755 "$root/bin/$name"

install -Dm644 "$src/packaging/$id.desktop" "$root/share/applications/$id.desktop"
install -Dm644 "$src/packaging/$id.metainfo.xml" "$root/share/metainfo/$id.metainfo.xml"
install -Dm644 "$src/assets/icon.svg" "$root/share/icons/hicolor/scalable/apps/$id.svg"

if [ "${NO_COMPILE:-0}" != 1 ] && command -v python3 >/dev/null; then
    python3 -m compileall -q -d "$prefix/share/$name" "$lib" >/dev/null
fi
