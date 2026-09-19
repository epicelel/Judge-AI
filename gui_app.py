
"""
JudgeAI Desktop Application

Replacement GUI that stays compatible with the current JudgeAI CLI/backend.
It deliberately runs the canonical `judge.py new ...` pipeline instead of
duplicating old backend calls inside the GUI.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont
    from PyQt6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QFileDialog,
        QFormLayout,
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
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    print("ERROR: PyQt6 not installed. Run: pip install PyQt6")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.bedrock_client import build_client, CredentialsError
from src.config import (
    get_available_providers,
    load_config,
    load_into_environment,
    set_api_key,
    set_provider_preference,
)
from src.storage import LocalDiskBallotStore, StorageError


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
}


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JudgeAI Settings")
        self.setMinimumWidth(520)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)

        title = QLabel("⚙️ Settings")
        title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        layout.addWidget(title)

        provider_group = QGroupBox("LLM Provider")
        provider_form = QFormLayout(provider_group)
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(
            ["Auto-detect", "Anthropic API", "OpenAI API"]
        )
        provider_form.addRow("Provider:", self.provider_combo)
        layout.addWidget(provider_group)

        keys_group = QGroupBox("API Keys")
        keys_form = QFormLayout(keys_group)

        self.anthropic_key = QLineEdit()
        self.anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_key.setPlaceholderText("sk-ant-...")
        keys_form.addRow("Anthropic:", self.anthropic_key)

        self.openai_key = QLineEdit()
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key.setPlaceholderText("sk-...")
        keys_form.addRow("OpenAI:", self.openai_key)

        layout.addWidget(keys_group)

        note = QLabel(
            "Keys are stored in ~/.judgeai/config.json and loaded when JudgeAI starts."
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
        save.clicked.connect(self._save)
        save.setObjectName("primary")
        buttons.addWidget(save)

        layout.addLayout(buttons)

        self.setStyleSheet(f"""
            QDialog {{
                background: {COLORS['background']};
            }}
            QGroupBox {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                margin-top: 8px;
                padding: 14px;
                font-weight: 600;
            }}
            QLineEdit, QComboBox {{
                background: white;
                border: 1px solid {COLORS['border']};
                border-radius: 7px;
                padding: 9px;
            }}
            QPushButton {{
                padding: 9px 18px;
                border-radius: 7px;
                border: 1px solid {COLORS['border']};
                background: white;
            }}
            QPushButton#primary {{
                color: white;
                background: {COLORS['primary']};
                border: none;
            }}
        """)

    def _load(self):
        config = load_config()

        self.anthropic_key.setText(
            os.environ.get("ANTHROPIC_API_KEY")
            or config.get("anthropic_api_key", "")
        )
        self.openai_key.setText(
            os.environ.get("OPENAI_API_KEY")
            or config.get("openai_api_key", "")
        )

        pref = (
            os.environ.get("LLM_PROVIDER")
            or config.get("provider_preference", "auto")
            or "auto"
        ).lower()

        if pref == "anthropic":
            self.provider_combo.setCurrentText("Anthropic API")
        elif pref == "openai":
            self.provider_combo.setCurrentText("OpenAI API")
        else:
            self.provider_combo.setCurrentText("Auto-detect")

    def _save(self):
        try:
            if self.anthropic_key.text().strip():
                set_api_key("anthropic", self.anthropic_key.text().strip())

            if self.openai_key.text().strip():
                set_api_key("openai", self.openai_key.text().strip())

            selected = self.provider_combo.currentText()

            if selected == "Anthropic API":
                set_provider_preference("anthropic")
            elif selected == "OpenAI API":
                set_provider_preference("openai")
            else:
                set_provider_preference("auto")

            self.accept()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Settings Error",
                f"Could not save settings:\n\n{exc}",
            )


class JudgeWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)

    def __init__(self, transcript_path: Path, runs: int = 3):
        super().__init__()
        self.transcript_path = transcript_path
        self.runs = runs

    def run(self):
        temp_dir = None
        try:
            self.progress.emit("Preparing transcript...")

            # Use the current CLI pipeline as the single source of truth.
            # We stage a copy so JudgeAI's successful-run archiving does not
            # move/delete the user's original transcript.
            temp_dir = tempfile.mkdtemp(prefix="judgeai_gui_")
            staged_path = Path(temp_dir) / self.transcript_path.name
            shutil.copy2(self.transcript_path, staged_path)

            self.progress.emit("Judging round...")

            command = [
                sys.executable,
                str(PROJECT_ROOT / "judge.py"),
                "new",
                str(staged_path),
                "--format",
                "LD",
                "--yes",
                "--runs",
                str(self.runs),
            ]

            completed = subprocess.run(
                command,
                cwd=str(PROJECT_ROOT),
                env=os.environ.copy(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            combined = stdout + "\n" + stderr

            if completed.returncode != 0:
                raise RuntimeError(
                    combined.strip()
                    or f"JudgeAI exited with code {completed.returncode}"
                )

            match = re.search(r"Round ID:\s*([^\s]+)", combined)
            round_id = match.group(1) if match else None

            diff_text = ""
            if round_id:
                try:
                    diff_text = LocalDiskBallotStore().load_diff(round_id)
                except Exception:
                    diff_text = stdout.strip()

            self.finished.emit(
                {
                    "success": True,
                    "round_id": round_id,
                    "diff": diff_text or stdout.strip(),
                    "log": combined.strip(),
                }
            )

        except Exception as exc:
            self.finished.emit(
                {
                    "success": False,
                    "error": str(exc),
                }
            )
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)


class DropArea(QLabel):
    file_dropped = pyqtSignal(Path)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(260)
        self.setText(
            "📄\n\nDrop a debate transcript here\n\nor click to browse\n\n"
            ".txt and .rtf supported"
        )
        self._normal_style()

    def _normal_style(self):
        self.setStyleSheet(f"""
            QLabel {{
                border: 3px dashed {COLORS['border']};
                border-radius: 16px;
                background: {COLORS['surface']};
                padding: 50px;
                font-size: 16pt;
                color: {COLORS['text_secondary']};
            }}
        """)

    def _hover_style(self):
        self.setStyleSheet(f"""
            QLabel {{
                border: 3px dashed {COLORS['primary']};
                border-radius: 16px;
                background: #EFF6FF;
                padding: 50px;
                font-size: 16pt;
                color: {COLORS['primary']};
            }}
        """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._hover_style()

    def dragLeaveEvent(self, event):
        self._normal_style()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        self._normal_style()

        if not urls:
            return

        path = Path(urls[0].toLocalFile())
        self.file_dropped.emit(path)

    def mousePressEvent(self, event):
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
        self.worker = None
        self.all_rounds = []

        self.setWindowTitle("JudgeAI")
        self.setMinimumSize(980, 760)

        self._build_ui()
        self._apply_style()
        self.refresh_rounds()
        self.refresh_provider_status()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(36, 32, 36, 32)
        layout.setSpacing(18)

        header = QHBoxLayout()

        heading_box = QVBoxLayout()
        title = QLabel("⚖️ JudgeAI")
        title.setFont(QFont("Arial", 30, QFont.Weight.Bold))
        heading_box.addWidget(title)

        subtitle = QLabel("Multi-paradigm Lincoln-Douglas debate judge")
        subtitle.setStyleSheet(f"color: {COLORS['text_secondary']};")
        heading_box.addWidget(subtitle)

        header.addLayout(heading_box)
        header.addStretch()

        self.provider_status = QLabel("● Checking...")
        self.provider_status.setStyleSheet(
            f"padding: 8px 12px; color: {COLORS['text_secondary']};"
        )
        header.addWidget(self.provider_status)

        settings = QPushButton("⚙️ Settings")
        settings.clicked.connect(self.open_settings)
        header.addWidget(settings)

        layout.addLayout(header)

        self.drop_area = DropArea()
        self.drop_area.file_dropped.connect(self.start_judging)
        layout.addWidget(self.drop_area)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setMinimumHeight(40)
        layout.addWidget(self.progress)

        rounds_header = QHBoxLayout()

        rounds_title = QLabel("Recent Rounds")
        rounds_title.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        rounds_header.addWidget(rounds_title)

        rounds_header.addStretch()

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_rounds)
        rounds_header.addWidget(refresh)

        layout.addLayout(rounds_header)

        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Search by round ID, date, resolution, AFF, or NEG..."
        )
        self.search.textChanged.connect(self.filter_rounds)
        layout.addWidget(self.search)

        self.rounds_list = QListWidget()
        self.rounds_list.itemDoubleClicked.connect(self.open_round)
        layout.addWidget(self.rounds_list)

        hint = QLabel(
            "Double-click a completed round to view its cross-paradigm result."
        )
        hint.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(hint)

    def _apply_style(self):
        self.setStyleSheet(f"""
            QMainWindow {{
                background: {COLORS['background']};
            }}
            QWidget {{
                font-family: Arial, sans-serif;
                color: {COLORS['text']};
            }}
            QPushButton {{
                background: white;
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 9px 14px;
            }}
            QPushButton:hover {{
                border-color: {COLORS['primary']};
            }}
            QLineEdit {{
                background: white;
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 10px;
            }}
            QListWidget {{
                background: white;
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
                padding: 6px;
            }}
            QListWidget::item {{
                padding: 12px;
                margin: 3px;
                border-bottom: 1px solid {COLORS['border']};
            }}
            QProgressBar {{
                background: white;
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background: {COLORS['primary']};
                border-radius: 7px;
            }}
        """)

    def refresh_provider_status(self):
        try:
            client = build_client(verbose=False)
            self.provider_status.setText(f"● {type(client).__name__}")
            self.provider_status.setStyleSheet(
                f"padding: 8px 12px; color: {COLORS['success']}; font-weight: 600;"
            )
        except Exception:
            providers = get_available_providers()
            if providers:
                self.provider_status.setText("● API key saved")
                self.provider_status.setStyleSheet(
                    f"padding: 8px 12px; color: {COLORS['warning']}; font-weight: 600;"
                )
            else:
                self.provider_status.setText("● Not configured")
                self.provider_status.setStyleSheet(
                    f"padding: 8px 12px; color: {COLORS['warning']}; font-weight: 600;"
                )

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            load_into_environment()
            self.refresh_provider_status()
            QMessageBox.information(self, "JudgeAI", "Settings saved.")

    def start_judging(self, path: Path):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(
                self,
                "JudgeAI",
                "A round is already being judged.",
            )
            return

        if not path.exists() or not path.is_file():
            QMessageBox.critical(
                self,
                "Invalid File",
                f"File not found:\n{path}",
            )
            return

        if path.suffix.lower() not in {".txt", ".rtf"}:
            QMessageBox.warning(
                self,
                "Unsupported File",
                "Please choose a .txt or .rtf transcript.",
            )
            return

        try:
            build_client(verbose=False)
        except CredentialsError:
            QMessageBox.warning(
                self,
                "API Key Needed",
                "Open Settings and add an Anthropic or OpenAI API key first.",
            )
            self.open_settings()
            return
        except Exception as exc:
            QMessageBox.critical(
                self,
                "LLM Setup Error",
                f"JudgeAI could not initialize the model provider:\n\n{exc}",
            )
            return

        answer = QMessageBox.question(
            self,
            "Judge Round",
            "Judge this transcript now?\n\n"
            "This will make paid API calls. The default is 3 runs per paradigm.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.drop_area.setVisible(False)
        self.progress.setVisible(True)
        self.progress.setFormat("Starting JudgeAI...")

        self.worker = JudgeWorker(path, runs=3)
        self.worker.progress.connect(self.progress.setFormat)
        self.worker.finished.connect(self.judging_finished)
        self.worker.start()

    def judging_finished(self, result: dict):
        self.progress.setVisible(False)
        self.drop_area.setVisible(True)

        if not result.get("success"):
            QMessageBox.critical(
                self,
                "Judging Failed",
                result.get("error", "Unknown error"),
            )
            return

        self.refresh_rounds()

        round_id = result.get("round_id") or "Unknown"
        diff = result.get("diff") or "Round completed, but no diff was found."

        dialog = QDialog(self)
        dialog.setWindowTitle(f"JudgeAI Result — {round_id}")
        dialog.resize(850, 650)

        layout = QVBoxLayout(dialog)

        title = QLabel(f"✓ Round complete\n{round_id}")
        title.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        layout.addWidget(title)

        output = QTextEdit()
        output.setReadOnly(True)
        output.setPlainText(diff)
        layout.addWidget(output)

        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)

        dialog.exec()

    def refresh_rounds(self):
        try:
            self.all_rounds = self.store.list_rounds()
        except Exception:
            self.all_rounds = []

        self.filter_rounds(self.search.text() if hasattr(self, "search") else "")

    def filter_rounds(self, query: str):
        if not hasattr(self, "rounds_list"):
            return

        self.rounds_list.clear()
        needle = (query or "").strip().lower()

        for item in self.all_rounds:
            haystack = " ".join(
                str(item.get(key) or "")
                for key in ("round_id", "date", "resolution", "aff", "neg", "format")
            ).lower()

            if needle and needle not in haystack:
                continue

            round_id = item.get("round_id") or "Unknown"
            date = item.get("date") or "Unknown date"
            resolution = item.get("resolution") or "Resolution not detected"
            aff = item.get("aff") or "AFF"
            neg = item.get("neg") or "NEG"
            cost = float(item.get("cost_usd") or 0)

            text = (
                f"{date}  •  {round_id}\n"
                f"{resolution}\n"
                f"{aff} vs {neg}  •  ${cost:.4f}"
            )

            widget_item = QListWidgetItem(text)
            widget_item.setData(Qt.ItemDataRole.UserRole, round_id)
            self.rounds_list.addItem(widget_item)

    def open_round(self, item: QListWidgetItem):
        round_id = item.data(Qt.ItemDataRole.UserRole)
        if not round_id:
            return

        try:
            content = self.store.load_diff(round_id)
        except StorageError:
            try:
                meta = self.store.load_metadata(round_id)
                content = (
                    "No cross-paradigm diff is saved for this round.\n\n"
                    f"Metadata:\n{meta}"
                )
            except Exception as exc:
                content = f"Could not load round:\n\n{exc}"

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Round — {round_id}")
        dialog.resize(850, 650)

        layout = QVBoxLayout(dialog)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(content)
        layout.addWidget(text)

        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)

        dialog.exec()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("JudgeAI")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
