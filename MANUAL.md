# Manual — AutoFirma Fedora

## 1. Propósito

Este repositorio proporciona la instalación y administración de AutoFirma 1.9 para Fedora basada en el **RPM oficial**. La lógica es específica de Fedora: no se asume que las rutas o comportamientos de Debian o CachyOS sean válidos.

## 2. Arquitectura

```text
GUI PyQt6 (gui/autofirma_fedora_gui.py)
   │
   ├── operaciones propias: NSS, certificado personal, estado, lanzar
   │
   └── instalar_autofirma.sh  (se ejecuta con sudo, dentro de un PTY)
             │
             ├── Fedora y arquitectura
             ├── Java (versión y soporte gráfico)
             ├── nss-tools y openssl
             ├── almacén NSS del usuario
             ├── descarga oficial + verificación ZIP
             ├── extracción + verificación RPM
             ├── dnf install
             └── verificación final + instalación de la GUI
```

El RPM oficial conserva la responsabilidad de instalar los archivos de AutoFirma y de su integración con el sistema y los navegadores. El script no duplica esa configuración.

## 3. Qué hace el RPM oficial

Contenido y scriptlets observados en `autofirma-1.9-1.noarch` (firmado RSA/SHA256, clave `f70b0257bf86a0cb`, build 2025-06-03):

**Archivos**

```text
/usr/bin/autofirma
/usr/lib64/autofirma/autofirma.jar
/usr/lib64/autofirma/autofirmaConfigurador.jar
/usr/lib64/autofirma/autofirma.png
/usr/lib64/firefox/defaults/pref/autofirma.js
/usr/share/applications/autofirma.desktop
/usr/share/metainfo/es.gob.afirma.metainfo.xml
/usr/share/licenses/autofirma/LICENSE
```

**Scriptlets**

| Fase | Acción |
|---|---|
| `preinstall` | Si Firefox está en ejecución, lo cierra con `pkill firefox` |
| `postinstall` | Ejecuta `java -Djava.awt.headless=true -jar autofirmaConfigurador.jar -install` y registra `x-scheme-handler/afirma=autofirma.desktop` en `/usr/share/applications/mimeapps.list` |
| `preuninstall` | Ejecuta `autofirmaConfigurador.jar -uninstall` (y `uninstall.sh` si existe) |
| `postuninstall` | Borra `/usr/lib64/autofirma` y la entrada de `mimeapps.list` |

El certificado raíz local («AutoFirma ROOT») y su instalación en los almacenes NSS de los navegadores los gestiona `autofirmaConfigurador.jar -install`. El RPM **no** incluye `AutoFirma_ROOT.cer`. Por eso la GUI no importa ese certificado a mano.

Si tras instalar hace falta repetir la integración (por ejemplo, un perfil de Firefox creado después):

```bash
sudo java -Djava.awt.headless=true -jar /usr/lib64/autofirma/autofirmaConfigurador.jar -install
```

## 4. Instalador (`instalar_autofirma.sh`)

Se puede ejecutar como usuario normal: se reejecuta con `sudo bash`. Orden de pasos:

1. **Fedora**: comprueba `ID=fedora` en `/etc/os-release`.
2. **Arquitectura**: `uname -m` debe coincidir con `rpm --eval %{_arch}` y ser una de `x86_64`, `aarch64`, `ppc64le`, `s390x`.
3. **Herramientas**: `dnf rpm curl unzip sha256sum awk find sed mktemp`.
4. **Java**: versión 8 o superior (se recomienda 17 o superior) y presencia de `libawt_xawt.so`. Si el Java pertenece a un paquete `*-headless`, instala el paquete equivalente sin `-headless`.
5. **`nss-tools` y `openssl`**: los instala con `dnf` si faltan.
6. **Almacén NSS del usuario**: para el usuario que lanzó `sudo`, crea `~/.pki/nssdb` (permisos 700, contraseña vacía) solo si no existe. Si existe con `cert9.db`, no lo toca; si existe con contenido pero sin `cert9.db`, avisa y no lo modifica.
7. **Descarga**: `Autofirma_Linux_Fedora.zip` desde `firmaelectronica.gob.es`, solo HTTPS, TLS 1.2 o superior, con reintentos.
8. **Verificación del ZIP**: SHA-256 contra la huella fijada. Si falla, no se extrae nada.
9. **Extracción**: el ZIP debe contener exactamente un RPM, con el nombre esperado.
10. **Verificación del RPM**: SHA-256 y metadatos (`name=autofirma`, `version=1.9`, `arch=noarch`).
11. **Instalación**: antes de `dnf install -y`, detecta Firefox abierto y pide confirmación. Esto es necesario porque el `preinstall` del RPM puede ejecutar `pkill firefox`.
12. **Comprobación final**: ejecutable en `/usr/bin`, directorio de instalación, paquete registrado en `rpm` y manejador `afirma://` mediante `xdg-mime`.
13. **GUI**: copia la GUI y el instalador a `/usr/share/autofirma-fedora/`, crea `/usr/bin/autofirma-fedora` y la entrada de menú.

