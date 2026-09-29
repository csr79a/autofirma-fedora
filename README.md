# AutoFirma Fedora

Instalador y GUI para AutoFirma en Fedora Linux usando el **paquete RPM oficial** de AutoFirma.

El proyecto sigue la experiencia visual y técnica de la GUI de AutoFirma para CachyOS, pero adapta la lógica de instalación y mantenimiento a Fedora.

## Objetivos

- Instalar AutoFirma mediante el RPM oficial.
- Utilizar `dnf` para dependencias e instalación.
- Comprobar Java y herramientas NSS.
- Mantener la integración oficial de AutoFirma (`afirma://`) proporcionada por el RPM.
- Gestionar NSS y certificados de usuario de forma conservadora.
- Importar certificados `.p12/.pfx` sin guardar contraseñas en archivos ni argumentos.
- Verificar huellas digitales después de las operaciones de certificados.
- Proporcionar una GUI PyQt6 con PTY real, consola integrada, ANSI, entrada interactiva y cancelación.
- Separar la lógica Fedora del resto de proyectos AutoFirma.

## Estructura

```text
autofirma-fedora/
├── README.md
├── MANUAL.md
├── LICENSE
├── instalar_autofirma.sh
└── gui/
    └── autofirma_fedora_gui.py
```

## Estado

Proyecto inicial. La estructura se está preparando antes de implementar las operaciones definitivas de instalación, actualización, NSS, certificados y navegadores.

La aplicación no compila AutoFirma desde código fuente: utiliza el RPM oficial publicado para Fedora.

## Requisitos previstos

- Fedora Linux
- Python 3
- PyQt6 para la GUI
- Java/OpenJDK compatible con AutoFirma
- `nss-tools`
- `dnf`
- permisos administrativos únicamente para las operaciones que los requieran

Las versiones y dependencias definitivas se comprobarán contra el RPM oficial antes de cerrar el instalador.

## Seguridad

El proyecto evita almacenar contraseñas de certificados en archivos temporales o argumentos de procesos.

La gestión de certificados deberá verificar la huella del certificado antes y después de operaciones sensibles y evitar reemplazar silenciosamente un certificado existente cuando su identidad no coincida.

## Licencia

Consulta [LICENSE](LICENSE).

## Documentación

Consulta [MANUAL.md](MANUAL.md) para la arquitectura y el procedimiento de instalación previsto.
