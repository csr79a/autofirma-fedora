#!/usr/bin/env bash
#
# instalar_autofirma.sh — AutoFirma 1.9 oficial para Fedora
#
# Fuente oficial:
# https://firmaelectronica.gob.es/content/dam/firmaelectronica/descargas-software/autofirma19/Autofirma_Linux_Fedora.zip
#
# Comprueba Fedora/arquitectura, Java y NSS, descarga el ZIP oficial,
# extrae el RPM, verifica SHA-256 y metadatos, instala con dnf y valida.
#
set -euo pipefail
IFS=

AUTOFIRMA_VERSION="1.9"
AUTOFIRMA_RPM_NAME="autofirma-1.9-1.noarch_FEDORA.rpm"
AUTOFIRMA_ZIP_NAME="Autofirma_Linux_Fedora.zip"
AUTOFIRMA_URL="https://firmaelectronica.gob.es/content/dam/firmaelectronica/descargas-software/autofirma19/Autofirma_Linux_Fedora.zip"
AUTOFIRMA_RPM_SHA256="049bccfc298cca0cbd9819b7830a7d89829888e7b3df2337a4929433d4b49aa3"

WORK_DIR=""
DOWNLOADED_ZIP=""
RPM_FILE=""

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || die "Se necesitan privilegios de administrador. Instala sudo o ejecuta el script como root."
    exec sudo -- "$0" "$@"
fi

log() { printf '[INFO] %s\n' "$*"; }
ok() { printf '[ OK ] %s\n' "$*"; }
warn() { printf '[ADVERTENCIA] %s\n' "$*" >&2; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

cleanup() {
    if [ -n "$WORK_DIR" ] && [ -d "$WORK_DIR" ]; then
        rm -rf -- "$WORK_DIR"
    fi
}
trap cleanup EXIT

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "No se encontró el comando requerido: $1"
}

detect_os() {
    [ -r /etc/os-release ] || die "No existe /etc/os-release."
    # shellcheck disable=SC1091
    . /etc/os-release
    [ "$ID" = "fedora" ] || die "Este instalador está diseñado exclusivamente para Fedora."
    ok "Fedora detectado: $PRETTY_NAME"
}

detect_arch() {
    local machine rpm_arch
    machine="$(uname -m)"
    rpm_arch="$(rpm --eval '%{_arch}' 2>/dev/null || true)"

    [ -n "$rpm_arch" ] || die "No se pudo determinar la arquitectura RPM."

    case "$machine" in
        x86_64|aarch64|ppc64le|s390x)
            [ "$rpm_arch" = "$machine" ] ||
                die "Arquitectura inconsistente: uname=$machine, rpm=$rpm_arch"
            ;;
        *)
            die "Arquitectura no soportada por este instalador: $machine"
            ;;
    esac

    ok "Arquitectura detectada: $machine (RPM: $rpm_arch)"
    log "El RPM oficial es noarch; Java y NSS utilizan la arquitectura del sistema."
}

check_tools() {
    require_command dnf
    require_command rpm
    require_command curl
    require_command unzip
    require_command sha256sum
    require_command awk
    require_command find
    ok "Herramientas básicas disponibles."
}

check_java() {
    local java_bin java_version major

    java_bin="$(command -v java 2>/dev/null || true)"
    [ -n "$java_bin" ] ||
        die "Java no está instalado. Instala OpenJDK 17, recomendado oficialmente, y vuelve a ejecutar el instalador."

    java_version="$(java -version 2>&1 | awk -F'"' '/version/ {print $2; exit}')"
    [ -n "$java_version" ] || die "No se pudo determinar la versión de Java."

    if [[ "$java_version" == 1.* ]]; then
        major="$(printf '%s\n' "$java_version" | sed 's/^1\.//; s/\..*//')"
    else
        major="$(printf '%s\n' "$java_version" | sed 's/\..*//')"
    fi

    [[ "$major" =~ ^[0-9]+$ ]] ||
        die "No se pudo interpretar la versión de Java: $java_version"
    [ "$major" -ge 8 ] ||
        die "Java $java_version es demasiado antiguo. AutoFirma requiere Java 8 o superior."

    ok "Java detectado: $java_version ($java_bin)"
    if [ "$major" -ge 17 ]; then
        ok "Java cumple la recomendación de OpenJDK 17 o superior."
    else
        warn "Java $java_version cumple el mínimo, pero la documentación oficial recomienda OpenJDK 17."
    fi
}

