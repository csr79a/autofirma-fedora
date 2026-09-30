#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI de AutoFirma para Fedora.

Arquitectura:
- PyQt6
- PTY real para el instalador y consultas interactivas
- consola integrada con salida ANSI limpiada
- entrada interactiva y cancelación
- tarjetas de acciones
- NSS conservador: no recrea ni borra almacenes existentes
- importación PKCS#12 con contraseña por stdin, nunca por argv/archivo temporal
- la confianza de AutoFirma ROOT la gestiona el propio RPM (autofirmaConfigurador.jar -install)
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QInputDialog,
    QVBoxLayout,
    QWidget,
)

_GUI_DIR = Path(__file__).resolve().parent
_repo_root = _GUI_DIR.parent
_system_root = Path("/usr/share/autofirma-fedora")
ROOT = _repo_root if (_repo_root / "instalar_autofirma.sh").is_file() else _system_root
INSTALLER = ROOT / "instalar_autofirma.sh"
NSS_DIR = Path.home() / ".pki" / "nssdb"

ANSI_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)


def run_capture(args, input_text=None):
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=60,
    )


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def nss_certificates(db: Path):
    try:
        p = run_capture(["certutil", "-L", "-d", f"sql:{db}"])
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return p.returncode, p.stdout, p.stderr


NICK_RE = re.compile(r"^(?P<nick>.*\S)\s+(?P<trust>[pPcCTu,]+)\s*$")


def nss_nicknames(listing: str) -> list[str]:
    """Extrae los nicknames de `certutil -L`, respetando los que llevan espacios."""
    result = []
    for line in listing.splitlines():
        if not line.strip() or line.lstrip().startswith(("Certificate Nickname", "SSL,")):
            continue
        m = NICK_RE.match(line.rstrip())
        if m:
            result.append(m.group("nick").strip())
    return result


