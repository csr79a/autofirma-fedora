# AutoFirma Fedora

Instalador y GUI para AutoFirma en Fedora Linux usando el **paquete RPM oficial** de AutoFirma 1.9.

La aplicación no compila AutoFirma desde código fuente ni redistribuye el paquete: lo descarga del dominio oficial (`firmaelectronica.gob.es`), verifica su integridad y lo instala con `dnf`.

## Qué hace

- Descarga `Autofirma_Linux_Fedora.zip` y verifica su **SHA-256** antes de extraerlo. Después verifica el **SHA-256 del RPM** y sus metadatos (nombre, versión, arquitectura) antes de instalarlo.
- Instala con `dnf`, que resuelve las dependencias.
- Comprueba que Java sea utilizable: versión mínima y **soporte gráfico (AWT/X11)**. Si Java no está instalado, ofrece instalar un OpenJDK disponible (priorizando 17); si el Java instalado es un paquete `-headless`, instala automáticamente el equivalente con interfaz.
- Instala `nss-tools` y `openssl` si faltan.
- Crea el almacén NSS del usuario (`~/.pki/nssdb`) si no existe. Si existe, no lo toca.
- Deja la integración con el navegador (`afirma://`, certificado raíz «AutoFirma ROOT») a cargo del propio RPM oficial.
- Ofrece una GUI PyQt6 con consola integrada (PTY real, ANSI limpiado, entrada interactiva y cancelación mediante Ctrl+C (\x03) y grupo de procesos).
- Detecta perfiles de Firefox tradicionales, configurados mediante `XDG_CONFIG_HOME` y Firefox Flatpak.
- Verifica por SHA-256 que el certificado personal importado por `pk12util` coincide con el certificado de origen.
- Verifica después de instalar el RPM que `xdg-mime` tenga registrado el manejador `afirma://`.

## Estructura del repositorio

```text
autofirma-fedora/
├── README.md
├── MANUAL.md
├── LICENSE
├── instalar_autofirma.sh
└── gui/
    └── autofirma_fedora_gui.py
```

Al ejecutar `instalar_autofirma.sh`, la GUI y el instalador se copian al sistema:

| Ruta | Contenido |
|---|---|
| `/usr/share/autofirma-fedora/` | `autofirma_fedora_gui.py` e `instalar_autofirma.sh` |
| `/usr/bin/autofirma-fedora` | Lanzador de la GUI |
| `/usr/share/applications/autofirma-fedora.desktop` | Entrada de menú «AutoFirma · Fedora» |

## Requisitos

- Fedora Linux (x86_64, aarch64, ppc64le o s390x; el RPM es `noarch`)
- `dnf`, `rpm`, `curl`, `unzip`
- Python 3.10 o superior y PyQt6 (solo para la GUI)
- Permisos de administrador (`sudo`)

Java, `nss-tools` y `openssl` se comprueban y, cuando es posible, se instalan.

## Uso

Desde el repositorio:

```bash
git clone <URL-del-repositorio> autofirma-fedora
cd autofirma-fedora
bash instalar_autofirma.sh
```

Después, la GUI está en el menú («AutoFirma · Fedora») o con:

```bash
autofirma-fedora
```

### Tarjetas de la GUI

| Tarjeta | Función |
|---|---|
| 1. Instalar / actualizar | Ejecuta el instalador (descarga, verificación e instalación del RPM) |
| 2. Lanzar AutoFirma | Abre AutoFirma instalada |
| 3. NSS | Crea o comprueba `~/.pki/nssdb` sin recrear ni borrar uno existente |
| 4. Certificado | Importa un certificado personal `.p12` / `.pfx` al almacén NSS |
| 5. Estado | Diagnóstico de Java, NSS, AutoFirma y el manejador `afirma://` |

## Desinstalar

```bash
sudo dnf remove autofirma
```

El propio RPM ejecuta su desinstalador (`autofirmaConfigurador.jar -uninstall`). La GUI del proyecto se elimina borrando `/usr/share/autofirma-fedora`, `/usr/bin/autofirma-fedora` y `/usr/share/applications/autofirma-fedora.desktop`.

## Avisos conocidos

- **Java 25.** Fedora 44 solo ofrece `java-25-openjdk`. AutoFirma 1.9 muestra un aviso de que esa versión no está oficialmente soportada; es informativo y se puede marcar «No volver a mostrar».
- **Firefox está abierto durante la instalación.** El instalador detecta esta situación y pide confirmación antes de continuar, porque el `preinstall` del RPM puede ejecutar `pkill firefox`.
- **`NOKEY` en `rpm -K`.** El RPM está firmado con una clave que no está importada en el sistema. Es normal y no indica corrupción.

## Estado de la verificación

Probado en Fedora 44 (KDE Plasma, x86_64) con `java-25-openjdk`: descarga, verificación de huellas, instalación del RPM, creación del almacén NSS y apertura de la ventana de AutoFirma.

Pendiente de validar de extremo a extremo: firma real de un documento con certificado personal y detección de AutoFirma desde el navegador con el comprobador oficial.

## Seguridad

- La descarga se hace solo por HTTPS (TLS 1.2 o superior) desde la URL oficial fijada.
- El ZIP y el RPM se rechazan si su SHA-256 no coincide con el fijado en el instalador.
- La contraseña de un `.p12` nunca se pasa por línea de comandos ni se guarda en archivos temporales: se envía por `stdin`.
- La GUI rechaza ejecución como root para no operar sobre `/root/.pki/nssdb` ni sobre perfiles de navegador equivocados.
- Un almacén NSS existente no se elimina, recrea ni modifica.

## Licencia

Consulta [LICENSE](LICENSE).

## Documentación

Consulta [MANUAL.md](MANUAL.md) para la arquitectura, el detalle del instalador y la resolución de problemas.