check_nss_tools() {
    if command -v certutil >/dev/null 2>&1 &&
       command -v pk12util >/dev/null 2>&1; then
        ok "nss-tools ya está disponible (certutil y pk12util)."
        return
    fi

    log "nss-tools no está disponible. Se instalará mediante dnf."
    dnf install -y nss-tools

    command -v certutil >/dev/null 2>&1 ||
        die "nss-tools se instaló, pero no se encontró certutil."
    command -v pk12util >/dev/null 2>&1 ||
        die "nss-tools se instaló, pero no se encontró pk12util."

    ok "nss-tools instalado correctamente."
}

download_official_zip() {
    WORK_DIR="$(mktemp -d -t autofirma-fedora.XXXXXX)"
    DOWNLOADED_ZIP="$WORK_DIR/$AUTOFIRMA_ZIP_NAME"

    log "Descargando AutoFirma Fedora $AUTOFIRMA_VERSION desde la fuente oficial."
    log "URL: $AUTOFIRMA_URL"

    curl \
        --fail \
        --location \
        --proto '=https' \
        --tlsv1.2 \
        --retry 3 \
        --retry-delay 2 \
        --connect-timeout 20 \
        --max-time 300 \
        --output "$DOWNLOADED_ZIP" \
        "$AUTOFIRMA_URL"

    [ -s "$DOWNLOADED_ZIP" ] || die "La descarga oficial está vacía."
    ok "Descarga oficial completada."
}

extract_and_locate_rpm() {
    local extract_dir rpm_count
    extract_dir="$WORK_DIR/extract"
    mkdir -p -- "$extract_dir"

    unzip -q -o -- "$DOWNLOADED_ZIP" -d "$extract_dir"

    rpm_count="$(find "$extract_dir" -type f -iname '*.rpm' | wc -l)"
    [ "$rpm_count" -eq 1 ] ||
        die "Se esperaba exactamente un RPM en el ZIP oficial; se encontraron $rpm_count."

    RPM_FILE="$(find "$extract_dir" -type f -iname '*.rpm' -print -quit)"
    [ -n "$RPM_FILE" ] && [ -f "$RPM_FILE" ] ||
        die "No se encontró el RPM de AutoFirma."

    [ "$(basename "$RPM_FILE")" = "$AUTOFIRMA_RPM_NAME" ] ||
        die "RPM inesperado: $(basename "$RPM_FILE")"

    ok "RPM localizado: $(basename "$RPM_FILE")"
}

verify_rpm_sha256() {
    local actual
    actual="$(sha256sum "$RPM_FILE" | awk '{print $1}')"

    if [ "$actual" != "$AUTOFIRMA_RPM_SHA256" ]; then
        echo "SHA-256 esperada: $AUTOFIRMA_RPM_SHA256" >&2
        echo "SHA-256 obtenida : $actual" >&2
        die "La verificación SHA-256 ha fallado. El paquete NO se instalará."
    fi

    ok "SHA-256 del RPM verificada."
}

