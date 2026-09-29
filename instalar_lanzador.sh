#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'
umask 077

ROOT="$(cd -- "$(dirname -- "$(readlink -f -- "$0" 2>/dev/null || printf '%s' "$0")")" && pwd)"
WRAPPER="$ROOT/gui/autofirma-fedora-gui"
DESKTOP_TEMPLATE="$ROOT/gui/autofirma-fedora.desktop.in"
LOCAL_BIN="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
LINK="$LOCAL_BIN/autofirma-fedora-gui"
DESKTOP="$APPS_DIR/autofirma-fedora.desktop"

[[ -f "$ROOT/gui/autofirma_fedora_gui.py" ]] || { echo "[ERROR] No se encuentra la GUI." >&2; exit 1; }
[[ -f "$WRAPPER" ]] || { echo "[ERROR] No se encuentra el lanzador." >&2; exit 1; }
[[ -f "$DESKTOP_TEMPLATE" ]] || { echo "[ERROR] No se encuentra la plantilla .desktop." >&2; exit 1; }

/usr/bin/python3 -c 'import PyQt6' >/dev/null 2>&1 || {
    echo "[ERROR] Falta PyQt6."
    echo "Instala solamente la dependencia de la GUI:"
    echo "  sudo dnf install -y python3 python3-pyqt6"
    exit 1
}

mkdir -p "$LOCAL_BIN" "$APPS_DIR"
chmod 0755 "$WRAPPER"
ln -sfn "$WRAPPER" "$LINK"

sed "s|@GUI_LAUNCHER@|$LINK|g" "$DESKTOP_TEMPLATE" > "$DESKTOP"
chmod 0644 "$DESKTOP"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

echo "[ OK ] Lanzador instalado."
echo "[ OK ] Comando: $LINK"
echo "[ OK ] Menú: $DESKTOP"
echo
echo "Busca «AutoFirma · Fedora» en el menú de aplicaciones."