La GUI se instala al final, después de verificar el RPM.

## 5. GUI

Cinco tarjetas:

1. **Instalar / actualizar**: lanza el instalador en un PTY. Es también la forma de forzar una reinstalación.
2. **Lanzar AutoFirma**: abre `/usr/bin/autofirma` desacoplado de la GUI.
3. **NSS**: crea o comprueba `~/.pki/nssdb`.
4. **Certificado**: importa un `.p12` / `.pfx` personal.
5. **Estado**: Java, `certutil`, `pk12util`, `openssl`, `xdg-mime`, `rpm`, `dnf`, ejecutable y directorio de AutoFirma, versión del RPM, certificados «AutoFirma» presentes en los almacenes NSS y manejador `afirma://`.

La consola integrada usa un PTY real. Limpia las secuencias ANSI y admite entrada interactiva. La primera cancelación escribe `\x03` en el PTY, equivalente a Ctrl+C; si el proceso no termina inmediatamente, la siguiente cancelación mata el grupo de procesos completo. El código de salida que se muestra es el real del proceso.

## 6. NSS y certificados

Ruta del almacén: `~/.pki/nssdb` (formato `sql:`, `cert9.db`). La detección de Firefox contempla `XDG_CONFIG_HOME`, `~/.mozilla/firefox` y el perfil de Firefox Flatpak en `~/.var/app/org.mozilla.firefox/.mozilla/firefox`. Se trata de forma conservadora: **no se elimina, recrea ni modifica** un almacén existente.

`certutil -N` **no crea el directorio** del almacén: hay que crearlo antes, o falla con `SEC_ERROR_BAD_DATABASE`. Tanto el instalador como la tarjeta NSS lo hacen.

### Importación de un PKCS#12

1. Selección del archivo y de la contraseña (diálogo con eco oculto).
2. Cálculo de la huella SHA-256 del certificado con `openssl pkcs12`. Si falla, reintenta con `-legacy`, necesario con OpenSSL 3 para archivos antiguos (por ejemplo, con RC2-40, habituales en certificados emitidos hace años). Si no consigue la huella, avisa y sigue, porque `pk12util` es quien valida realmente el archivo.
3. Si la huella ya existe en el almacén con cualquier nickname (incluidos los que llevan espacios), no se vuelve a importar.
4. Importación con `pk12util -w /dev/stdin`: la contraseña viaja por `stdin`, nunca por argumentos ni por archivos temporales.
5. Tras `pk12util`, se vuelve a abrir el almacén NSS, se recalculan las huellas SHA-256 y se comprueba que el certificado importado coincide con la huella del archivo de origen. Si no coincide, la GUI informa de un fallo de verificación.

## 7. Java

- AutoFirma necesita un Java con soporte gráfico. Con un paquete `-headless` el RPM se instala y el `postinstall` funciona (usa modo headless), pero la aplicación no abre ventana y cae a modo consola («No se puede crear el entorno grafico»).
- Fedora 44 solo ofrece `java-25-openjdk` (y `java-latest-openjdk`, que es la misma versión). Con esa versión AutoFirma 1.9 muestra un aviso de versión no soportada, de carácter informativo.
- Para una versión anterior habría que usar un JDK portátil y `JAVA_HOME`, lo que complicaría la integración con el navegador, que invoca `/usr/bin/autofirma`. Solo compensa si se comprueba un fallo real.

## 8. Seguridad