verify_rpm_metadata() {
    local name version arch

    rpm -K --nosignature "$RPM_FILE" >/dev/null 2>&1 ||
        die "El archivo descargado no es un RPM válido."

    name="$(rpm -qp --qf '%{NAME}' "$RPM_FILE")"
    version="$(rpm -qp --qf '%{VERSION}' "$RPM_FILE")"
    arch="$(rpm -qp --qf '%{ARCH}' "$RPM_FILE")"

    [ "$name" = "autofirma" ] || die "Paquete inesperado: $name"
    [ "$version" = "$AUTOFIRMA_VERSION" ] || die "Versión RPM inesperada: $version"
    [ "$arch" = "noarch" ] || die "Arquitectura RPM inesperada: $arch"

    ok "Metadatos RPM verificados: $name-$version ($arch)."
}

install_rpm() {
    log "Instalando AutoFirma mediante dnf."
    # dnf gestiona dependencias y ejecuta los scriptlets oficiales del RPM.
    dnf install -y "$RPM_FILE"
    ok "dnf terminó la instalación de AutoFirma."
}

verify_installation() {
    local installed_version

    command -v autofirma >/dev/null 2>&1 ||
        die "La instalación terminó, pero /usr/bin/autofirma no está disponible."

    install_dir="$(rpm -ql autofirma | awk '/^\/usr\/lib(64)?\/AutoFirma\/?$/ {print; exit}')"
    if [ -z "$install_dir" ]; then
        if [ -d /usr/lib64/AutoFirma ]; then
            install_dir="/usr/lib64/AutoFirma"
        elif [ -d /usr/lib/AutoFirma ]; then
            install_dir="/usr/lib/AutoFirma"
        else
            die "No se encontró el directorio de instalación de AutoFirma."
        fi
    fi

    installed_version="$(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}' autofirma 2>/dev/null || true)"
    [ -n "$installed_version" ] ||
        die "rpm no registra el paquete autofirma como instalado."

    ok "AutoFirma instalada: $installed_version"
    ok "Ejecutable: $(command -v autofirma)"
    ok "Directorio: $install_dir"
    ok "Paquete RPM registrado correctamente."

    command -v java >/dev/null 2>&1 && ok "Java disponible después de la instalación."
    command -v certutil >/dev/null 2>&1 && ok "certutil disponible después de la instalación."
    command -v pk12util >/dev/null 2>&1 && ok "pk12util disponible después de la instalación."
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
    check_nss_tools
    download_official_zip
    extract_and_locate_rpm
    verify_rpm_sha256
    verify_rpm_metadata
    install_rpm
    verify_installation

    echo
    echo "=============================================="
    echo " Instalación completada"
    echo "=============================================="
    echo
    echo "AutoFirma ha sido instalada mediante el RPM oficial."
    echo "El propio RPM ha realizado su configuración de integración."
}

main "$@"
\n\t'
umask 077

AUTOFIRMA_VERSION="1.9"
AUTOFIRMA_RPM_NAME="autofirma-1.9-1.noarch_FEDORA.rpm"
AUTOFIRMA_ZIP_NAME="Autofirma_Linux_Fedora.zip"
AUTOFIRMA_URL="https://firmaelectronica.gob.es/content/dam/firmaelectronica/descargas-software/autofirma19/Autofirma_Linux_Fedora.zip"
AUTOFIRMA_RPM_SHA256="049bccfc298cca0cbd9819b7830a7d89829888e7b3df2337a4929433d4b49aa3"

WORK_DIR=""
DOWNLOADED_ZIP=""
RPM_FILE=""

log() { printf '[INFO] %s\n' "$*"; }
ok() { printf '[ OK ] %s\n' "$*"; }
warn() { printf '[ADVERTENCIA] %s\n' "$*" >&2; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

cleanup() {
    if [ -n "$WORK_DIR" ] && [ -d "$WORK_DIR" ]; then
        rm -rf -- "$WORK_DIR"
    fi
}
trap cleanup EXIT

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "No se encontró el comando requerido: $1"
}

detect_os() {
    [ -r /etc/os-release ] || die "No existe /etc/os-release."
    # shellcheck disable=SC1091
    . /etc/os-release
    [ "$ID" = "fedora" ] || die "Este instalador está diseñado exclusivamente para Fedora."
    ok "Fedora detectado: $PRETTY_NAME"
}

