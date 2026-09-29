#!/usr/bin/env bash
#
# instalar_autofirma.sh
# Instalador AutoFirma para Fedora.
#
# IMPORTANTE:
# Este esqueleto inicial todavía no implementa la descarga e instalación
# definitiva. La lógica se cerrará después de contrastar el RPM oficial.
#
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    exec sudo -- "$0" "$@"
fi

source /etc/os-release

if [[ "${ID:-}" != "fedora" ]]; then
    echo "[ERROR] Este instalador está diseñado para Fedora." >&2
    exit 1
fi

command -v dnf >/dev/null 2>&1 || {
    echo "[ERROR] No se encontró dnf." >&2
    exit 1
}

echo "[OK] Fedora detectado."
echo "[OK] dnf disponible."
echo
echo "El instalador definitivo se implementará después de validar"
echo "el RPM oficial de AutoFirma para Fedora."
