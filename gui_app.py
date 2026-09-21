#!/usr/bin/env python3
"""JudgeAI v0.9 desktop application."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

try:
    from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
    from PyQt6.QtGui import (
        QDesktopServices,
        QDragEnterEvent,
        QDropEvent,
        QFont,
        QPageSize,
        QPainter,
        QPdfWriter,
        QPen,
        QTextDocument,
    )
    from PyQt6.QtWidgets import (
        QApplication,
        QAbstractItemView,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSizePolicy,
        QStackedWidget,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    print("ERROR: PyQt6 not installed. Run: pip install PyQt6")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def cli_prefix() -> list[str]:
    """Command prefix for the canonical CLI in source and packaged builds."""
    if getattr(sys, "frozen", False):
        name = "JudgeAI-CLI.exe" if os.name == "nt" else "JudgeAI-CLI"
        candidate = Path(sys.executable).resolve().with_name(name)
        if not candidate.exists():
            raise RuntimeError(
                f"Packaged CLI helper not found: {candidate}. Reinstall JudgeAI or rebuild the desktop bundle."
            )
        return [str(candidate)]
    return [sys.executable, str(PROJECT_ROOT / "judge.py")]


def runtime_cwd() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else PROJECT_ROOT

from src.bedrock_client import build_client
from src.config import (
    clear_api_key,
    get_available_providers,
    get_gui_defaults,
    get_model_preference,
    load_config,
    load_into_environment,
    set_api_key,
    set_gui_defaults,
    set_model_preference,
    set_provider_preference,
)
from src.gui_services import (
    classify_run_error,
    combined_report,
    estimate_cost_usd,
    preflight_transcript,
)
from src.judging import PARADIGMS
from src.llm_client import CredentialsError
from src.storage import LocalDiskBallotStore, StorageError
from src.version import VERSION_LABEL


COLORS = {
    "primary": "#3B82F6",
    "primary_hover": "#2563EB",
    "success": "#10B981",
    "warning": "#F59E0B",
    "error": "#EF4444",
    "background": "#F9FAFB",
    "surface": "#FFFFFF",
    "border": "#E5E7EB",
    "text": "#111827",
    "text_secondary": "#6B7280",
    "selected": "#EFF6FF",
}


class CleanComboBox(QComboBox):
    """QComboBox with a reliably visible chevron on Windows."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(Qt.GlobalColor.black)
        pen.setWidthF(1.6)
        painter.setPen(pen)
        center_x = self.width() - 20
        center_y = self.height() // 2 - 2
        painter.drawLine(center_x - 5, center_y, center_x, center_y + 5)
        painter.drawLine(center_x, center_y + 5, center_x + 5, center_y)
        painter.end()


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JudgeAI Settings")
        self.setMinimumWidth(620)
        self.paradigm_checks: dict[str, QCheckBox] = {}
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        title = QLabel("⚙️ Settings")
        title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        layout.addWidget(title)

        provider_group = QGroupBox("Model provider")
        provider_form = QFormLayout(provider_group)
        self.provider_combo = CleanComboBox()
        self.provider_combo.addItems(["Auto-detect", "Anthropic API", "OpenAI API"])
        provider_form.addRow("Provider:", self.provider_combo)

        self.openai_model = QLineEdit()
        self.openai_model.setPlaceholderText("Default: gpt-5.6-luna")
        provider_form.addRow("OpenAI model:", self.openai_model)

        self.anthropic_model = QLineEdit()
        self.anthropic_model.setPlaceholderText("Default: claude-sonnet-4-5-20250929")
        provider_form.addRow("Anthropic model:", self.anthropic_model)
        layout.addWidget(provider_group)

        keys_group = QGroupBox("API keys")
        keys_form = QFormLayout(keys_group)
        self.anthropic_key = QLineEdit()
        self.anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_key.setPlaceholderText("sk-ant-...")
        self.anthropic_status = QLabel()
        anthropic_row = QHBoxLayout()
        anthropic_row.addWidget(self.anthropic_key, 1)
        anthropic_row.addWidget(self.anthropic_status)
        keys_form.addRow("Anthropic:", anthropic_row)

        self.openai_key = QLineEdit()
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key.setPlaceholderText("sk-...")
        self.openai_status = QLabel()
        openai_row = QHBoxLayout()
        openai_row.addWidget(self.openai_key, 1)
        openai_row.addWidget(self.openai_status)
        keys_form.addRow("OpenAI:", openai_row)
        layout.addWidget(keys_group)

        defaults_group = QGroupBox("Round defaults")
        defaults_layout = QVBoxLayout(defaults_group)
        run_row = QHBoxLayout()
        run_row.addWidget(QLabel("Runs per paradigm:"))
        self.default_runs = CleanComboBox()
        for runs, label in ((1, "1 — Fast / cheapest"), (3, "3 — Recommended"), (5, "5 — More stable")):
            self.default_runs.addItem(label, runs)
        run_row.addWidget(self.default_runs)
        run_row.addStretch()
        defaults_layout.addLayout(run_row)

        checks = QGridLayout()
        for index, (key, paradigm) in enumerate(PARADIGMS.items()):
            check = QCheckBox(paradigm.display_name)
            self.paradigm_checks[key] = check
            checks.addWidget(check, index // 2, index % 2)
        defaults_layout.addLayout(checks)
        layout.addWidget(defaults_group)

        note = QLabel(
            "Saved keys stay on this computer in ~/.judgeai/config.json. "
            "Model IDs are optional overrides; leave them blank to use JudgeAI defaults."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.setStyleSheet(f"""
            QDialog {{ background: {COLORS['background']}; }}
            QGroupBox {{
                background: {COLORS['surface']}; border: 1px solid {COLORS['border']};
                border-radius: 10px; margin-top: 8px; padding: 14px; font-weight: 600;
            }}
            QLineEdit {{
                background: white; border: 1px solid {COLORS['border']};
                border-radius: 7px; padding: 9px;
            }}
            QComboBox {{
                background: white; border: 1px solid {COLORS['border']};
                border-radius: 7px; padding: 8px 42px 8px 10px; min-height: 22px;
            }}
            QComboBox::drop-down {{ width: 38px; border: none; background: transparent; }}
            QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
            QPushButton {{
                padding: 9px 18px; border-radius: 7px;
                border: 1px solid {COLORS['border']}; background: white;
            }}
            QPushButton#primary {{ color: white; background: {COLORS['primary']}; border: none; }}
        """)

    def _set_status(self, label: QLabel, configured: bool):
        label.setText("Configured ✓" if configured else "Not configured")
        label.setStyleSheet(
            f"color: {COLORS['success'] if configured else COLORS['text_secondary']}; font-weight: 600;"
        )

    def _load(self):
        config = load_config()
        anthropic = os.environ.get("ANTHROPIC_API_KEY") or config.get("anthropic_api_key", "")
        openai = os.environ.get("OPENAI_API_KEY") or config.get("openai_api_key", "")
        self.anthropic_key.setText(anthropic)
        self.openai_key.setText(openai)
        self._set_status(self.anthropic_status, bool(anthropic))
        self._set_status(self.openai_status, bool(openai))

        self.openai_model.setText(get_model_preference("openai") or "")
        self.anthropic_model.setText(get_model_preference("anthropic") or "")

        pref = (os.environ.get("LLM_PROVIDER") or config.get("provider_preference", "auto") or "auto").lower()
        self.provider_combo.setCurrentText(
            "Anthropic API" if pref == "anthropic" else "OpenAI API" if pref == "openai" else "Auto-detect"
        )

        defaults = get_gui_defaults()
        index = self.default_runs.findData(defaults["default_runs"])
        self.default_runs.setCurrentIndex(max(0, index))
        selected = set(defaults["default_paradigms"])
        for key, check in self.paradigm_checks.items():
            check.setChecked(key in selected)

    def _save(self):
        try:
            anthropic = self.anthropic_key.text().strip()
            openai = self.openai_key.text().strip()
            set_api_key("anthropic", anthropic) if anthropic else clear_api_key("anthropic")
            set_api_key("openai", openai) if openai else clear_api_key("openai")

            selected = self.provider_combo.currentText()
            set_provider_preference(
                "anthropic" if selected == "Anthropic API" else "openai" if selected == "OpenAI API" else "auto"
            )
            set_model_preference("openai", self.openai_model.text())
            set_model_preference("anthropic", self.anthropic_model.text())

            paradigms = [key for key, check in self.paradigm_checks.items() if check.isChecked()]
            if not paradigms:
                QMessageBox.warning(self, "Round defaults", "Choose at least one default paradigm.")
                return
            set_gui_defaults(int(self.default_runs.currentData() or 3), paradigms)
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Settings Error", f"Could not save settings:\n\n{exc}")


class RoundSetupDialog(QDialog):
    """Review zero-cost metadata and judging options before any paid calls."""

    def __init__(self, preflight, defaults: dict, provider: str, model: str, parent=None):
        super().__init__(parent)
        self.preflight = preflight
        self.provider = provider
        self.model = model
        self.paradigm_checks: dict[str, QCheckBox] = {}
        self.setWindowTitle("Review Round")
        self.setMinimumWidth(700)
        self._build_ui(defaults)
        self._update_estimate()

    def _build_ui(self, defaults: dict):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("Review round before judging")
        title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        layout.addWidget(title)
        subtitle = QLabel(
            f"{self.preflight.path.name} • zero-cost local detection. Edit anything that looks wrong."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(subtitle)

        meta_group = QGroupBox("Round information")
        form = QFormLayout(meta_group)
        self.format_combo = CleanComboBox()
        self.format_combo.addItem("LD — Lincoln-Douglas", "LD")
        form.addRow("Format:", self.format_combo)

        self.resolution = QLineEdit(self.preflight.resolution or "")
        self.resolution.setPlaceholderText("Resolution (optional)")
        form.addRow("Resolution:", self.resolution)

        self.aff = QLineEdit(self.preflight.aff or "")
        self.aff.setPlaceholderText("Aff speaker/team (optional)")
        form.addRow("Aff:", self.aff)

        self.neg = QLineEdit(self.preflight.neg or "")
        self.neg.setPlaceholderText("Neg speaker/team (optional)")
        form.addRow("Neg:", self.neg)
        layout.addWidget(meta_group)

        judging_group = QGroupBox("Judging")
        judging_layout = QVBoxLayout(judging_group)
        grid = QGridLayout()
        selected = set(defaults.get("default_paradigms") or PARADIGMS.keys())
        for index, (key, paradigm) in enumerate(PARADIGMS.items()):
            check = QCheckBox(paradigm.display_name)
            check.setChecked(key in selected)
            check.stateChanged.connect(self._update_estimate)
            self.paradigm_checks[key] = check
            grid.addWidget(check, index // 2, index % 2)
        judging_layout.addLayout(grid)

        run_row = QHBoxLayout()
        run_row.addWidget(QLabel("Runs per paradigm:"))
        self.runs_combo = CleanComboBox()
        for runs, text in ((1, "1 — Fast / cheapest"), (3, "3 — Recommended"), (5, "5 — More stable")):
            self.runs_combo.addItem(text, runs)
        idx = self.runs_combo.findData(defaults.get("default_runs", 3))
        self.runs_combo.setCurrentIndex(max(0, idx))
        self.runs_combo.currentIndexChanged.connect(self._update_estimate)
        run_row.addWidget(self.runs_combo)
        run_row.addStretch()
        judging_layout.addLayout(run_row)
        layout.addWidget(judging_group)

        self.estimate = QLabel()
        self.estimate.setWordWrap(True)
        self.estimate.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self.estimate)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        judge = QPushButton("Judge Round")
        judge.setObjectName("primary")
        judge.clicked.connect(self._accept_if_valid)
        buttons.addWidget(judge)
        layout.addLayout(buttons)

        self.setStyleSheet(f"""
            QDialog {{ background: {COLORS['background']}; }}
            QGroupBox {{
                background: white; border: 1px solid {COLORS['border']};
                border-radius: 10px; margin-top: 8px; padding: 14px; font-weight: 600;
            }}
            QLineEdit, QComboBox {{
                background: white; border: 1px solid {COLORS['border']};
                border-radius: 7px; padding: 9px;
            }}
            QComboBox {{ padding-right: 44px; }}
            QComboBox::drop-down {{ width: 38px; border: none; background: transparent; }}
            QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
            QPushButton {{ padding: 9px 18px; border-radius: 7px; border: 1px solid {COLORS['border']}; background: white; }}
            QPushButton#primary {{ color: white; background: {COLORS['primary']}; border: none; }}
        """)

    def _selected_paradigms(self) -> list[str]:
        return [key for key, check in self.paradigm_checks.items() if check.isChecked()]

    def _update_estimate(self):
        paradigms = self._selected_paradigms()
        runs = int(self.runs_combo.currentData() or 3)
        if not paradigms:
            self.estimate.setText("Choose at least one paradigm.")
            return
        low, high = estimate_cost_usd(
            self.preflight.chars, paradigms, runs, self.provider, self.model
        )
        self.estimate.setText(
            f"Approximate API cost: ${low:.2f}–${high:.2f} • {len(paradigms)} paradigm(s) × {runs} run(s). "
            "Actual tokenization, output length, retries, and provider pricing can change the total."
        )

    def _accept_if_valid(self):
        if not self._selected_paradigms():
            QMessageBox.warning(self, "JudgeAI", "Choose at least one paradigm.")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "format": self.format_combo.currentData() or "LD",
            "resolution": self.resolution.text().strip(),
            "aff": self.aff.text().strip(),
            "neg": self.neg.text().strip(),
            "paradigms": self._selected_paradigms(),
            "runs": int(self.runs_combo.currentData() or 3),
        }


class _SubprocessWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._process: Optional[subprocess.Popen] = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        process = self._process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _run_command(self, command: list[str]) -> tuple[int, str, str]:
        flags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags = subprocess.CREATE_NO_WINDOW
        self._process = subprocess.Popen(
            command,
            cwd=str(runtime_cwd()),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=flags,
        )
        stdout, stderr = self._process.communicate()
        return self._process.returncode or 0, stdout or "", stderr or ""


class JudgeWorker(_SubprocessWorker):
    def __init__(self, transcript_path: Path, setup: dict):
        super().__init__()
        self.transcript_path = transcript_path
        self.setup = setup

    def run(self):
        temp_dir = None
        try:
            self.progress.emit("Preparing transcript…")
            temp_dir = tempfile.mkdtemp(prefix="judgeai_gui_")
            staged_path = Path(temp_dir) / self.transcript_path.name
            shutil.copy2(self.transcript_path, staged_path)

            command = [
                *cli_prefix(),
                "new",
                str(staged_path),
                "--format",
                self.setup.get("format", "LD"),
                "--yes",
                "--runs",
                str(self.setup.get("runs", 3)),
                "--personas",
                ",".join(self.setup.get("paradigms") or PARADIGMS.keys()),
            ]
            for flag, value in (
                ("--resolution", self.setup.get("resolution")),
                ("--aff", self.setup.get("aff")),
                ("--neg", self.setup.get("neg")),
            ):
                if value:
                    command += [flag, str(value)]

            self.progress.emit("Flowing and judging the round…")
            code, stdout, stderr = self._run_command(command)
            combined = (stdout + "\n" + stderr).strip()
            match = re.search(r"Round ID:\s*([^\s]+)", combined)
            round_id = match.group(1) if match else None

            if self._cancelled:
                self.finished.emit({"success": False, "cancelled": True, "round_id": round_id})
                return

            store = LocalDiskBallotStore()
            partial = False
            analysis_failed = False
            if code != 0:
                partial = bool(round_id and store.round_path(round_id).exists())
                if not partial:
                    raise RuntimeError(combined or f"JudgeAI exited with code {code}")
                analysis_failed = (
                    "Cross-paradigm diff failed:" in combined
                    or "Could not save diff:" in combined
                )

            if round_id:
                try:
                    meta = store.load_metadata(round_id)
                    meta["source_path"] = str(self.transcript_path)
                    meta["source_name"] = self.transcript_path.name
                    meta["gui_selected_paradigms"] = list(self.setup.get("paradigms") or [])
                    store.save_metadata(round_id, meta)
                except Exception:
                    pass

            diff_text = ""
            if round_id:
                try:
                    diff_text = store.load_diff(round_id)
                except Exception:
                    diff_text = ""

            self.finished.emit(
                {
                    "success": True,
                    "partial": partial,
                    "analysis_failed": analysis_failed,
                    "round_id": round_id,
                    "diff": diff_text,
                    "log": combined,
                    "warning": combined if partial else "",
                }
            )
        except Exception as exc:
            self.finished.emit({"success": False, "error": str(exc)})
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)


class AnalysisRetryWorker(_SubprocessWorker):
    def __init__(self, round_id: str):
        super().__init__()
        self.round_id = round_id

    def run(self):
        try:
            self.progress.emit("Regenerating cross-paradigm analysis…")
            command = [
                *cli_prefix(),
                "retry-analysis",
                self.round_id,
            ]
            code, stdout, stderr = self._run_command(command)
            combined = (stdout + "\n" + stderr).strip()

            if self._cancelled:
                self.finished.emit(
                    {"success": False, "cancelled": True, "round_id": self.round_id}
                )
                return

            if code != 0:
                raise RuntimeError(
                    combined or f"JudgeAI exited with code {code}"
                )

            self.finished.emit(
                {
                    "success": True,
                    "round_id": self.round_id,
                    "log": combined,
                }
            )
        except Exception as exc:
            self.finished.emit(
                {
                    "success": False,
                    "round_id": self.round_id,
                    "error": str(exc),
                }
            )


class RetryWorker(_SubprocessWorker):
    def __init__(self, round_id: str, persona: str, runs: int):
        super().__init__()
        self.round_id = round_id
        self.persona = persona
        self.runs = runs

    def run(self):
        try:
            self.progress.emit(f"Retrying {PARADIGMS[self.persona].display_name}…")
            command = [
                *cli_prefix(),
                "retry",
                self.round_id,
                "--persona",
                self.persona,
                "--runs",
                str(self.runs),
            ]
            code, stdout, stderr = self._run_command(command)
            combined = (stdout + "\n" + stderr).strip()
            if self._cancelled:
                self.finished.emit({"success": False, "cancelled": True})
                return
            if code != 0:
                raise RuntimeError(combined or f"JudgeAI exited with code {code}")
            self.finished.emit({"success": True, "round_id": self.round_id, "log": combined})
        except Exception as exc:
            self.finished.emit({"success": False, "error": str(exc)})


class DropArea(QFrame):
    file_dropped = pyqtSignal(Path)

    def __init__(self):
        super().__init__()
        self.setObjectName("dropArea")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(180)
        self.setMaximumHeight(205)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 15, 22, 15)
        layout.setSpacing(4)
        layout.addStretch()
        icon = QLabel("📄")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFont(QFont("Arial", 18))
        icon.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(icon)
        title = QLabel("Drop a debate transcript here")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Arial", 14))
        title.setStyleSheet(f"background: transparent; border: none; color: {COLORS['text_secondary']};")
        layout.addWidget(title)
        browse = QLabel("or click to browse")
        browse.setAlignment(Qt.AlignmentFlag.AlignCenter)
        browse.setFont(QFont("Arial", 13))
        browse.setStyleSheet(f"background: transparent; border: none; color: {COLORS['text_secondary']};")
        layout.addWidget(browse)
        support = QLabel(".txt and .rtf supported")
        support.setAlignment(Qt.AlignmentFlag.AlignCenter)
        support.setFont(QFont("Arial", 10))
        support.setStyleSheet(f"background: transparent; border: none; color: {COLORS['text_secondary']};")
        layout.addWidget(support)
        layout.addStretch()
        self._normal_style()

    def _normal_style(self):
        self.setStyleSheet(f"QFrame#dropArea {{ border: 3px dashed {COLORS['border']}; border-radius: 16px; background: {COLORS['surface']}; }}")

    def _hover_style(self):
        self.setStyleSheet(f"QFrame#dropArea {{ border: 3px dashed {COLORS['primary']}; border-radius: 16px; background: #EFF6FF; }}")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._hover_style()

    def dragLeaveEvent(self, event):
        self._normal_style()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        self._normal_style()
        if urls:
            self.file_dropped.emit(Path(urls[0].toLocalFile()))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Transcript",
            str(Path.home()),
            "Transcript Files (*.txt *.rtf);;All Files (*.*)",
        )
        if path:
            self.file_dropped.emit(Path(path))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        load_into_environment()
        self.store = LocalDiskBallotStore()
        self.worker: Optional[_SubprocessWorker] = None
        self.all_rounds: list[dict] = []
        self.last_path: Optional[Path] = None
        self.last_setup: Optional[dict] = None
        self.current_provider = ""
        self.current_model = ""

        self.setWindowTitle(f"{VERSION_LABEL} — JudgeAI")
        self.setMinimumSize(1000, 720)
        self.resize(1200, 840)
        self._build_ui()
        self._apply_style()
        self.refresh_rounds()
        self.refresh_provider_status()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(30, 24, 30, 28)
        layout.setSpacing(12)

        header = QHBoxLayout()
        heading_box = QVBoxLayout()
        title = QLabel("⚖️ JudgeAI")
        title.setFont(QFont("Arial", 30, QFont.Weight.Bold))
        heading_box.addWidget(title)
        subtitle = QLabel(f"Multi-paradigm Lincoln-Douglas debate judge • {VERSION_LABEL}")
        subtitle.setStyleSheet(f"color: {COLORS['text_secondary']};")
        heading_box.addWidget(subtitle)
        header.addLayout(heading_box)
        header.addStretch()
        self.provider_status = QLabel("● Checking…")
        header.addWidget(self.provider_status)
        settings = QPushButton("⚙️ Settings")
        settings.clicked.connect(self.open_settings)
        header.addWidget(settings)
        layout.addLayout(header)

        self.drop_area = DropArea()
        self.drop_area.file_dropped.connect(self.prepare_round)
        layout.addWidget(self.drop_area)

        # The idle controls and active progress UI occupy the SAME fixed-height
        # slot. Showing progress therefore cannot push the run controls upward
        # into the transcript drop area or shift Recent Rounds downward.
        self.work_status_stack = QStackedWidget()
        self.work_status_stack.setFixedHeight(48)

        idle_status = QWidget()
        run_row = QHBoxLayout(idle_status)
        run_row.setContentsMargins(0, 2, 0, 2)
        run_label = QLabel("Default runs for next round:")
        run_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-weight: 600;"
        )
        run_row.addWidget(run_label)

        self.runs_combo = CleanComboBox()
        for runs, text in (
            (1, "1 — Fast / cheapest"),
            (3, "3 — Recommended"),
            (5, "5 — More stable"),
        ):
            self.runs_combo.addItem(text, runs)
        default_runs = get_gui_defaults()["default_runs"]
        self.runs_combo.setCurrentIndex(
            max(0, self.runs_combo.findData(default_runs))
        )
        self.runs_combo.setMinimumWidth(230)
        self.runs_combo.setFixedHeight(42)
        run_row.addWidget(self.runs_combo)

        run_help = QLabel(
            "You can change paradigms, names, resolution, and runs before each round."
        )
        run_help.setStyleSheet(f"color: {COLORS['text_secondary']};")
        run_row.addWidget(run_help)
        run_row.addStretch()

        busy_status = QWidget()
        progress_row = QHBoxLayout(busy_status)
        progress_row.setContentsMargins(0, 2, 0, 2)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMinimumHeight(40)
        progress_row.addWidget(self.progress, 1)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_current_work)
        progress_row.addWidget(self.cancel_button)

        self.work_status_stack.addWidget(idle_status)
        self.work_status_stack.addWidget(busy_status)
        self.work_status_stack.setCurrentWidget(idle_status)
        self._idle_status_page = idle_status
        self._busy_status_page = busy_status
        layout.addWidget(self.work_status_stack)

        rounds_header = QHBoxLayout()
        rounds_title = QLabel("Recent Rounds")
        rounds_title.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        rounds_header.addWidget(rounds_title)
        rounds_header.addStretch()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_rounds)
        rounds_header.addWidget(refresh)
        layout.addLayout(rounds_header)

        filter_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search date, resolution, round ID, Aff, or Neg…")
        self.search.textChanged.connect(self.filter_rounds)
        filter_row.addWidget(self.search, 1)
        self.format_filter = CleanComboBox()
        self.format_filter.addItem("All formats", "all")
        for fmt in ("LD", "PF", "Worlds", "Congress", "Parli"):
            self.format_filter.addItem(fmt, fmt)
        self.format_filter.currentIndexChanged.connect(self.filter_rounds)
        filter_row.addWidget(self.format_filter)
        self.winner_filter = CleanComboBox()
        self.winner_filter.addItem("All results", "all")
        self.winner_filter.addItem("AFF majority", "AFF")
        self.winner_filter.addItem("NEG majority", "NEG")
        self.winner_filter.addItem("Split / incomplete", "split")
        self.winner_filter.currentIndexChanged.connect(self.filter_rounds)
        filter_row.addWidget(self.winner_filter)
        layout.addLayout(filter_row)

        self.rounds_list = QListWidget()
        self.rounds_list.setMinimumHeight(260)
        self.rounds_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.rounds_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.rounds_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rounds_list.setWordWrap(True)
        layout.addWidget(self.rounds_list, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.addStretch()
        open_button = QPushButton("Open")
        open_button.clicked.connect(self.open_selected_round)
        actions.addWidget(open_button)
        transcript_button = QPushButton("Transcript")
        transcript_button.clicked.connect(self.open_selected_transcript)
        actions.addWidget(transcript_button)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self.delete_selected_round)
        actions.addWidget(delete_button)
        layout.addLayout(actions)

    def _apply_style(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background: {COLORS['background']}; }}
            QWidget {{ font-family: Arial, sans-serif; color: {COLORS['text']}; }}
            QPushButton {{
                background: white; border: 1px solid {COLORS['border']};
                border-radius: 8px; padding: 9px 14px;
            }}
            QPushButton:hover {{ border-color: {COLORS['primary']}; }}
            QLineEdit, QComboBox {{
                background: white; border: 1px solid {COLORS['border']};
                border-radius: 8px; padding: 10px;
            }}
            QComboBox {{ padding-right: 46px; }}
            QComboBox::drop-down {{ width: 38px; border: none; background: transparent; }}
            QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
            QListWidget {{
                background: white; border: 1px solid {COLORS['border']};
                border-radius: 10px; padding: 6px; outline: none;
            }}
            QListWidget::item {{
                background: {COLORS['surface']}; color: {COLORS['text']};
                padding: 10px 12px; margin: 2px; border: 1px solid transparent;
                border-bottom: 1px solid {COLORS['border']}; border-radius: 6px;
            }}
            QListWidget::item:hover {{ background: #F8FAFC; color: {COLORS['text']}; }}
            QListWidget::item:selected, QListWidget::item:selected:active, QListWidget::item:selected:!active {{
                background: {COLORS['selected']}; color: {COLORS['text']}; border: 1px solid #BFDBFE;
            }}
            QScrollBar:vertical {{ background: transparent; width: 12px; margin: 4px 2px; }}
            QScrollBar::handle:vertical {{ background: #CBD5E1; min-height: 34px; border-radius: 5px; }}
            QScrollBar::handle:vertical:hover {{ background: #94A3B8; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QProgressBar {{ background: white; border: 1px solid {COLORS['border']}; border-radius: 8px; text-align: center; }}
            QProgressBar::chunk {{ background: {COLORS['primary']}; border-radius: 7px; }}
        """)

    def refresh_provider_status(self):
        try:
            client = build_client(verbose=False)
            self.current_provider = getattr(client, "current_provider_name", type(client).__name__)
            self.current_model = getattr(client, "model_id", "")
            label = f"● {self.current_provider}" + (f" · {self.current_model}" if self.current_model else "")
            self.provider_status.setText(label)
            self.provider_status.setStyleSheet(f"padding: 8px 12px; color: {COLORS['success']}; font-weight: 600;")
        except Exception:
            providers = get_available_providers()
            self.current_provider = providers[0] if providers else ""
            self.current_model = ""
            self.provider_status.setText("● API key saved" if providers else "● Not configured")
            self.provider_status.setStyleSheet(f"padding: 8px 12px; color: {COLORS['warning']}; font-weight: 600;")

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            load_into_environment()
            defaults = get_gui_defaults()
            self.runs_combo.setCurrentIndex(max(0, self.runs_combo.findData(defaults["default_runs"])))
            self.refresh_provider_status()
            QMessageBox.information(self, "JudgeAI", "Settings saved.")

    def _validate_path_and_provider(self, path: Path) -> bool:
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "JudgeAI", "A judging task is already running.")
            return False
        if not path.exists() or not path.is_file():
            QMessageBox.critical(self, "Invalid File", f"File not found:\n{path}")
            return False
        if path.suffix.lower() not in {".txt", ".rtf"}:
            QMessageBox.warning(self, "Unsupported File", "Please choose a .txt or .rtf transcript.")
            return False
        try:
            build_client(verbose=False)
        except CredentialsError:
            QMessageBox.warning(self, "API Key Needed", "Open Settings and add an Anthropic or OpenAI API key first.")
            self.open_settings()
            return False
        except Exception as exc:
            QMessageBox.critical(self, "LLM Setup Error", f"JudgeAI could not initialize the model provider:\n\n{exc}")
            return False
        return True

    def prepare_round(self, path: Path):
        if not self._validate_path_and_provider(path):
            return
        try:
            preflight = preflight_transcript(path, "LD")
        except Exception as exc:
            QMessageBox.critical(self, "Transcript Error", f"Could not read this transcript:\n\n{exc}")
            return

        defaults = get_gui_defaults()
        defaults["default_runs"] = int(self.runs_combo.currentData() or defaults["default_runs"])
        dialog = RoundSetupDialog(preflight, defaults, self.current_provider, self.current_model, self)
        if not dialog.exec():
            return
        setup = dialog.values()
        self._launch_judging(path, setup)

    def _set_busy(self, busy: bool, message: str = ""):
        self.drop_area.setEnabled(not busy)
        self.runs_combo.setEnabled(not busy)
        self.work_status_stack.setCurrentWidget(
            self._busy_status_page if busy else self._idle_status_page
        )
        if busy:
            self.progress.setFormat(message or "Working…")

    def _launch_judging(self, path: Path, setup: dict):
        self.last_path = path
        self.last_setup = dict(setup)
        self._set_busy(True, "Starting JudgeAI…")
        self.worker = JudgeWorker(path, setup)
        self.worker.progress.connect(self.progress.setFormat)
        self.worker.finished.connect(self.judging_finished)
        self.worker.start()

    def cancel_current_work(self):
        if self.worker and self.worker.isRunning():
            self.cancel_button.setEnabled(False)
            self.progress.setFormat("Cancelling…")
            self.worker.cancel()

    def judging_finished(self, result: dict):
        self._set_busy(False)
        self.cancel_button.setEnabled(True)
        self.refresh_rounds()
        if result.get("cancelled"):
            QMessageBox.information(self, "JudgeAI", "Judging was cancelled. Any completed partial artifacts remain in Recent Rounds.")
            return
        if not result.get("success"):
            self._show_failure(result.get("error", "Unknown error"), can_retry=bool(self.last_path))
            return

        round_id = result.get("round_id") or "Unknown"
        if result.get("partial"):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            if result.get("analysis_failed"):
                box.setWindowTitle("Judging complete — analysis unavailable")
                box.setText(
                    "The selected paradigm ballots were saved successfully, but the "
                    "cross-paradigm analysis failed. Open the result and use Retry "
                    "Analysis to regenerate only the synthesis. The judges will not rerun."
                )
            else:
                box.setWindowTitle("Round completed with limits")
                box.setText(
                    "JudgeAI saved the parts of the round that completed, but at least "
                    "one later step failed. Open the result to see what is available."
                )
            if result.get("warning"):
                box.setDetailedText(result["warning"])
            box.addButton(QMessageBox.StandardButton.OK)
            box.exec()

        self._show_round_dialog(
            round_id,
            fallback_diff=result.get("diff") or "",
            just_completed=True,
            analysis_failed=bool(result.get("analysis_failed")),
        )

    def _show_failure(self, raw_error: str, can_retry: bool = False):
        title, friendly = classify_run_error(raw_error)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(friendly)
        box.setDetailedText(raw_error)
        retry_button = None
        if can_retry:
            retry_button = box.addButton("Retry Round", QMessageBox.ButtonRole.AcceptRole)
        settings_button = box.addButton("Settings", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        clicked = box.clickedButton()
        if clicked is settings_button:
            self.open_settings()
        elif retry_button is not None and clicked is retry_button and self.last_path and self.last_setup:
            self._launch_judging(self.last_path, self.last_setup)

    @staticmethod
    def _decision_winner(decision: str) -> Optional[str]:
        match = re.match(r"\s*(AFF|NEG)\b", decision or "", re.I)
        return match.group(1).upper() if match else None

    @classmethod
    def _overall_split(cls, decisions: dict) -> tuple[int, int, int]:
        aff = neg = other = 0
        for decision in (decisions or {}).values():
            winner = cls._decision_winner(decision)
            if winner == "AFF":
                aff += 1
            elif winner == "NEG":
                neg += 1
            else:
                other += 1
        return aff, neg, other

    @classmethod
    def _overall_label(cls, decisions: dict) -> str:
        aff, neg, other = cls._overall_split(decisions)
        if aff > neg:
            return f"AFF {aff} • NEG {neg}" + (f" • {other} unavailable" if other else "")
        if neg > aff:
            return f"NEG {neg} • AFF {aff}" + (f" • {other} unavailable" if other else "")
        return f"Split {aff}-{neg}" + (f" • {other} unavailable" if other else "")

    def refresh_rounds(self):
        try:
            self.all_rounds = self.store.list_rounds()
        except Exception:
            self.all_rounds = []
        self.filter_rounds()

    def filter_rounds(self, *_args):
        if not hasattr(self, "rounds_list"):
            return
        self.rounds_list.clear()
        needle = (self.search.text() if hasattr(self, "search") else "").strip().lower()
        format_filter = self.format_filter.currentData() if hasattr(self, "format_filter") else "all"
        winner_filter = self.winner_filter.currentData() if hasattr(self, "winner_filter") else "all"

        for item in self.all_rounds:
            haystack = " ".join(str(item.get(key) or "") for key in ("round_id", "date", "resolution", "aff", "neg", "format")).lower()
            if needle and needle not in haystack:
                continue
            if format_filter != "all" and (item.get("format") or "").lower() != str(format_filter).lower():
                continue
            decisions = item.get("decisions") or {}
            aff_count, neg_count, other = self._overall_split(decisions)
            if winner_filter == "AFF" and not (aff_count > neg_count):
                continue
            if winner_filter == "NEG" and not (neg_count > aff_count):
                continue
            if winner_filter == "split" and not (aff_count == neg_count or other):
                continue

            round_id = item.get("round_id") or "Unknown"
            date = item.get("date") or "Unknown date"
            resolution = item.get("resolution") or "Resolution not detected"
            aff = item.get("aff") or "AFF"
            neg = item.get("neg") or "NEG"
            cost = float(item.get("cost_usd") or 0)
            overall = self._overall_label(decisions) if decisions else "No result summary"
            text = f"{date}  •  {round_id}\n{resolution}\n{aff} vs {neg}  •  {overall}  •  ${cost:.4f}"
            widget_item = QListWidgetItem(text)
            widget_item.setData(Qt.ItemDataRole.UserRole, round_id)
            self.rounds_list.addItem(widget_item)

    def _selected_round_id(self) -> Optional[str]:
        item = self.rounds_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def open_selected_round(self):
        round_id = self._selected_round_id()
        if round_id:
            self._show_round_dialog(round_id)

    def open_selected_transcript(self):
        round_id = self._selected_round_id()
        if round_id:
            self._open_transcript(round_id)

    def delete_selected_round(self):
        round_id = self._selected_round_id()
        if not round_id:
            return
        answer = QMessageBox.question(
            self,
            "Delete Round",
            f"Delete saved ballots and analysis for {round_id}?\n\nArchived/original transcript files are not deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete_round(round_id)
            self.refresh_rounds()
        except StorageError as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))

    @staticmethod
    def _text_tab(content: str) -> QTextEdit:
        view = QTextEdit()
        view.setReadOnly(True)
        view.setPlainText(content)
        return view

    @staticmethod
    def _clean_ballot_for_display(content: str) -> str:
        return re.sub(r"^<!--.*?-->\s*", "", content, count=1, flags=re.DOTALL)

    def _ordered_personas(self, metadata: dict, round_id: str):
        decisions = metadata.get("decisions") or {}
        available = set(self.store.personas_for(round_id)) | set(decisions.keys())
        registry_order = {key: index for index, key in enumerate(PARADIGMS.keys())}
        return sorted(available, key=lambda key: (registry_order.get(key, 999), key))

    def _load_ballots(self, metadata: dict, round_id: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
        decisions = metadata.get("decisions") or {}
        ballots: dict[str, str] = {}
        tabs: list[tuple[str, str]] = []
        for persona in self._ordered_personas(metadata, round_id):
            paradigm = PARADIGMS.get(persona)
            display_name = paradigm.display_name if paradigm else persona
            decision = decisions.get(persona)
            try:
                ballot = self._clean_ballot_for_display(self.store.load_ballot(round_id, persona))
                content = (f"Decision: {decision}\n\n" if decision else "") + ballot
            except StorageError:
                content = (f"Decision: {decision}\n\n" if decision else "") + "No saved representative ballot is available for this paradigm."
            ballots[display_name] = content
            tabs.append((persona, content))
        return ballots, tabs

    def _show_round_dialog(
        self,
        round_id: str,
        fallback_diff: str = "",
        just_completed: bool = False,
        analysis_failed: bool = False,
    ):
        try:
            metadata = self.store.load_metadata(round_id)
        except Exception:
            metadata = {}

        has_diff = False
        try:
            diff = self.store.load_diff(round_id)
            has_diff = bool(diff.strip())
        except StorageError:
            diff = fallback_diff.strip()
            has_diff = bool(diff)

        if not has_diff:
            diff = (
                "Cross-paradigm analysis is unavailable for this round.\n\n"
                "The saved paradigm ballots are still valid. Click Retry Analysis below "
                "to regenerate only the synthesis without rerunning the judges."
            )

        ballots_by_name, persona_tabs = self._load_ballots(metadata, round_id)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"JudgeAI Result — {round_id}")

        # Keep the full result window inside the usable desktop area.
        # This matters on Windows at 125%/150% display scaling, where a fixed
        # 780px logical height can extend below the taskbar and hide buttons.
        screen = dialog.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            target_width = min(1050, max(760, available.width() - 80))
            target_height = min(780, max(560, available.height() - 80))
            dialog.resize(target_width, target_height)
        else:
            dialog.resize(1000, 700)

        dialog.setMinimumSize(760, 560)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        resolution = metadata.get("resolution") or "Resolution not detected"
        aff = metadata.get("aff") or "Aff"
        neg = metadata.get("neg") or "Neg"
        if just_completed and not has_diff and len(persona_tabs) >= 2:
            status_line = "⚠ Judging complete — analysis unavailable\n"
        elif just_completed:
            status_line = "✓ Round complete\n"
        else:
            status_line = ""
        heading = QLabel(status_line + f"{aff} vs {neg}\n{resolution}")
        heading.setWordWrap(True)
        heading.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(heading)

        overall = QLabel(f"Paradigm split: {self._overall_label(metadata.get('decisions') or {})}")
        overall.setStyleSheet(f"padding: 8px 10px; background: #F3F4F6; border-radius: 8px; font-weight: 600; color: {COLORS['text']};")
        layout.addWidget(overall)

        card_grid = QGridLayout()
        decisions = metadata.get("decisions") or {}
        for index, key in enumerate(PARADIGMS):
            decision = decisions.get(key, "Not run")
            card = QLabel(f"{PARADIGMS[key].display_name}\n{decision}")
            card.setWordWrap(True)
            card.setStyleSheet(f"background: white; border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 9px;")
            card_grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(card_grid)

        tabs = QTabWidget()
        tabs.setMinimumHeight(220)
        tab_personas: list[Optional[str]] = [None]
        tabs.addTab(self._text_tab(diff), "Cross-Paradigm")
        for persona, content in persona_tabs:
            tabs.addTab(
                self._text_tab(content),
                PARADIGMS.get(persona).display_name if persona in PARADIGMS else persona,
            )
            tab_personas.append(persona)
        layout.addWidget(tabs, 1)

        # Keep actions in their own fixed-height row so they remain visible
        # even on shorter/high-DPI displays.
        button_bar = QWidget()
        button_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        buttons = QHBoxLayout(button_bar)
        buttons.setContentsMargins(0, 4, 0, 0)
        buttons.setSpacing(8)
        copy_button = QPushButton("Copy Current Tab")
        buttons.addWidget(copy_button)
        export_button = QPushButton("Export Report")
        buttons.addWidget(export_button)
        folder_button = QPushButton("Open Folder")
        buttons.addWidget(folder_button)
        transcript_button = QPushButton("Open Transcript")
        buttons.addWidget(transcript_button)
        retry_button = QPushButton("Retry This Paradigm")
        retry_button.setEnabled(False)
        buttons.addWidget(retry_button)

        retry_analysis_button = QPushButton("Retry Analysis")
        retry_analysis_button.setVisible(not has_diff and len(persona_tabs) >= 2)
        buttons.addWidget(retry_analysis_button)
        buttons.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        buttons.addWidget(close)
        layout.addWidget(button_bar)

        def current_view() -> Optional[QTextEdit]:
            widget = tabs.currentWidget()
            return widget if isinstance(widget, QTextEdit) else None

        def copy_current():
            view = current_view()
            if view:
                QApplication.clipboard().setText(view.toPlainText())

        def update_retry(index: int):
            retry_button.setEnabled(index > 0 and index < len(tab_personas) and bool(tab_personas[index]))

        def retry_current():
            index = tabs.currentIndex()
            persona = tab_personas[index] if index < len(tab_personas) else None
            if not persona:
                return
            runs = int(self.runs_combo.currentData() or 3)
            answer = QMessageBox.question(
                dialog,
                "Retry paradigm",
                f"Retry {PARADIGMS[persona].display_name} with {runs} run(s)?\n\nThis makes paid API calls and replaces that paradigm's saved representative ballot.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                dialog.accept()
                self.start_retry(round_id, persona, runs)

        def retry_analysis_only():
            answer = QMessageBox.question(
                dialog,
                "Retry cross-paradigm analysis",
                "Regenerate the cross-paradigm analysis from the saved ballots?\n\n"
                "This makes one paid synthesis API call. It does not rerun any judge.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                dialog.accept()
                self.start_analysis_retry(round_id)

        copy_button.clicked.connect(copy_current)
        tabs.currentChanged.connect(update_retry)
        retry_button.clicked.connect(retry_current)
        retry_analysis_button.clicked.connect(retry_analysis_only)
        folder_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.round_path(round_id)))))
        transcript_button.clicked.connect(lambda: self._open_transcript(round_id))
        export_button.clicked.connect(lambda: self._export_round(round_id, metadata, diff, ballots_by_name, dialog))
        dialog.exec()

    def _export_round(self, round_id: str, metadata: dict, diff: str, ballots: dict[str, str], parent):
        report = combined_report(round_id, metadata, diff, ballots)
        default_name = f"JudgeAI_{round_id}.md"
        path, selected_filter = QFileDialog.getSaveFileName(
            parent,
            "Export JudgeAI Report",
            str(Path.home() / "Desktop" / default_name),
            "Markdown (*.md);;Text (*.txt);;PDF (*.pdf)",
        )
        if not path:
            return
        out = Path(path)
        if "PDF" in selected_filter and out.suffix.lower() != ".pdf":
            out = out.with_suffix(".pdf")
        elif "Text" in selected_filter and out.suffix.lower() != ".txt":
            out = out.with_suffix(".txt")
        elif "Markdown" in selected_filter and out.suffix.lower() != ".md":
            out = out.with_suffix(".md")
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.suffix.lower() == ".pdf":
                writer = QPdfWriter(str(out))
                writer.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
                document = QTextDocument()
                document.setPlainText(report)
                document.print(writer)
            else:
                out.write_text(report, encoding="utf-8")
            QMessageBox.information(parent, "Export complete", f"Saved:\n{out}")
        except Exception as exc:
            QMessageBox.critical(parent, "Export failed", str(exc))

    def _open_transcript(self, round_id: str):
        path = None
        try:
            metadata = self.store.load_metadata(round_id)
            source = metadata.get("source_path")
            if source and Path(source).exists():
                path = Path(source)
        except Exception:
            pass
        if path is None:
            candidate = self.store.round_path(round_id) / "structured_transcript.md"
            if candidate.exists():
                path = candidate
        if path is None:
            QMessageBox.warning(self, "Transcript", "No original or saved structured transcript exists for this round.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def start_analysis_retry(self, round_id: str):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(
                self,
                "JudgeAI",
                "Another judging task is already running.",
            )
            return

        self._set_busy(True, "Regenerating cross-paradigm analysis…")
        self.worker = AnalysisRetryWorker(round_id)
        self.worker.progress.connect(self.progress.setFormat)
        self.worker.finished.connect(self.analysis_retry_finished)
        self.worker.start()

    def analysis_retry_finished(self, result: dict):
        self._set_busy(False)
        self.cancel_button.setEnabled(True)
        self.refresh_rounds()

        if result.get("cancelled"):
            QMessageBox.information(self, "JudgeAI", "Analysis retry cancelled.")
            return

        if not result.get("success"):
            self._show_failure(
                result.get("error", "Cross-paradigm analysis failed."),
                can_retry=False,
            )
            round_id = result.get("round_id")
            if round_id:
                self._show_round_dialog(round_id, analysis_failed=True)
            return

        round_id = result.get("round_id")
        QMessageBox.information(
            self,
            "JudgeAI",
            "Cross-paradigm analysis regenerated from the saved ballots. "
            "No judge was rerun.",
        )
        if round_id:
            self._show_round_dialog(round_id)

    def start_retry(self, round_id: str, persona: str, runs: int):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "JudgeAI", "Another judging task is already running.")
            return
        self._set_busy(True, f"Retrying {PARADIGMS[persona].display_name}…")
        self.worker = RetryWorker(round_id, persona, runs)
        self.worker.progress.connect(self.progress.setFormat)
        self.worker.finished.connect(self.retry_finished)
        self.worker.start()

    def retry_finished(self, result: dict):
        self._set_busy(False)
        self.cancel_button.setEnabled(True)
        self.refresh_rounds()
        if result.get("cancelled"):
            QMessageBox.information(self, "JudgeAI", "Retry cancelled.")
            return
        if not result.get("success"):
            self._show_failure(result.get("error", "Unknown error"), can_retry=False)
            return
        round_id = result.get("round_id")
        QMessageBox.information(self, "JudgeAI", "Paradigm retry completed and the cross-paradigm analysis was refreshed.")
        if round_id:
            self._show_round_dialog(round_id)

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("JudgeAI")
    # Explicit app font avoids the Qt -1 point-size warning seen on some Windows setups.
    app.setFont(QFont("Arial", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