detect_arch() {
    local machine rpm_arch
    machine="$(uname -m)"
    rpm_arch="$(rpm --eval '%{_arch}' 2>/dev/null || true)"

    [ -n "$rpm_arch" ] || die "No se pudo determinar la arquitectura RPM."

    case "$machine" in
        x86_64|aarch64|ppc64le|s390x)
            [ "$rpm_arch" = "$machine" ] ||
                die "Arquitectura inconsistente: uname=$machine, rpm=$rpm_arch"
            ;;
        *)
            die "Arquitectura no soportada por este instalador: $machine"
            ;;
    esac

    ok "Arquitectura detectada: $machine (RPM: $rpm_arch)"
    log "El RPM oficial es noarch; Java y NSS utilizan la arquitectura del sistema."
}

check_tools() {
    require_command dnf
    require_command rpm
    require_command curl
    require_command unzip
    require_command sha256sum
    ok "Herramientas básicas disponibles."
}

check_java() {
    local java_bin java_version major

    java_bin="$(command -v java 2>/dev/null || true)"
    [ -n "$java_bin" ] ||
        die "Java no está instalado. Instala OpenJDK 17, recomendado oficialmente, y vuelve a ejecutar el instalador."

    java_version="$(java -version 2>&1 | awk -F'"' '/version/ {print $2; exit}')"
    [ -n "$java_version" ] || die "No se pudo determinar la versión de Java."

    if [[ "$java_version" == 1.* ]]; then
        major="$(printf '%s\n' "$java_version" | sed 's/^1\.//; s/\..*//')"
    else
        major="$(printf '%s\n' "$java_version" | sed 's/\..*//')"
    fi

    [[ "$major" =~ ^[0-9]+$ ]] ||
        die "No se pudo interpretar la versión de Java: $java_version"
    [ "$major" -ge 8 ] ||
        die "Java $java_version es demasiado antiguo. AutoFirma requiere Java 8 o superior."

    ok "Java detectado: $java_version ($java_bin)"
    if [ "$major" -ge 17 ]; then
        ok "Java cumple la recomendación de OpenJDK 17 o superior."
    else
        warn "Java $java_version cumple el mínimo, pero la documentación oficial recomienda OpenJDK 17."
    fi
}

check_nss_tools() {
    if command -v certutil >/dev/null 2>&1 &&
       command -v pk12util >/dev/null 2>&1; then
        ok "nss-tools ya está disponible (certutil y pk12util)."
        return
    fi

    log "nss-tools no está disponible. Se instalará mediante dnf."
    dnf install -y nss-tools

    command -v certutil >/dev/null 2>&1 ||
        die "nss-tools se instaló, pero no se encontró certutil."
    command -v pk12util >/dev/null 2>&1 ||
        die "nss-tools se instaló, pero no se encontró pk12util."

    ok "nss-tools instalado correctamente."
}

download_official_zip() {
    WORK_DIR="$(mktemp -d -t autofirma-fedora.XXXXXX)"
    DOWNLOADED_ZIP="$WORK_DIR/$AUTOFIRMA_ZIP_NAME"

    log "Descargando AutoFirma Fedora $AUTOFIRMA_VERSION desde la fuente oficial."
    log "URL: $AUTOFIRMA_URL"

    curl \
        --fail \
        --location \
        --proto '=https' \
        --tlsv1.2 \
        --retry 3 \
        --retry-delay 2 \
        --connect-timeout 20 \
        --max-time 300 \
        --output "$DOWNLOADED_ZIP" \
        "$AUTOFIRMA_URL"

    [ -s "$DOWNLOADED_ZIP" ] || die "La descarga oficial está vacía."
    ok "Descarga oficial completada."
}

