#!/usr/bin/env bash
# AutoFirma 1.9 oficial para Fedora
set -euo pipefail
IFS=$'\n\t'
umask 077

readonly AUTOFIRMA_VERSION="1.9"
readonly AUTOFIRMA_RPM_NAME="autofirma-1.9-1.noarch_FEDORA.rpm"
readonly AUTOFIRMA_ZIP_NAME="Autofirma_Linux_Fedora.zip"
readonly AUTOFIRMA_URL="https://firmaelectronica.gob.es/content/dam/firmaelectronica/descargas-software/autofirma19/Autofirma_Linux_Fedora.zip"
# SHA-256 del ZIP oficial descargado y del RPM que contiene (calculadas el 2026-09-29).
readonly AUTOFIRMA_ZIP_SHA256="049bccfc298cca0cbd9819b7830a7d89829888e7b3df2337a4929433d4b49aa3"
readonly AUTOFIRMA_RPM_SHA256="d76d7a65a62ace9b22983c9b0fdeaf5691e335e8de234cf94bd1b22f86ef42a9"

ROOT_DIR=""
WORK_DIR=""
DOWNLOADED_ZIP=""
RPM_FILE=""

log() { printf "[INFO] %s\n" "$*"; }
ok() { printf "[ OK ] %s\n" "$*"; }
warn() { printf "[ADVERTENCIA] %s\n" "$*" >&2; }
die() { printf "[ERROR] %s\n" "$*" >&2; exit 1; }

cleanup() {
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
        rm -rf -- "$WORK_DIR"
    fi
}
trap cleanup EXIT

ROOT_DIR="$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || die "Se necesitan privilegios de administrador. Instala sudo o ejecuta el script como root."
    exec sudo -- bash "$0" "$@"
fi

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "No se encontró el comando requerido: $1"
}

detect_os() {
    [[ -r /etc/os-release ]] || die "No existe /etc/os-release."
    # shellcheck disable=SC1091
    source /etc/os-release
    [[ ${ID:-} == fedora ]] || die "Este instalador está diseñado exclusivamente para Fedora."
    ok "Fedora detectado: ${PRETTY_NAME:-Fedora}"
}

detect_arch() {
    local machine rpm_arch
    machine=$(uname -m)
    rpm_arch=$(rpm --eval "%{_arch}" 2>/dev/null || true)
    [[ -n "$rpm_arch" ]] || die "No se pudo determinar la arquitectura RPM."
    case "$machine" in
        x86_64|aarch64|ppc64le|s390x) [[ "$rpm_arch" == "$machine" ]] || die "Arquitectura inconsistente: uname=$machine, rpm=$rpm_arch" ;;
        *) die "Arquitectura no soportada por este instalador: $machine" ;;
    esac
    ok "Arquitectura detectada: $machine (RPM: $rpm_arch)"
    log "El RPM oficial es noarch; Java y NSS utilizan la arquitectura del sistema."
}

check_tools() {
    local cmd
    for cmd in dnf rpm curl unzip sha256sum awk find sed mktemp; do require_command "$cmd"; done
    ok "Herramientas básicas disponibles."
}

check_java() {
    local java_bin java_version major
    java_bin=$(command -v java 2>/dev/null || true)
    [[ -n "$java_bin" ]] || die "Java no está instalado. Instala OpenJDK 17, recomendado oficialmente, y vuelve a ejecutar el instalador."
    java_version=$(java -version 2>&1 | awk -F '"' '/version/ {print $2; exit}')
    [[ -n "$java_version" ]] || die "No se pudo determinar la versión de Java."
    if [[ "$java_version" == 1.* ]]; then major=$(printf "%s\n" "$java_version" | sed "s/^1\.//; s/\..*//"); else major=$(printf "%s\n" "$java_version" | sed "s/\..*//"); fi
    [[ "$major" =~ ^[0-9]+$ ]] || die "No se pudo interpretar la versión de Java: $java_version"
    (( major >= 8 )) || die "Java $java_version es demasiado antiguo. AutoFirma requiere Java 8 o superior."
    ok "Java detectado: $java_version ($java_bin)"
    if (( major >= 17 )); then ok "Java cumple la recomendación de OpenJDK 17 o superior."; else warn "Java $java_version cumple el mínimo, pero la documentación oficial recomienda OpenJDK 17."; fi
}

