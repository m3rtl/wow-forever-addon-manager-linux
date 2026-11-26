#!/bin/bash
# Gibt .SRCINFO fuer das PKGBUILD aus. Unter Arch gleichwertig: makepkg --printsrcinfo
# (dieses Skript laeuft auch ohne makepkg, z. B. in CI auf Ubuntu).
set -eu
cd "$(dirname "$0")"
# PKGBUILD in einer Subshell auswerten; es setzt nur Variablen und definiert Funktionen
(
    . ./PKGBUILD
    printf 'pkgbase = %s\n' "$pkgname"
    printf '\tpkgdesc = %s\n' "$pkgdesc"
    printf '\tpkgver = %s\n' "$pkgver"
    printf '\tpkgrel = %s\n' "$pkgrel"
    printf '\turl = %s\n' "$url"
    for a in "${arch[@]}"; do printf '\tarch = %s\n' "$a"; done
    for l in "${license[@]}"; do printf '\tlicense = %s\n' "$l"; done
    for d in "${depends[@]}"; do printf '\tdepends = %s\n' "$d"; done
    for o in "${optdepends[@]}"; do printf '\toptdepends = %s\n' "$o"; done
    for s in "${source[@]}"; do printf '\tsource = %s\n' "$s"; done
    for c in "${sha256sums[@]}"; do printf '\tsha256sums = %s\n' "$c"; done
    printf '\npkgname = %s\n' "$pkgname"
)