extract_and_locate_rpm() {
    local extract_dir rpm_count
    extract_dir="$WORK_DIR/extract"
    mkdir -p -- "$extract_dir"

    unzip -q -o -- "$DOWNLOADED_ZIP" -d "$extract_dir"

    rpm_count="$(find "$extract_dir" -type f -iname '*.rpm' | wc -l)"
    [ "$rpm_count" -eq 1 ] ||
        die "Se esperaba exactamente un RPM en el ZIP oficial; se encontraron $rpm_count."

    RPM_FILE="$(find "$extract_dir" -type f -iname '*.rpm' -print -quit)"
    [ -n "$RPM_FILE" ] && [ -f "$RPM_FILE" ] ||
        die "No se encontró el RPM de AutoFirma."

    [ "$(basename "$RPM_FILE")" = "$AUTOFIRMA_RPM_NAME" ] ||
        die "RPM inesperado: $(basename "$RPM_FILE")"

    ok "RPM localizado: $(basename "$RPM_FILE")"
}

verify_rpm_sha256() {
    local actual
    actual="$(sha256sum "$RPM_FILE" | awk '{print $1}')"

    if [ "$actual" != "$AUTOFIRMA_RPM_SHA256" ]; then
        echo "SHA-256 esperada: $AUTOFIRMA_RPM_SHA256" >&2
        echo "SHA-256 obtenida : $actual" >&2
        die "La verificación SHA-256 ha fallado. El paquete NO se instalará."
    fi

    ok "SHA-256 del RPM verificada."
}

verify_rpm_metadata() {
    local name version arch

    rpm -K --nosignature "$RPM_FILE" >/dev/null 2>&1 ||
        die "El archivo descargado no es un RPM válido."

    name="$(rpm -qp --qf '%{NAME}' "$RPM_FILE")"
    version="$(rpm -qp --qf '%{VERSION}' "$RPM_FILE")"
    arch="$(rpm -qp --qf '%{ARCH}' "$RPM_FILE")"

    [ "$name" = "autofirma" ] || die "Paquete inesperado: $name"
    [ "$version" = "$AUTOFIRMA_VERSION" ] || die "Versión RPM inesperada: $version"
    [ "$arch" = "noarch" ] || die "Arquitectura RPM inesperada: $arch"

    ok "Metadatos RPM verificados: $name-$version ($arch)."
}

install_rpm() {
    log "Instalando AutoFirma mediante dnf."
    # dnf gestiona dependencias y ejecuta los scriptlets oficiales del RPM.
    dnf install -y "$RPM_FILE"
    ok "dnf terminó la instalación de AutoFirma."
}

verify_installation() {
    local installed_version

    command -v autofirma >/dev/null 2>&1 ||
        die "La instalación terminó, pero /usr/bin/autofirma no está disponible."

    [ -d /usr/lib64/AutoFirma ] || [ -d /usr/lib/AutoFirma ] ||
        die "No se encontró el directorio de instalación de AutoFirma."

    installed_version="$(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}' autofirma 2>/dev/null || true)"
    [ -n "$installed_version" ] ||
        die "rpm no registra el paquete autofirma como instalado."

    ok "AutoFirma instalada: $installed_version"
    ok "Ejecutable: $(command -v autofirma)"
    ok "Paquete RPM registrado correctamente."

    command -v java >/dev/null 2>&1 && ok "Java disponible después de la instalación."
    command -v certutil >/dev/null 2>&1 && ok "certutil disponible después de la instalación."
    command -v pk12util >/dev/null 2>&1 && ok "pk12util disponible después de la instalación."
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
    check_nss_tools
    download_official_zip
    extract_and_locate_rpm
    verify_rpm_sha256
    verify_rpm_metadata
    install_rpm
    verify_installation

    echo
    echo "=============================================="
    echo " Instalación completada"
    echo "=============================================="
    echo
    echo "AutoFirma ha sido instalada mediante el RPM oficial."
    echo "El propio RPM ha realizado su configuración de integración."
}

main "$@"
