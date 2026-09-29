# Manual — AutoFirma Fedora

## 1. Propósito

Este repositorio proporciona una instalación y administración de AutoFirma para Fedora basada en el **RPM oficial**.

La GUI seguirá el estilo de la versión de CachyOS, pero las operaciones internas serán específicas de Fedora.

## 2. Arquitectura

```text
GUI PyQt6
   │
   ├── operaciones gráficas: NSS, certificados, estado
   │
   └── instalar_autofirma.sh
             │
             ├── Fedora
             ├── Java
             ├── nss-tools
             ├── descarga oficial
             ├── verificación
             └── dnf/rpm
```

El RPM oficial conserva la responsabilidad de instalar los archivos propios de AutoFirma y realizar su configuración de integración.

## 3. GUI

La GUI prevista tendrá tarjetas para:

1. AutoFirma — instalar/actualizar y comprobar.
2. NSS — crear/comprobar el almacén.
3. Certificado — importar `.p12/.pfx` y verificar.
4. Navegadores — comprobar la integración y confianza.
5. Estado — diagnóstico de Java, NSS, AutoFirma y `afirma://`.
6. Versiones — versión instalada y versión oficial disponible.
7. Actualizar — actualizar únicamente cuando corresponda.

La consola integrada utilizará PTY real, renderizado ANSI, entrada interactiva y cancelación.

## 4. Instalación Fedora

El instalador deberá:

1. Verificar que el sistema sea Fedora.
2. Comprobar la arquitectura soportada.
3. Comprobar Java.
4. Comprobar/instalar `nss-tools`.
5. Obtener el RPM oficial.
6. Verificar el paquete antes de instalarlo.
7. Instalarlo mediante `dnf`.
8. Comprobar la instalación final.
9. Informar del estado de la integración.

No se duplicará en el script la configuración que ya realiza el RPM oficial.

## 5. NSS y certificados

El almacén de usuario se tratará de forma conservadora.

No se eliminará ni recreará automáticamente un almacén NSS existente.

La importación de PKCS#12 no deberá exponer la contraseña en la línea de comandos ni almacenarla en un archivo temporal.

Después de una importación se verificará el certificado mediante su huella.

## 6. Navegadores

La GUI comprobará la configuración disponible en el sistema y distinguirá entre:

- integración proporcionada por AutoFirma;
- confianza de certificados en NSS;
- configuración específica de cada navegador.

No se asumirá que las rutas de Debian o CachyOS son válidas en Fedora.

## 7. Seguridad

Antes de fijar mecanismos concretos de autenticidad del RPM se comprobará el procedimiento de distribución oficial de AutoFirma.

No se debe sustituir silenciosamente un certificado existente si su huella no coincide con la esperada.

## 8. Estado del proyecto

Este manual describe la arquitectura inicial. Las rutas, versiones y comprobaciones definitivas se cerrarán después de contrastarlas con el RPM Fedora oficial y su comportamiento real.