- **Autenticidad**: el instalador fija dos huellas SHA-256 calculadas sobre la descarga oficial:

  | Elemento | SHA-256 |
  |---|---|
  | `Autofirma_Linux_Fedora.zip` | `049bccfc298cca0cbd9819b7830a7d89829888e7b3df2337a4929433d4b49aa3` |
  | `autofirma-1.9-1.noarch_FEDORA.rpm` | `d76d7a65a62ace9b22983c9b0fdeaf5691e335e8de234cf94bd1b22f86ef42a9` |

  No se ha podido confirmar que el organismo publique huellas oficiales; estas se han calculado a partir de la descarga desde el dominio oficial. Si en el futuro el archivo se republica, la verificación fallará hasta actualizarlas.
- **Firma del RPM**: `rpm -K` muestra `NOKEY` porque la clave PGP (`gpg_sgad_publickey.asc`, incluida en el ZIP) no está importada. El instalador usa `rpm -K --nosignature` solo para comprobar que el archivo es un RPM válido; la integridad se apoya en las huellas fijadas.
- **Sin sustitución silenciosa**: no se sustituye un certificado existente si su identidad no coincide.
- **TLS**: la descarga usa `--proto '=https' --tlsv1.2` y no se desactiva la verificación de certificados. No se añade un fallback TLS inseguro.
- **Contraseñas**: no se guardan en disco ni en la línea de comandos.

### Actualizar a una nueva versión de AutoFirma

1. Descargar el ZIP oficial y calcular las huellas:

   ```bash
   d=$(mktemp -d) && cd "$d"
   curl --fail --location --proto '=https' --tlsv1.2 -o af.zip "<URL oficial>"
   unzip -q af.zip && sha256sum af.zip *.rpm
   rpm -qpi *.rpm | head -20
   rpm -qpl *.rpm
   rpm -qp --scripts *.rpm
   ```

2. Revisar los scriptlets y la lista de archivos.
3. Actualizar en `instalar_autofirma.sh`: `AUTOFIRMA_VERSION`, `AUTOFIRMA_RPM_NAME`, `AUTOFIRMA_ZIP_NAME`, `AUTOFIRMA_URL`, `AUTOFIRMA_ZIP_SHA256` y `AUTOFIRMA_RPM_SHA256`.

## 9. Desinstalación

```bash
sudo dnf remove autofirma
```

El RPM ejecuta su desinstalador (retira la configuración y la entrada `afirma://`). Para comprobar que no quedan restos del certificado raíz en los almacenes NSS:

```bash
certutil -d sql:$HOME/.pki/nssdb -L | grep -i autofirma
find ~/.mozilla -name cert9.db 2>/dev/null | while read -r db; do
  d=$(dirname "$db"); echo "== $d"; certutil -d sql:"$d" -L | grep -i autofirma
done
```

Si aparece, se borra con `certutil -d sql:<ruta> -D -n "<nickname exacto>"`.

## 10. Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `certutil: SEC_ERROR_BAD_DATABASE` | El almacén no existe o no está inicializado | Tarjeta **3. NSS**, o `mkdir -m 700 -p ~/.pki/nssdb && certutil -N -d sql:$HOME/.pki/nssdb --empty-password` |
| `[ERROR] La verificación SHA-256 … ha fallado` | El archivo descargado no coincide con la huella fijada | No instalar. Revisar el archivo con los comandos de la sección 8 |
| `sudo: … command not found` al lanzar el instalador | El script copiado sin permiso de ejecución | Ejecutarlo con `bash instalar_autofirma.sh`; la versión actual ya se reejecuta con `bash` |
| «No se puede crear el entorno grafico» | Java `-headless` sin AWT/X11 | El instalador instala el paquete completo; a mano: `sudo dnf install java-25-openjdk` |
| «Java 25 no está oficialmente soportado» | Aviso informativo de AutoFirma 1.9 | Marcar «No volver a mostrar» |
| El proceso termina con código 1 | Un paso del instalador falló | Leer la última línea `[ERROR]` de la consola |
| AutoFirma no es detectado desde el navegador | Integración no aplicada a ese perfil | Cerrar y reabrir el navegador; si persiste, repetir `-install` (sección 3) |
| Importación de `.p12` falla | Contraseña incorrecta o formato antiguo | Comprobar la contraseña; con OpenSSL 3 se reintenta con `-legacy` |

## 11. Estado del proyecto

Verificado en Fedora 44 (KDE Plasma, x86_64) con `java-25-openjdk`: descarga y verificación de huellas, instalación del RPM, creación del almacén NSS y apertura de la ventana de AutoFirma.

Pendiente de validar de extremo a extremo: firma real con certificado personal y detección de AutoFirma desde Firefox y Chromium con el comprobador oficial.