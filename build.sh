#!/bin/sh
# Baut die Einzeldatei dist/wow-forever-addon-manager (PyInstaller).
# Voraussetzung: python3, python3-gi und GTK 3 (gir1.2-gtk-3.0) systemweit installiert.
set -eu
cd "$(dirname "$(readlink -f "$0")")"
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --quiet pyinstaller
.venv/bin/pyinstaller --noconfirm --clean --onefile --name wow-forever-addon-manager \
    --add-data assets:assets \
    --hidden-import wfa_gui --hidden-import wfa_cli --hidden-import wfa_core \
    wow-forever-addon-manager.py
echo "Fertig: dist/wow-forever-addon-manager"