def nss_fingerprint(db: Path, nickname: str) -> str | None:
    try:
        p = run_capture(
            ["certutil", "-L", "-d", f"sql:{db}", "-n", nickname, "-a"]
        )
        if p.returncode:
            return None
        q = subprocess.run(
            ["openssl", "x509", "-noout", "-fingerprint", "-sha256"],
            input=p.stdout,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if q.returncode:
        return None
    return normalize_fingerprint(q.stdout)


def normalize_fingerprint(value: str) -> str:
    """Normaliza SHA-256 para comparar salidas de herramientas con formatos distintos."""
    value = re.sub(r"(?i)^.*sha256 fingerprint=", "", value.strip())
    return value.replace(":", "").replace(" ", "").upper()


def pkcs12_fingerprint(path: Path, password: str) -> str | None:
    base = ["openssl", "pkcs12", "-in", str(path), "-clcerts", "-nokeys", "-passin", "stdin"]
    for extra in ([], ["-legacy"]):
        try:
            p = subprocess.run(
                base + extra,
                input=password + "\n",
                text=True,
                capture_output=True,
                timeout=60,
            )
            if p.returncode:
                continue
            q = subprocess.run(
                ["openssl", "x509", "-noout", "-fingerprint", "-sha256"],
                input=p.stdout,
                text=True,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if q.returncode == 0:
            return normalize_fingerprint(q.stdout)
    return None


def firefox_profiles() -> list[Path]:
    bases = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        xdg_path = Path(xdg).expanduser()
        if xdg_path.is_absolute():
            bases.append(xdg_path / "mozilla" / "firefox")
    bases.extend(
        [
            Path.home() / ".mozilla" / "firefox",
            # Firefox instalado como Flatpak.
            Path.home() / ".var" / "app" / "org.mozilla.firefox" / ".mozilla" / "firefox",
        ]
    )

    result: list[Path] = []
    for base in dict.fromkeys(bases):
        if not base.is_dir():
            continue

        ini = base / "profiles.ini"
        if ini.is_file():
            current_path = None
            is_relative = True

            def add_profile():
                nonlocal current_path
                if not current_path:
                    return
                p = Path(current_path)
                if is_relative:
                    p = base / p
                if (p / "cert9.db").exists():
                    result.append(p)
                current_path = None

            for line in ini.read_text(errors="replace").splitlines():
                if line.startswith("["):
                    add_profile()
                    is_relative = True
                elif line.startswith("IsRelative="):
                    is_relative = line.split("=", 1)[1].strip() != "0"
                elif line.startswith("Path="):
                    add_profile()
                    current_path = line.split("=", 1)[1].strip()

            add_profile()

        for pattern in ("*.default", "*.default-*", "*.default-release"):
            for p in base.glob(pattern):
                if (p / "cert9.db").exists():
                    result.append(p)

    return list(dict.fromkeys(result))


def find_autofirma_executable() -> str | None:
    for name in ("autofirma", "AutoFirma"):
        direct = shutil.which(name)
        if direct:
            return direct
    for path in (
        "/usr/bin/autofirma",
        "/usr/bin/AutoFirma",
        "/usr/local/bin/autofirma",
        "/usr/local/bin/AutoFirma",
    ):
        if Path(path).is_file() and os.access(path, os.X_OK):
            return path
    return None


def installed_autofirma_version() -> str | None:
    if not have("rpm"):
        return None
    try:
        p = run_capture(["rpm", "-q", "--qf", "%{VERSION}", "autofirma"])
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode:
        return None
    value = p.stdout.strip()
    return value or None


def find_autofirma_install_dir() -> Path | None:
    if not have("rpm"):
        return None
    try:
        p = run_capture(["rpm", "-ql", "autofirma"])
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode:
        return None
    for line in p.stdout.splitlines():
        path = Path(line.strip())
        if path.name.lower() == "autofirma.jar" and path.parent.is_dir():
            return path.parent
    for candidate in (
        Path("/usr/lib64/autofirma"),
        Path("/usr/lib/autofirma"),
        Path("/usr/lib64/AutoFirma"),
        Path("/usr/lib/AutoFirma"),
    ):
        if candidate.is_dir():
            return candidate
    return None


class PtyRunner:
    def __init__(self, command, on_output, on_done):
        self.command = command
        self.on_output = on_output
        self.on_done = on_done
        self.pid = None
        self.fd = None
        self.finished = False
        self.last_cancel = 0.0

    def start(self):
        import pty

        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            try:
                os.execvp(self.command[0], self.command)
            except OSError as exc:
                try:
                    os.write(self.fd, f"\r\nERROR al ejecutar {self.command[0]}: {exc}\r\n".encode())
                except OSError:
                    pass
                os._exit(127)
        os.set_blocking(self.fd, False)

    def _drain(self):
        """Lee todo lo pendiente del PTY para no perder las últimas líneas."""
        while self.fd is not None:
            try:
                data = os.read(self.fd, 16384)
            except BlockingIOError:
                return
            except OSError:
                return  # EIO: el hijo cerró el PTY
            if not data:
                return
            self.on_output(data.decode("utf-8", "replace"))

    def poll(self):
        if self.finished or self.fd is None:
            return
        self._drain()
        try:
            done, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            done, status = self.pid, 0
        if done:
            self._drain()
            self.finish(os.waitstatus_to_exitcode(status))

    def send(self, text: str):
        if self.fd is not None:
            try:
                os.write(self.fd, text.encode())
            except OSError:
                pass

    def cancel(self):
        if not self.pid:
            return

        now = time.monotonic()
        if now - self.last_cancel < 0.8:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except OSError:
                try:
                    os.kill(self.pid, signal.SIGKILL)
                except OSError:
                    pass
        else:
            # Equivale a Ctrl+C en el PTY y permite que bash/dnf limpie
            # normalmente antes de recurrir a SIGKILL.
            try:
                os.write(self.fd, b"\x03")
            except OSError:
                try:
                    os.killpg(self.pid, signal.SIGINT)
                except OSError:
                    try:
                        os.kill(self.pid, signal.SIGINT)
                    except OSError:
                        pass
        self.last_cancel = now

    def finish(self, code: int):
        if self.finished:
            return
        self.finished = True
        fd, self.fd = self.fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        self.on_done(code)


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.runner: PtyRunner | None = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_runner)

        self.setWindowTitle("AutoFirma · Fedora")
        self.resize(1120, 780)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)

        title = QLabel("AutoFirma · Fedora")
        title.setFont(QFont("Sans", 24, QFont.Weight.Bold))
        root.addWidget(title)

        subtitle = QLabel(
            "Instalación RPM oficial · certificados · estado"
        )
        root.addWidget(subtitle)

        grid = QGridLayout()
        root.addLayout(grid)

        cards = [
            ("1. Instalar / actualizar", "Instala o reinstala el RPM oficial (verifica SHA-256)", self.install),
            ("2. Lanzar AutoFirma", "Abrir AutoFirma instalada", self.launch),
            ("3. NSS", "Crear o comprobar ~/.pki/nssdb", self.nss_check),
            ("4. Certificado", "Importar certificado personal .p12 / .pfx", self.import_cert),
            ("5. Estado", "Comprobar instalación e integración", self.status),
        ]

        for i, (head, desc, fn) in enumerate(cards):
            box = QGroupBox(head)
            lay = QVBoxLayout(box)
            lab = QLabel(desc)
            lab.setWordWrap(True)
            lay.addWidget(lab)
            button = QPushButton("Abrir")
            button.clicked.connect(fn)
            lay.addWidget(button)
            grid.addWidget(box, i // 2, i % 2)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Monospace", 10))
        root.addWidget(self.log, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        root.addWidget(self.progress)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(
            "Entrada para el proceso (contraseña / s / n / confirmación...)"
        )
        self.input.returnPressed.connect(self.send_input)
        row.addWidget(self.input, 1)

        send = QPushButton("Enviar")
        send.clicked.connect(self.send_input)
        row.addWidget(send)

        clear = QPushButton("Limpiar consola")
        clear.clicked.connect(self.log.clear)
        row.addWidget(clear)

        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(self.cancel_runner)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.cancel_button)

        root.addLayout(row)

    def write(self, text: str):
        clean = ANSI_RE.sub("", text).replace("\r", "\n")
        if self.runner:
            tail = clean.rstrip().lower()
            asks_secret = bool(re.search(r"(contraseña|password)[^\n]*:$", tail))
            self.input.setEchoMode(
                QLineEdit.EchoMode.Password if asks_secret else QLineEdit.EchoMode.Normal
            )
        if clean.strip():
            self.log.appendPlainText(clean.rstrip("\n"))
            self.log.ensureCursorVisible()

    def run_pty(self, title: str, command: list[str]):
        if self.runner:
            QMessageBox.warning(
                self,
                "Proceso activo",
                "Termina o cancela el proceso actual antes de iniciar otro.",
            )
            return

        self.write(f"\n=== {title} ===")
        self.write("$ " + " ".join(command))

        self.runner = PtyRunner(command, self.write, self.finished)
        try:
            self.runner.start()
        except OSError as exc:
            self.runner = None
            QMessageBox.critical(self, "Error", f"No se pudo iniciar el proceso:\n{exc}")
            return

        self.progress.show()
        self.cancel_button.setEnabled(True)
        self.timer.start(40)

    def _poll_runner(self):
        if self.runner:
            self.runner.poll()

    def finished(self, code: int):
        self.timer.stop()
        self.progress.hide()
        self.cancel_button.setEnabled(False)
        self.input.setEchoMode(QLineEdit.EchoMode.Normal)
        self.write(f"=== Proceso terminado: código {code} ===")
        self.runner = None

    def send_input(self):
        if self.runner:
            self.runner.send(self.input.text() + "\n")
            self.input.clear()

    def cancel_runner(self):
        if self.runner:
            self.runner.cancel()
            self.write("Se ha solicitado la cancelación. Pulsa otra vez si no termina.")

    def install(self):
        if not INSTALLER.is_file():
            QMessageBox.critical(self, "Error", f"No se encuentra:\n{INSTALLER}")
            return
        self.run_pty(
            "Instalar / reinstalar AutoFirma",
            ["bash", str(INSTALLER)],
        )

    def launch(self):
        executable = find_autofirma_executable()
        if not executable:
            QMessageBox.warning(
                self,
                "AutoFirma no instalada",
                "No se encontró /usr/bin/autofirma. Ejecuta primero «1. AutoFirma».",
            )
            return

        self.write(f"Lanzando AutoFirma: {executable}")
        try:
            subprocess.Popen(
                [executable],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            QMessageBox.critical(self, "Error", f"No se pudo lanzar AutoFirma:\n{exc}")

    def nss_check(self):
        if not have("certutil"):
            QMessageBox.critical(
                self,
                "Falta NSS",
                "No está disponible certutil. Pulsa «1. AutoFirma» para que "
                "el instalador compruebe/instale nss-tools.",
            )
            return

        if not NSS_DIR.exists():
            try:
                NSS_DIR.parent.mkdir(parents=True, exist_ok=True)
                NSS_DIR.mkdir(mode=0o700)  # certutil -N no crea el directorio
                p = subprocess.run(
                    ["certutil", "-N", "-d", f"sql:{NSS_DIR}", "--empty-password"],
                    text=True,
                    capture_output=True,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                self.write(f"ERROR creando NSS: {exc}")
                return

            if p.returncode:
                self.write("ERROR creando NSS: " + (p.stderr or p.stdout).strip())
                return

            self.write(f"NSS creado: {NSS_DIR} (contraseña vacía)")
        elif not (NSS_DIR / "cert9.db").exists():
            try:
                entries = list(NSS_DIR.iterdir())
            except OSError as exc:
                self.write(f"ERROR leyendo NSS: {exc}")
                return
            if entries:
                self.write(
                    f"ERROR: {NSS_DIR} existe pero no contiene cert9.db y tiene otros datos. "
                    "No se modifica por seguridad."
                )
                return
            try:
                p = subprocess.run(
                    ["certutil", "-N", "-d", f"sql:{NSS_DIR}", "--empty-password"],
                    text=True,
                    capture_output=True,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                self.write(f"ERROR inicializando NSS vacío: {exc}")
                return
            if p.returncode:
                self.write("ERROR inicializando NSS: " + (p.stderr or p.stdout).strip())
                return
            os.chmod(NSS_DIR, 0o700)
            self.write(f"NSS inicializado: {NSS_DIR} (contraseña vacía)")
        else:
            self.write(f"NSS ya existe: {NSS_DIR}")
            self.write("No se recrea, no se borra y no se modifica.")

        rc, out, err = nss_certificates(NSS_DIR)
        if rc == 0:
            self.write(out.strip() or "NSS válido.")
        else:
            self.write("ERROR: certutil no puede abrir el almacén NSS.")
            self.write(err.strip())

    def import_cert(self):
        if not have("pk12util"):
            QMessageBox.critical(
                self,
                "Falta NSS Tools",
                "No se encontró pk12util. Ejecuta primero «1. AutoFirma».",
            )
            return

        if not NSS_DIR.exists() or not (NSS_DIR / "cert9.db").exists():
            self.nss_check()
        if not NSS_DIR.exists() or not (NSS_DIR / "cert9.db").exists():
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar certificado personal",
            str(Path.home()),
            "Certificados PKCS#12 (*.p12 *.pfx)",
        )
        if not path:
            return

        password, ok = self.password_dialog(
            "Contraseña del certificado",
            "Contraseña del archivo .p12/.pfx:",
        )
        if not ok:
            return

        cert = Path(path)
        self.write(f"Comprobando certificado: {cert.name}")

        fingerprint = pkcs12_fingerprint(cert, password)
        if fingerprint:
            self.write("Huella SHA-256: " + fingerprint)
        else:
            self.write(
                "ADVERTENCIA: no se pudo calcular la huella con openssl "
                "(contraseña incorrecta o formato antiguo). pk12util validará el archivo."
            )

        rc, listing, err = nss_certificates(NSS_DIR)
        if rc:
            self.write("ERROR: el almacén NSS no se puede abrir.")
            self.write(err.strip())
            return

        if fingerprint:
            for nickname in nss_nicknames(listing):
                if nss_fingerprint(NSS_DIR, nickname) == fingerprint:
                    self.write(
                        f"El certificado ya está presente en NSS como «{nickname}»."
                    )
                    return

        self.write(f"Importando certificado personal: {cert.name}")
        try:
            p = subprocess.run(
                [
                    "pk12util",
                    "-d",
                    f"sql:{NSS_DIR}",
                    "-i",
                    str(cert),
                    "-w",
                    "/dev/stdin",
                ],
                input=password + "\n",
                text=True,
                capture_output=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.write(f"ERROR al importar: {exc}")
            return

        if p.returncode:
            self.write("ERROR al importar: " + (p.stderr or p.stdout).strip())
            return

        rc, out, err = nss_certificates(NSS_DIR)
        if rc:
            self.write("ERROR: la importación terminó, pero no se pudo volver a abrir el almacén NSS.")
            self.write(err.strip())
            return

        if fingerprint:
            imported_nicknames = nss_nicknames(out)
            verified = [
                nickname
                for nickname in imported_nicknames
                if nss_fingerprint(NSS_DIR, nickname) == fingerprint
            ]
            if not verified:
                self.write(
                    "ERROR: pk12util terminó correctamente, pero la huella SHA-256 "
                    "del certificado importado no coincide con la del archivo de origen."
                )
                return
            self.write(
                "Certificado importado y verificado por SHA-256 en NSS como: "
                + ", ".join(f"«{nickname}»" for nickname in verified)
            )
        else:
            self.write(
                "ADVERTENCIA: certificado importado, pero no se pudo calcular la "
                "huella SHA-256 de origen; no fue posible realizar la verificación posterior."
            )

        self.write(out.strip() or "Importación verificada correctamente.")

    def password_dialog(self, title: str, label: str):
        return QInputDialog.getText(
            self,
            title,
            label,
            QLineEdit.EchoMode.Password,
        )

    def status(self):
        self.write("\n=== Estado de AutoFirma Fedora ===")

        for cmd in ("java", "certutil", "pk12util", "openssl", "xdg-mime", "rpm", "dnf"):
            self.write(f"{cmd}: {'OK' if have(cmd) else 'FALTA'}")

        self.write(f"Instalador: {'OK' if INSTALLER.is_file() else 'FALTA'}")

        executable = find_autofirma_executable()
        self.write(f"Ejecutable AutoFirma: {executable or 'NO ENCONTRADO'}")
        install_dir = find_autofirma_install_dir()
        self.write(f"Directorio AutoFirma: {install_dir or 'NO ENCONTRADO'}")

        if have("rpm"):
            installed = installed_autofirma_version()
            self.write(
                "Versión RPM: "
                + (installed if installed else "NO INSTALADA")
            )

        stores = ([NSS_DIR] if (NSS_DIR / "cert9.db").exists() else []) + firefox_profiles()
        if not stores:
            self.write("Almacenes NSS: ninguno encontrado")
        elif have("certutil"):
            for db in stores:
                rc, out, _ = nss_certificates(db)
                found = [n for n in nss_nicknames(out) if "autofirma" in n.lower()] if rc == 0 else []
                self.write(f"AutoFirma en {db}: " + (", ".join(found) if found else "no hay certificado AutoFirma"))

        self.write(f"NSS: {'EXISTE' if NSS_DIR.exists() else 'NO EXISTE'}")

        if NSS_DIR.exists() and have("certutil"):
            rc, out, err = nss_certificates(NSS_DIR)
            self.write("NSS: VÁLIDO" if rc == 0 else "NSS: ERROR")
            if rc:
                self.write(err.strip())
            elif out.strip():
                self.write(out.strip())

        if have("xdg-mime"):
            try:
                p = run_capture(
                    ["xdg-mime", "query", "default", "x-scheme-handler/afirma"]
                )
                self.write("afirma://: " + (p.stdout.strip() or "no registrado"))
            except (OSError, subprocess.SubprocessError):
                self.write("afirma://: no se pudo consultar")


def main():
    if sys.version_info < (3, 10):
        print("Se requiere Python 3.10 o superior.", file=sys.stderr)
        raise SystemExit(1)

    if os.geteuid() == 0:
        print(
            "La GUI no debe ejecutarse como root. Iníciala como usuario normal "
            "para acceder a tu almacén NSS y a tus perfiles de Firefox.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("AutoFirma Fedora")
    app.setOrganizationName("AutoFirma Fedora")
    app.setDesktopFileName("autofirma-fedora")
    window = App()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()