#!/usr/bin/env python3
"""
AutoFirma Fedora GUI

GUI inicial del proyecto.
La arquitectura seguirá el estilo de AutoFirma CachyOS:
- PyQt6
- PTY real
- consola integrada
- ANSI
- entrada interactiva
- cancelación
- tarjetas de acciones

La lógica definitiva se implementará después de cerrar la validación
del RPM oficial de Fedora.
"""

import sys

from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class AutoFirmaFedoraWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("AutoFirma Fedora")
        self.resize(900, 650)

        central = QWidget()
        layout = QVBoxLayout(central)

        title = QLabel("AutoFirma Fedora")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Instalador y herramientas para AutoFirma mediante el RPM oficial."
        )
        layout.addWidget(subtitle)

        button = QPushButton("Instalar / actualizar AutoFirma")
        button.clicked.connect(self.install_placeholder)
        layout.addWidget(button)

        status = QLabel(
            "Proyecto inicial: la implementación completa se añadirá "
            "después de validar el RPM Fedora."
        )
        status.setWordWrap(True)
        layout.addWidget(status)

        self.setCentralWidget(central)

    def install_placeholder(self) -> None:
        self.statusBar().showMessage(
            "La operación de instalación todavía está en construcción."
        )


def main() -> int:
    app = QApplication(sys.argv)
    window = AutoFirmaFedoraWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