# AutoFirma necesita AWT/X11 para abrir su ventana. Los paquetes *-headless no lo incluyen:
# el RPM se instala igual, pero la app cae a modo consola ("No se puede crear el entorno grafico").
ensure_java_gui() {
    local real home owner base
    real=$(readlink -f -- "$(command -v java)")
    home=$(dirname -- "$(dirname -- "$real")")
    if [[ -n "$(find "$home" -name libawt_xawt.so -print -quit 2>/dev/null)" ]]; then
        ok "Java con soporte gráfico (AWT/X11)."
        return 0
    fi
    owner=$(rpm -qf --qf '%{NAME}\n' "$real" 2>/dev/null | head -n1 || true)
    if [[ "$owner" != *-headless ]]; then
        die "Este Java no incluye libawt_xawt.so (sin interfaz gráfica) y no es un paquete -headless de dnf. Instala un OpenJDK completo."
    fi
    base="${owner%-headless}"
    warn "Java instalado como $owner (sin interfaz gráfica). Se instalará $base."
    dnf install -y "$base"
    [[ -n "$(find "$home" -name libawt_xawt.so -print -quit 2>/dev/null)" ]] || die "$base se instaló, pero sigue sin encontrarse libawt_xawt.so."
    ok "Java con soporte gráfico instalado: $base"
}

install_gui_system() {
    local app_dir="/usr/share/autofirma-fedora"
    local launcher="/usr/bin/autofirma-fedora"
    local desktop="/usr/share/applications/autofirma-fedora.desktop"
    local gui_src="" self_src="$ROOT_DIR/instalar_autofirma.sh"

    # Layout de repositorio (gui/...) o layout ya instalado (/usr/share/autofirma-fedora/...)
    if [[ -f "$ROOT_DIR/gui/autofirma_fedora_gui.py" ]]; then
        gui_src="$ROOT_DIR/gui/autofirma_fedora_gui.py"
    elif [[ -f "$ROOT_DIR/autofirma_fedora_gui.py" ]]; then
        gui_src="$ROOT_DIR/autofirma_fedora_gui.py"
    else
        die "No se encuentra la GUI de AutoFirma Fedora (ni gui/autofirma_fedora_gui.py ni autofirma_fedora_gui.py en $ROOT_DIR)."
    fi
    [[ -f "$self_src" ]] || die "No se encuentra el instalador principal."

    log "Instalando la GUI de AutoFirma Fedora."
    install -d -m 0755 "$app_dir" /usr/share/applications
    if [[ ! "$gui_src" -ef "$app_dir/autofirma_fedora_gui.py" ]]; then
        install -m 0644 "$gui_src" "$app_dir/autofirma_fedora_gui.py"
    fi
    if [[ ! "$self_src" -ef "$app_dir/instalar_autofirma.sh" ]]; then
        install -m 0755 "$self_src" "$app_dir/instalar_autofirma.sh"
    fi

    cat > "$launcher" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/python3 /usr/share/autofirma-fedora/autofirma_fedora_gui.py "$@"
EOF
    chmod 0755 "$launcher"

    cat > "$desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=AutoFirma · Fedora
GenericName=AutoFirma para Fedora
Comment=Instalar y configurar AutoFirma en Fedora
Exec=/usr/bin/autofirma-fedora
TryExec=/usr/bin/autofirma-fedora
Terminal=false
Categories=Utility;Office;
Keywords=AutoFirma;firma;electrónica;certificado;
StartupNotify=true
EOF
    chmod 0644 "$desktop"

    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
    fi

    ok "GUI instalada: $launcher"
    ok "Lanzador de menú instalado: $desktop"
}

