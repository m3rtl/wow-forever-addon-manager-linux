#!/bin/sh
# Setzt pkgver und sha256sums im PKGBUILD auf ein veroeffentlichtes Tag und erzeugt .SRCINFO neu.
# Aufruf: packaging/aur/update.sh [VERSION]   (Standard: __version__ aus wfa_core.py)
# Danach PKGBUILD und .SRCINFO ins AUR-Repo (ssh://aur@aur.archlinux.org/wow-forever-addon-manager.git) kopieren.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
ver=${1:-$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$here/../../wfa_core.py")}
url="https://github.com/m3rtl/wow-forever-addon-manager-linux/archive/refs/tags/v$ver.tar.gz"
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
curl -fsSL "$url" -o "$tmp"
tar -tzf "$tmp" | grep -q '/packaging/install.sh$' || { echo "Tag v$ver enthält packaging/install.sh nicht." >&2; exit 1; }
sum=$(sha256sum "$tmp" | cut -d' ' -f1)
old=$(sed -n 's/^pkgver=//p' "$here/PKGBUILD")
sed -i -e "s/^pkgver=.*/pkgver=$ver/" -e "s/^sha256sums=.*/sha256sums=('$sum')/" "$here/PKGBUILD"
[ "$old" = "$ver" ] || sed -i 's/^pkgrel=.*/pkgrel=1/' "$here/PKGBUILD"
bash "$here/srcinfo.sh" > "$here/.SRCINFO"
echo "PKGBUILD: $ver ($sum)"
