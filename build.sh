#!/bin/sh
# Baut die Einzeldatei dist/wow-forever-addon-manager (PyInstaller).
# Voraussetzung: python3, python3-gi und GTK 3 (gir1.2-gtk-3.0) systemweit installiert.
set -eu
cd "$(dirname "$(readlink -f "$0")")"
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --quiet pyinstaller
.venv/bin/pyinstaller --noconfirm --clean --onefile --name wow-forever-addon-manager \
    --add-data assets:assets --add-data CHANGELOG.md:. \
    --hidden-import wfa_gui --hidden-import wfa_cli --hidden-import wfa_core \
    --hidden-import wfa_base --hidden-import wfa_paths --hidden-import wfa_http --hidden-import wfa_toc --hidden-import wfa_sources --hidden-import wfa_files --hidden-import wfa_pins \
    --hidden-import wfa_manager --hidden-import wfa_plan --hidden-import wfa_apply --hidden-import wfa_savedvars --hidden-import wfa_assign \
    --hidden-import wfa_tray --hidden-import wfa_background --hidden-import wfa_newaddon --hidden-import wfa_selfupdate --hidden-import wfa_portal \
    --hidden-import wfa_i18n --hidden-import wfa_expert --hidden-import wfa_chars --hidden-import wfa_cleanup --hidden-import wfa_snapshot \
    --hidden-import wfa_unattended --hidden-import wfa_bugs --hidden-import wfa_sets --hidden-import wfa_health \
    wow-forever-addon-manager.py
echo "Fertig: dist/wow-forever-addon-manager"
