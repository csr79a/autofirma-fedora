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
- protección por huella SHA-256 al instalar AutoFirma ROOT
"""

from __future__ import annotations

import os
import re
import select
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

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "instalar_autofirma.sh"
NSS_DIR = Path.home() / ".pki" / "nssdb"
AUTOFIRMA_ROOT_NAME = "AutoFirma_ROOT.cer"
AUTOFIRMA_NICKNAME = "AutoFirma ROOT"

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


def sha256_cert(path: Path) -> str | None:
    try:
        p = run_capture(
            ["openssl", "x509", "-in", str(path), "-noout", "-fingerprint", "-sha256"]
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode:
        return None
    return (
        p.stdout.strip()
        .replace("SHA256 Fingerprint=", "")
        .replace("sha256 Fingerprint=", "")
    )


def nss_certificates(db: Path):
    try:
        p = run_capture(["certutil", "-L", "-d", f"sql:{db}"])
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return p.returncode, p.stdout, p.stderr


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
    return (
        q.stdout.strip()
        .replace("SHA256 Fingerprint=", "")
        .replace("sha256 Fingerprint=", "")
    )


def pkcs12_fingerprint(path: Path, password: str) -> str | None:
    try:
        p = subprocess.run(
            [
                "openssl",
                "pkcs12",
                "-in",
                str(path),
                "-clcerts",
                "-nokeys",
                "-passin",
                "stdin",
            ],
            input=password,
            text=True,
            capture_output=True,
            timeout=60,
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
    return (
        q.stdout.strip()
        .replace("SHA256 Fingerprint=", "")
        .replace("sha256 Fingerprint=", "")
    )


def firefox_profiles() -> list[Path]:
    bases = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        bases.append(Path(xdg) / "mozilla" / "firefox")
    bases.append(Path.home() / ".mozilla" / "firefox")

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


def chromium_nss_dirs() -> list[Path]:
    result = []
    candidates = [
        Path.home() / ".pki" / "nssdb",
        Path.home() / ".config" / "google-chrome",
        Path.home() / ".config" / "chromium",
        Path.home() / ".config" / "BraveSoftware" / "Brave-Browser",
    ]
    for p in candidates:
        if p.is_dir() and (p / "cert9.db").exists():
            result.append(p)
    return list(dict.fromkeys(result))


def find_autofirma_root() -> Path | None:
    # AutoFirma genera su CA local en el perfil del usuario al inicializarse.
    # El RPM Fedora instala la aplicación en %{_libdir}/autofirma.
    candidates = [
        Path.home() / ".afirma" / "Autofirma" / AUTOFIRMA_ROOT_NAME,
        Path("/usr/lib64/autofirma") / AUTOFIRMA_ROOT_NAME,
        Path("/usr/lib/autofirma") / AUTOFIRMA_ROOT_NAME,
        Path("/usr/lib64/AutoFirma") / AUTOFIRMA_ROOT_NAME,
        Path("/usr/lib/AutoFirma") / AUTOFIRMA_ROOT_NAME,
        Path("/usr/share/AutoFirma") / AUTOFIRMA_ROOT_NAME,
    ]
    if shutil.which("rpm"):
        try:
            p = run_capture(["rpm", "-ql", "autofirma"])
            if p.returncode == 0:
                for line in p.stdout.splitlines():
                    candidate = Path(line.strip())
                    if candidate.name == AUTOFIRMA_ROOT_NAME and candidate.is_file():
                        candidates.insert(0, candidate)
        except (OSError, subprocess.SubprocessError):
            pass
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def find_autofirma_executable() -> str | None:
    direct = shutil.which("autofirma")
    if direct:
        return direct
    for path in ("/usr/bin/autofirma", "/usr/local/bin/autofirma"):
        if Path(path).is_file() and os.access(path, os.X_OK):
            return path
    return None


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
        if path.name == "autofirma.jar" and path.parent.is_dir():
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


def trust_root_in_db(db: Path, cert_path: Path):
    fingerprint = sha256_cert(cert_path)
    if not fingerprint:
        return False, f"{db}: no se pudo leer la huella SHA-256 del ROOT."

    existing = nss_fingerprint(db, AUTOFIRMA_NICKNAME)

    if existing and existing == fingerprint:
        try:
            p = run_capture(
                [
                    "certutil",
                    "-M",
                    "-d",
                    f"sql:{db}",
                    "-n",
                    AUTOFIRMA_NICKNAME,
                    "-t",
                    "C,,",
                ]
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"{db}: no se pudo actualizar la confianza: {exc}"
        if p.returncode:
            return False, f"{db}: {p.stderr.strip() or p.stdout.strip()}"
        if nss_fingerprint(db, AUTOFIRMA_NICKNAME) != fingerprint:
            return False, f"{db}: la huella cambió después de actualizar la confianza."
        return True, f"{db}: AutoFirma ROOT ya estaba instalado y verificado."

    if existing:
        return False, (
            f"{db}: ya existe «{AUTOFIRMA_NICKNAME}» con otra huella SHA-256. "
            "No se modifica por seguridad."
        )

    try:
        p = run_capture(
            [
                "certutil",
                "-A",
                "-d",
                f"sql:{db}",
                "-n",
                AUTOFIRMA_NICKNAME,
                "-t",
                "C,,",
                "-i",
                str(cert_path),
            ]
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{db}: no se pudo importar AutoFirma ROOT: {exc}"

    if p.returncode:
        return False, f"{db}: {p.stderr.strip() or p.stdout.strip()}"

    if nss_fingerprint(db, AUTOFIRMA_NICKNAME) != fingerprint:
        return False, f"{db}: importación realizada, pero la huella no coincide."

    return True, f"{db}: AutoFirma ROOT importado y verificado (C,,)."


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
            os.execvp(self.command[0], self.command)
        os.set_blocking(self.fd, False)

    def poll(self):
        if self.finished or self.fd is None:
            return
        try:
            ready, _, _ = select.select([self.fd], [], [], 0)
            if ready:
                data = os.read(self.fd, 16384)
                if data:
                    self.on_output(data.decode("utf-8", "replace"))
                else:
                    self.finish()
                    return
        except (OSError, EOFError):
            self.finish()
            return

        if self.pid:
            try:
                done, status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                done = self.pid
                status = 0
            if done:
                self.finish(os.waitstatus_to_exitcode(status) if status else 0)

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
        sig = signal.SIGKILL if now - self.last_cancel < 0.8 else signal.SIGINT
        try:
            os.kill(self.pid, sig)
        except OSError:
            pass
        self.last_cancel = now

    def finish(self, code: int | None = None):
        if self.finished:
            return
        self.finished = True

        fd = self.fd
        pid = self.pid
        self.fd = None

        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

        if code is None and pid:
            try:
                _, status = os.waitpid(pid, os.WNOHANG)
                code = os.waitstatus_to_exitcode(status) if status else 130
            except (OSError, ChildProcessError):
                code = 130

        self.on_done(code if code is not None else 0)


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
            "Instalación RPM oficial · NSS · certificados · navegadores · estado"
        )
        root.addWidget(subtitle)

        grid = QGridLayout()
        root.addLayout(grid)

        cards = [
            ("1. AutoFirma", "Instalar / reinstalar el RPM oficial", self.install),
            ("2. Lanzar AutoFirma", "Abrir AutoFirma instalada", self.launch),
            ("3. NSS", "Crear o comprobar ~/.pki/nssdb", self.nss_check),
            ("4. Certificado", "Importar certificado .p12 / .pfx", self.import_cert),
            ("5. Navegadores", "Confiar en AutoFirma ROOT", self.trust_browsers),
            ("6. Estado", "Comprobar instalación e integración", self.status),
            ("7. Versiones", "Consultar versiones oficiales", self.versions),
            ("8. Actualizar", "Volver a instalar la versión oficial fijada", self.update),
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

    def update(self):
        self.write("\n=== Actualizar AutoFirma ===")
        self.write(
            "El instalador usa la versión oficial fijada en instalar_autofirma.sh "
            "y verifica SHA-256 antes de instalar."
        )
        self.install()

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
                os.chmod(NSS_DIR.parent, 0o700)
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

            try:
                os.chmod(NSS_DIR, 0o700)
            except OSError as exc:
                self.write(f"ADVERTENCIA: no se pudo aplicar chmod 700: {exc}")

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
        if not fingerprint:
            self.write(
                "ERROR: no se pudo leer el certificado del PKCS#12. "
                "Comprueba la contraseña y el archivo."
            )
            return

        self.write("Huella SHA-256: " + fingerprint)

        rc, listing, err = nss_certificates(NSS_DIR)
        if rc:
            self.write("ERROR: el almacén NSS no se puede abrir.")
            self.write(err.strip())
            return

        for line in listing.splitlines():
            stripped = line.strip()
            if not stripped or stripped.lower().startswith("certificate"):
                continue
            nickname = stripped.split()[0]
            existing = nss_fingerprint(NSS_DIR, nickname)
            if existing == fingerprint:
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

        self.write("Certificado importado correctamente.")
        rc, out, err = nss_certificates(NSS_DIR)
        if rc == 0:
            self.write(out.strip())
        else:
            self.write(err.strip())

    def password_dialog(self, title: str, label: str):
        return QInputDialog.getText(
            self,
            title,
            label,
            QLineEdit.EchoMode.Password,
        )

    def trust_browsers(self):
        if not have("certutil"):
            QMessageBox.critical(
                self,
                "Falta NSS",
                "No está disponible certutil. Ejecuta «1. AutoFirma».",
            )
            return

        root = find_autofirma_root()
        if not root:
            QMessageBox.warning(
                self,
                "AutoFirma ROOT no encontrado",
                "No se encontró AutoFirma_ROOT.cer. Ejecuta AutoFirma una vez "
                "para que genere su CA local.",
            )
            return

        self.write(f"AutoFirma ROOT encontrado: {root}")
        self.write(f"SHA-256 ROOT: {sha256_cert(root) or 'no disponible'}")

        targets: list[Path] = []
        if NSS_DIR.is_dir() and (NSS_DIR / "cert9.db").exists():
            targets.append(NSS_DIR)
        targets.extend(firefox_profiles())
        targets.extend(chromium_nss_dirs())
        targets = list(dict.fromkeys(targets))

        if not targets:
            self.write(
                "No se encontraron almacenes NSS de navegador. "
                "Crea/inicia el navegador y vuelve a intentarlo."
            )
            return

        for db in targets:
            ok, msg = trust_root_in_db(db, root)
            self.write(("OK: " if ok else "ERROR: ") + msg)

        self.write(
            "Cierra completamente Firefox/Chromium/Chrome/Brave antes de probar "
            "de nuevo la integración."
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
            try:
                p = run_capture(["rpm", "-q", "autofirma"])
                self.write(
                    "Paquete RPM: "
                    + (p.stdout.strip() if p.returncode == 0 else "NO INSTALADO")
                )
            except (OSError, subprocess.SubprocessError):
                self.write("Paquete RPM: no se pudo consultar")

        root = find_autofirma_root()
        self.write(f"AutoFirma ROOT: {root or 'NO ENCONTRADO'}")
        if root:
            self.write(f"ROOT SHA-256: {sha256_cert(root) or 'no disponible'}")

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

    def versions(self):
        self.run_pty(
            "Consultar versiones oficiales de clienteafirma",
            [
                "bash",
                "-lc",
                "set -o pipefail; "
                "command -v curl >/dev/null || { echo 'ERROR: falta curl.'; exit 1; }; "
                "echo 'Tags recientes de clienteafirma:'; "
                "curl --fail --location --proto '=https' --tlsv1.2 --max-time 30 "
                "-H 'Accept: application/vnd.github+json' "
                "'https://api.github.com/repos/ctt-gob-es/clienteafirma/tags?per_page=15' "
                "| grep -E '\\"name\\": \\"v[0-9]' "
                "| sed -E 's/.*\\"name\\": \\"([^\\"]+).*/\\1/'",
            ],
        )


def main():
    if sys.version_info < (3, 10):
        print("Se requiere Python 3.10 o superior.", file=sys.stderr)
        raise SystemExit(1)

    app = QApplication(sys.argv)
    window = App()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