check_nss_tools() {
    local missing=()
    command -v certutil >/dev/null 2>&1 || missing+=(nss-tools)
    command -v pk12util >/dev/null 2>&1 || { [[ " ${missing[*]:-} " == *" nss-tools "* ]] || missing+=(nss-tools); }
    command -v openssl >/dev/null 2>&1 || missing+=(openssl)
    if (( ${#missing[@]} == 0 )); then ok "nss-tools y openssl ya están disponibles."; return; fi
    log "Faltan paquetes (${missing[*]}). Se instalarán mediante dnf."
    dnf install -y "${missing[@]}"
    command -v certutil >/dev/null 2>&1 || die "nss-tools se instaló, pero no se encontró certutil."
    command -v pk12util >/dev/null 2>&1 || die "nss-tools se instaló, pero no se encontró pk12util."
    command -v openssl >/dev/null 2>&1 || die "openssl se instaló, pero no se encontró el comando."
    ok "Paquetes instalados correctamente."
}

# Crea ~/.pki/nssdb del usuario que lanzó el instalador si no existe.
# certutil -N NO crea el directorio: hay que hacerlo antes, o falla con SEC_ERROR_BAD_DATABASE.
ensure_user_nss() {
    local user="${SUDO_USER:-}" home db
    if [[ -z "$user" || "$user" == root ]]; then
        warn "No se pudo determinar el usuario que lanzó el instalador; se omite ~/.pki/nssdb (créalo desde la GUI, opción 3)."
        return 0
    fi
    command -v runuser >/dev/null 2>&1 || { warn "Falta runuser; se omite la creación de ~/.pki/nssdb."; return 0; }
    home=$(getent passwd "$user" | cut -d: -f6)
    [[ -n "$home" && -d "$home" ]] || { warn "No se encontró el HOME de $user; se omite ~/.pki/nssdb."; return 0; }
    db="$home/.pki/nssdb"

    if [[ -f "$db/cert9.db" ]]; then
        ok "Almacén NSS ya existe: $db (no se modifica)."
        return 0
    fi
    if [[ -d "$db" && -n "$(ls -A -- "$db" 2>/dev/null || true)" ]]; then
        warn "$db existe con contenido pero sin cert9.db; no se toca por seguridad."
        return 0
    fi

    log "Creando almacén NSS de $user en $db"
    if runuser -u "$user" -- mkdir -p -- "$db" \
        && runuser -u "$user" -- chmod 0700 -- "$db" \
        && runuser -u "$user" -- certutil -N -d "sql:$db" --empty-password; then
        ok "Almacén NSS creado: $db (contraseña vacía)."
    else
        warn "No se pudo crear $db. La instalación continúa; usa la opción 3 de la GUI o revisa los permisos de $home."
    fi
}

download_official_zip() {
    WORK_DIR=$(mktemp -d -t autofirma-fedora.XXXXXX)
    DOWNLOADED_ZIP="$WORK_DIR/$AUTOFIRMA_ZIP_NAME"
    log "Descargando AutoFirma Fedora $AUTOFIRMA_VERSION desde la fuente oficial."
    curl --fail --location --proto "=https" --tlsv1.2 --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 300 --output "$DOWNLOADED_ZIP" "$AUTOFIRMA_URL"
    [[ -s "$DOWNLOADED_ZIP" ]] || die "La descarga oficial está vacía."
    ok "Descarga oficial completada."
}

verify_zip_sha256() {
    local actual
    actual=$(sha256sum "$DOWNLOADED_ZIP" | awk '{print $1}')
    [[ "$actual" == "$AUTOFIRMA_ZIP_SHA256" ]] || { echo "SHA-256 ZIP esperada: $AUTOFIRMA_ZIP_SHA256" >&2; echo "SHA-256 ZIP obtenida : $actual" >&2; die "La verificación SHA-256 del ZIP ha fallado. No se extrae ni se instala nada."; }
    ok "SHA-256 del ZIP verificada."
}

extract_and_locate_rpm() {
    local extract_dir rpm_count
    extract_dir="$WORK_DIR/extract"
    mkdir -p -- "$extract_dir"
    unzip -q -o -- "$DOWNLOADED_ZIP" -d "$extract_dir"
    rpm_count=$(find "$extract_dir" -type f -iname "*.rpm" | wc -l)
    [[ "$rpm_count" -eq 1 ]] || die "Se esperaba exactamente un RPM en el ZIP oficial; se encontraron $rpm_count."
    RPM_FILE=$(find "$extract_dir" -type f -iname "*.rpm" -print -quit)
    [[ -n "$RPM_FILE" && -f "$RPM_FILE" ]] || die "No se encontró el RPM de AutoFirma."
    [[ $(basename "$RPM_FILE") == "$AUTOFIRMA_RPM_NAME" ]] || die "RPM inesperado: $(basename "$RPM_FILE")"
    ok "RPM localizado: $(basename "$RPM_FILE")"
}

verify_rpm_sha256() {
    local actual
    actual=$(sha256sum "$RPM_FILE" | awk "{print \$1}")
    [[ "$actual" == "$AUTOFIRMA_RPM_SHA256" ]] || { echo "SHA-256 esperada: $AUTOFIRMA_RPM_SHA256" >&2; echo "SHA-256 obtenida : $actual" >&2; die "La verificación SHA-256 ha fallado. El paquete NO se instalará."; }
    ok "SHA-256 del RPM verificada."
}

verify_rpm_metadata() {
    local name version arch
    rpm -K --nosignature "$RPM_FILE" >/dev/null 2>&1 || die "El archivo descargado no es un RPM válido."
    name=$(rpm -qp --qf "%{NAME}" "$RPM_FILE")
    version=$(rpm -qp --qf "%{VERSION}" "$RPM_FILE")
    arch=$(rpm -qp --qf "%{ARCH}" "$RPM_FILE")
    [[ "$name" == autofirma ]] || die "Paquete inesperado: $name"
    [[ "$version" == "$AUTOFIRMA_VERSION" ]] || die "Versión RPM inesperada: $version"
    [[ "$arch" == noarch ]] || die "Arquitectura RPM inesperada: $arch"
    ok "Metadatos RPM verificados: $name-$version ($arch)."
}

install_rpm() {
    if command -v pgrep >/dev/null 2>&1 && pgrep -x firefox >/dev/null 2>&1; then
        warn "Firefox está abierto: el scriptlet del RPM lo cerrará (pkill firefox) durante la instalación."
    fi
    log "Instalando AutoFirma mediante dnf."
    dnf install -y "$RPM_FILE"
    ok "dnf terminó la instalación de AutoFirma."
}

verify_installation() {
    local installed_version install_dir exe
    exe=$(command -v autofirma 2>/dev/null || command -v AutoFirma 2>/dev/null || true)
    if [[ -z "$exe" ]]; then
        exe=$(rpm -ql autofirma 2>/dev/null | awk '/^\/usr\/bin\/[^\/]+$/ {print; exit}' || true)
    fi
    [[ -n "$exe" && -x "$exe" ]] || die "La instalación terminó, pero no se encontró el ejecutable de AutoFirma en /usr/bin (rpm -ql autofirma | grep bin)."
    install_dir=$(rpm -ql autofirma 2>/dev/null | awk 'tolower($0) ~ /^\/usr\/lib(64)?\/autofirma\/?$/ {print; exit}' || true)
    if [[ -z "$install_dir" ]]; then
        for d in /usr/lib64/autofirma /usr/lib/autofirma /usr/lib64/AutoFirma /usr/lib/AutoFirma; do
            [[ -d "$d" ]] && { install_dir="$d"; break; }
        done
    fi
    [[ -n "$install_dir" && -d "$install_dir" ]] || die "No se encontró el directorio de instalación de AutoFirma."
    installed_version=$(rpm -q --qf "%{VERSION}-%{RELEASE}.%{ARCH}" autofirma 2>/dev/null || true)
    [[ -n "$installed_version" ]] || die "rpm no registra el paquete autofirma como instalado."
    ok "AutoFirma instalada: $installed_version"
    ok "Ejecutable: $exe"
    ok "Directorio: $install_dir"
    ok "Paquete RPM registrado correctamente."
}

main() {
    echo "=============================================="
    echo " AutoFirma Fedora — instalador oficial"
    echo " Versión: $AUTOFIRMA_VERSION"
    echo "=============================================="
    echo
    detect_os
    detect_arch
    check_tools
    check_java
    ensure_java_gui
    check_nss_tools
    ensure_user_nss
    download_official_zip
    verify_zip_sha256
    extract_and_locate_rpm
    verify_rpm_sha256
    verify_rpm_metadata
    install_rpm
    verify_installation
    install_gui_system
    echo
    echo "Instalación completada mediante el RPM oficial."
}

main "$@"