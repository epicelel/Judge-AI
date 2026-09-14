#!/usr/bin/env python3
"""
JudgeAI Desktop Application

Native PyQt6 GUI for multi-paradigm debate judging.
Beautiful, modern interface - no terminal, no browser required.
"""

import sys
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QListWidget, QListWidgetItem, QTextEdit,
        QFileDialog, QMessageBox, QDialog, QLineEdit, QComboBox,
        QProgressBar, QTabWidget, QSplitter, QGroupBox, QFormLayout,
        QFrame,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QMimeData, QSize, QPropertyAnimation, QEasingCurve
    from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont, QIcon, QPalette, QColor
except ImportError:
    print("ERROR: PyQt6 not installed. Run: pip install PyQt6")
    sys.exit(1)

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.bedrock_client import build_client, CredentialsError, ModelInvocationError
from src.fallback_client import FallbackClient
from src.judging import judge_round, generate_diff, DEFAULT_PARADIGMS
from src.storage import LocalDiskBallotStore
from src.ingest import load_round_input
from src.config import load_config, set_api_key, set_provider_preference, load_into_environment, get_available_providers

# Modern color scheme
COLORS = {
    'primary': '#3B82F6',      # Bright blue
    'primary_hover': '#2563EB', # Darker blue
    'success': '#10B981',      # Green
    'warning': '#F59E0B',      # Orange
    'error': '#EF4444',        # Red
    'background': '#F9FAFB',   # Light gray
    'surface': '#FFFFFF',      # White
    'border': '#E5E7EB',       # Light border
    'text': '#111827',         # Dark text
    'text_secondary': '#6B7280', # Gray text
}


class SettingsDialog(QDialog):
    """Beautiful settings dialog for API keys and provider configuration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(550)
        self.setup_ui()
        self.load_settings()
        self.apply_styles()

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # Title
        title = QLabel("⚙️ Settings")
        title.setFont(QFont("SF Pro Display", 20, QFont.Weight.Bold))
        layout.addWidget(title)

        # Provider selection
        provider_group = QGroupBox("LLM Provider")
        provider_group.setFont(QFont("SF Pro Text", 12, QFont.Weight.Medium))
        provider_layout = QFormLayout()
        provider_layout.setSpacing(15)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["Auto-detect", "Anthropic API", "OpenAI API"])
        self.provider_combo.setMinimumHeight(40)
        provider_layout.addRow("Provider:", self.provider_combo)

        provider_group.setLayout(provider_layout)
        layout.addWidget(provider_group)

        # API Keys
        keys_group = QGroupBox("API Keys")
        keys_group.setFont(QFont("SF Pro Text", 12, QFont.Weight.Medium))
        keys_layout = QFormLayout()
        keys_layout.setSpacing(15)

        self.anthropic_key = QLineEdit()
        self.anthropic_key.setPlaceholderText("sk-ant-...")
        self.anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_key.setMinimumHeight(40)
        keys_layout.addRow("Anthropic:", self.anthropic_key)

        self.openai_key = QLineEdit()
        self.openai_key.setPlaceholderText("sk-...")
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key.setMinimumHeight(40)
        keys_layout.addRow("OpenAI:", self.openai_key)

        keys_group.setLayout(keys_layout)
        layout.addWidget(keys_group)

        # Help text
        help_text = QLabel(
            "📝 Get API keys:\n"
            "• Anthropic: console.anthropic.com (Recommended - $3/$15 per 1M tokens)\n"
            "• OpenAI: platform.openai.com/api-keys ($10/$30 per 1M tokens)\n\n"
            "💡 Pro Tip: Set BOTH keys for automatic fallback!\n"
            "   When one hits rate limits, automatically switches to the other.\n"
            "   Zero downtime, seamless operation.\n\n"
            "🔒 Keys are saved securely in ~/.judgeai/config.json"
        )
        help_text.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 10pt; padding: 10px;")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(44)
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Save")
        save_btn.setMinimumHeight(44)
        save_btn.clicked.connect(self.save_settings)
        save_btn.setObjectName("primary")

        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def apply_styles(self):
        """Apply modern styling to the dialog."""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS['background']};
            }}
            QGroupBox {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
                padding: 20px;
                margin-top: 10px;
                font-weight: 600;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
            }}
            QLineEdit, QComboBox {{
                background-color: {COLORS['surface']};
                border: 2px solid {COLORS['border']};
                border-radius: 8px;
                padding: 10px 15px;
                font-size: 13pt;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border-color: {COLORS['primary']};
            }}
            QPushButton {{
                background-color: {COLORS['surface']};
                border: 2px solid {COLORS['border']};
                border-radius: 8px;
                padding: 12px 24px;
                font-size: 13pt;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {COLORS['background']};
            }}
            QPushButton#primary {{
                background-color: {COLORS['primary']};
                border: none;
                color: white;
            }}
            QPushButton#primary:hover {{
                background-color: {COLORS['primary_hover']};
            }}
        """)

    def load_settings(self):
        """Load settings from saved config and environment variables."""
        config = load_config()

        # Load API keys (prefer environment, fallback to config)
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or config.get("anthropic_api_key", "")
        openai_key = os.environ.get("OPENAI_API_KEY") or config.get("openai_api_key", "")

        self.anthropic_key.setText(anthropic_key)
        self.openai_key.setText(openai_key)

        # Load provider preference
        provider = os.environ.get("LLM_PROVIDER") or config.get("provider_preference", "")
        provider = provider.lower()

        if provider == "anthropic":
            self.provider_combo.setCurrentText("Anthropic API")
        elif provider == "openai":
            self.provider_combo.setCurrentText("OpenAI API")
        else:
            self.provider_combo.setCurrentText("Auto-detect")

    def save_settings(self):
        """Save settings persistently to config file and environment."""
        try:
            # Save API keys
            if self.anthropic_key.text():
                set_api_key("anthropic", self.anthropic_key.text())

            if self.openai_key.text():
                set_api_key("openai", self.openai_key.text())

            # Save provider preference
            provider_text = self.provider_combo.currentText()
            if provider_text == "Anthropic API":
                set_provider_preference("anthropic")
            elif provider_text == "OpenAI API":
                set_provider_preference("openai")
            else:
                set_provider_preference("auto")

            self.accept()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Saving Settings",
                f"Failed to save settings:\n\n{str(e)}"
            )


class JudgingWorker(QThread):
    """Background worker for judging (keeps UI responsive)."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(object)

    def __init__(self, transcript_path: Path):
        super().__init__()
        self.transcript_path = transcript_path

    def run(self):
        """Run judging in background thread."""
        try:
            self.progress.emit("Parsing transcript...")

            round_input = load_round_input(
                target=str(self.transcript_path),
                debate_format="LD"
            )
            structured_transcript = round_input.structured_transcript

            self.progress.emit("Building LLM client...")
            client = build_client(verbose=False)

            self.progress.emit(f"Judging with {type(client).__name__}...")

            result = judge_round(
                client=client,
                structured_transcript=structured_transcript,
                paradigms=DEFAULT_PARADIGMS,
                runs=3
            )

            self.progress.emit("Generating cross-paradigm diff...")

            diff_response = generate_diff(
                client=client,
                round_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
                date=datetime.now().strftime("%Y-%m-%d"),
                resolution=structured_transcript.resolution or "Unknown",
                aff=structured_transcript.aff or "Affirmative",
                neg=structured_transcript.neg or "Negative",
                result=result
            )

            self.progress.emit("Saving results...")

            store = LocalDiskBallotStore()
            round_id = store.save_round(
                result=result,
                diff_text=diff_response.text,
                structured_transcript=structured_transcript,
                resolution=structured_transcript.resolution,
                aff=structured_transcript.aff or "Affirmative",
                neg=structured_transcript.neg or "Negative"
            )

            self.finished.emit({
                "success": True,
                "round_id": round_id,
                "diff": diff_response.text,
                "result": result
            })

        except Exception as e:
            self.finished.emit({
                "success": False,
                "error": str(e)
            })


class DropArea(QLabel):
    """Beautiful drag-and-drop area for transcript files."""

    file_dropped = pyqtSignal(Path)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("📄\n\nDrop transcript here\n\nor click to browse")
        self.setMinimumHeight(280)
        self.apply_styles()

    def apply_styles(self):
        """Apply modern styling."""
        self.setStyleSheet(f"""
            QLabel {{
                border: 3px dashed {COLORS['border']};
                border-radius: 16px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLORS['surface']}, stop:1 #F3F4F6);
                padding: 60px;
                font-size: 16pt;
                font-weight: 500;
                color: {COLORS['text_secondary']};
            }}
        """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"""
                QLabel {{
                    border: 3px dashed {COLORS['primary']};
                    border-radius: 16px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #EFF6FF, stop:1 #DBEAFE);
                    padding: 60px;
                    font-size: 16pt;
                    font-weight: 500;
                    color: {COLORS['primary']};
                }}
            """)

    def dragLeaveEvent(self, event):
        self.apply_styles()

    def dropEvent(self, event: QDropEvent):
        files = [url.toLocalFile() for url in event.mimeData().urls()]
        if files:
            self.file_dropped.emit(Path(files[0]))
        self.apply_styles()

    def mousePressEvent(self, event):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Transcript File",
            str(Path.home()),
            "Text Files (*.txt *.md);;All Files (*.*)"
        )
        if file_path:
            self.file_dropped.emit(Path(file_path))

    def enterEvent(self, event):
        """Hover effect."""
        self.setStyleSheet(f"""
            QLabel {{
                border: 3px dashed {COLORS['primary']};
                border-radius: 16px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLORS['surface']}, stop:1 #F3F4F6);
                padding: 60px;
                font-size: 16pt;
                font-weight: 500;
                color: {COLORS['primary']};
            }}
        """)

    def leaveEvent(self, event):
        """Remove hover effect."""
        self.apply_styles()


class MainWindow(QMainWindow):
    """Beautiful main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JudgeAI")
        self.setMinimumSize(1000, 800)
        self.store = LocalDiskBallotStore()
        self.current_worker = None

        # Load saved API keys from config
        load_into_environment()

        self.setup_ui()
        self.apply_styles()
        self.load_recent_rounds()
        self.check_llm_setup()

    def setup_ui(self):
        """Build the beautiful UI."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(20)
        layout.setContentsMargins(40, 40, 40, 40)

        # Header
        header = QHBoxLayout()

        title_section = QVBoxLayout()
        title_section.setSpacing(5)

        title = QLabel("⚖️  JudgeAI")
        title.setFont(QFont("SF Pro Display", 32, QFont.Weight.Bold))
        title_section.addWidget(title)

        subtitle = QLabel("Multi-paradigm Lincoln-Douglas debate judge")
        subtitle.setFont(QFont("SF Pro Text", 13))
        subtitle.setStyleSheet(f"color: {COLORS['text_secondary']};")
        title_section.addWidget(subtitle)

        header.addLayout(title_section)
        header.addStretch()

        # Status badge
        self.status_label = QLabel("● Not configured")
        self.status_label.setFont(QFont("SF Pro Text", 12))
        self.status_label.setStyleSheet(f"""
            background-color: {COLORS['surface']};
            border: 2px solid {COLORS['border']};
            border-radius: 8px;
            padding: 8px 16px;
            color: {COLORS['text_secondary']};
        """)
        header.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addLayout(header)
        layout.addSpacing(10)

        # Drop area
        self.drop_area = DropArea()
        self.drop_area.file_dropped.connect(self.handle_file)
        layout.addWidget(self.drop_area)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(48)
        self.progress_bar.setFont(QFont("SF Pro Text", 12))
        layout.addWidget(self.progress_bar)

        # Recent rounds section
        rounds_header = QHBoxLayout()

        rounds_label = QLabel("Recent Rounds")
        rounds_label.setFont(QFont("SF Pro Display", 18, QFont.Weight.Bold))
        rounds_header.addWidget(rounds_label)

        rounds_header.addStretch()

        refresh_btn = QPushButton("🔄  Refresh")
        refresh_btn.setMinimumHeight(36)
        refresh_btn.clicked.connect(self.load_recent_rounds)
        rounds_header.addWidget(refresh_btn)

        layout.addLayout(rounds_header)

        # Search bar
        search_container = QHBoxLayout()
        search_container.setSpacing(10)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Search by date, resolution, debater names, or round ID...")
        self.search_box.setMinimumHeight(44)
        self.search_box.setFont(QFont("SF Pro Text", 13))
        self.search_box.textChanged.connect(self.filter_rounds)
        search_container.addWidget(self.search_box)

        clear_search_btn = QPushButton("✕")
        clear_search_btn.setFixedSize(44, 44)
        clear_search_btn.setToolTip("Clear search")
        clear_search_btn.clicked.connect(self.clear_search)
        search_container.addWidget(clear_search_btn)

        layout.addLayout(search_container)

        # Results count label
        self.results_label = QLabel("")
        self.results_label.setFont(QFont("SF Pro Text", 11))
        self.results_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 5px 10px;")
        layout.addWidget(self.results_label)

        # Rounds list
        self.rounds_list = QListWidget()
        self.rounds_list.itemDoubleClicked.connect(self.view_round)
        self.rounds_list.setFont(QFont("SF Pro Text", 13))
        self.rounds_list.setSpacing(8)
        layout.addWidget(self.rounds_list)

        # Store all rounds for filtering
        self.all_rounds = []

        # Bottom toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)

        settings_btn = QPushButton("⚙️  Settings")
        settings_btn.setMinimumHeight(44)
        settings_btn.clicked.connect(self.show_settings)
        settings_btn.setObjectName("primary")
        toolbar.addWidget(settings_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

    def apply_styles(self):
        """Apply modern styling to the main window."""
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {COLORS['background']};
            }}
            QWidget {{
                font-family: "SF Pro Text", -apple-system, BlinkMacSystemFont, sans-serif;
            }}
            QPushButton {{
                background-color: {COLORS['surface']};
                border: 2px solid {COLORS['border']};
                border-radius: 10px;
                padding: 10px 20px;
                font-size: 13pt;
                font-weight: 500;
                color: {COLORS['text']};
            }}
            QPushButton:hover {{
                background-color: #F3F4F6;
                border-color: {COLORS['primary']};
            }}
            QPushButton#primary {{
                background-color: {COLORS['primary']};
                border: none;
                color: white;
            }}
            QPushButton#primary:hover {{
                background-color: {COLORS['primary_hover']};
            }}
            QLineEdit {{
                background-color: {COLORS['surface']};
                border: 2px solid {COLORS['border']};
                border-radius: 10px;
                padding: 12px 16px;
                font-size: 13pt;
            }}
            QLineEdit:focus {{
                border-color: {COLORS['primary']};
            }}
            QListWidget {{
                background-color: {COLORS['surface']};
                border: 2px solid {COLORS['border']};
                border-radius: 12px;
                padding: 10px;
                font-size: 13pt;
            }}
            QListWidget::item {{
                background-color: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 16px;
                margin: 4px;
            }}
            QListWidget::item:hover {{
                background-color: #F9FAFB;
                border-color: {COLORS['primary']};
            }}
            QListWidget::item:selected {{
                background-color: #EFF6FF;
                border-color: {COLORS['primary']};
                color: {COLORS['text']};
            }}
            QProgressBar {{
                border: 2px solid {COLORS['border']};
                border-radius: 10px;
                background-color: {COLORS['surface']};
                text-align: center;
                font-weight: 500;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {COLORS['primary']}, stop:1 #60A5FA);
                border-radius: 8px;
            }}
        """)

    def check_llm_setup(self):
        """Check if LLM provider is configured."""
        try:
            client = build_client(verbose=False)
            client_name = type(client).__name__

            # Check if using fallback client (multiple providers)
            if isinstance(client, FallbackClient):
                providers_text = " → ".join(client.provider_names)
                self.status_label.setText(f"● Auto-Fallback: {client.current_provider_name}")
                self.status_label.setToolTip(
                    f"Auto-switching enabled\n"
                    f"Fallback chain: {providers_text}\n"
                    f"Switches automatically on rate limits"
                )
                self.status_label.setStyleSheet(f"""
                    background-color: #EFF6FF;
                    border: 2px solid {COLORS['primary']};
                    border-radius: 8px;
                    padding: 8px 16px;
                    color: {COLORS['primary']};
                    font-weight: 600;
                """)
            elif "Anthropic" in client_name:
                self.status_label.setText("● Anthropic API")
                self.status_label.setToolTip("Using Anthropic API")
                self.status_label.setStyleSheet(f"""
                    background-color: #ECFDF5;
                    border: 2px solid {COLORS['success']};
                    border-radius: 8px;
                    padding: 8px 16px;
                    color: {COLORS['success']};
                    font-weight: 600;
                """)
            elif "OpenAI" in client_name:
                self.status_label.setText("● OpenAI API")
                self.status_label.setToolTip("Using OpenAI API")
                self.status_label.setStyleSheet(f"""
                    background-color: #ECFDF5;
                    border: 2px solid {COLORS['success']};
                    border-radius: 8px;
                    padding: 8px 16px;
                    color: {COLORS['success']};
                    font-weight: 600;
                """)
        except Exception:
            self.status_label.setText("● Not configured")
            self.status_label.setToolTip("No LLM provider configured")
            self.status_label.setStyleSheet(f"""
                background-color: #FEF3C7;
                border: 2px solid {COLORS['warning']};
                border-radius: 8px;
                padding: 8px 16px;
                color: {COLORS['warning']};
                font-weight: 600;
            """)

    def show_settings(self):
        """Open settings dialog."""
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.check_llm_setup()
            msg = QMessageBox(self)
            msg.setWindowTitle("Success")
            msg.setText("✓ Settings saved successfully")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.exec()

    def handle_file(self, file_path: Path):
        """Handle dropped/selected file."""
        if not file_path.exists():
            QMessageBox.critical(self, "Error", f"File not found: {file_path}")
            return

        try:
            build_client(verbose=False)
        except CredentialsError:
            QMessageBox.warning(
                self,
                "LLM Not Configured",
                "Please configure your LLM provider in Settings first.\n\n"
                "You need either:\n"
                "• Anthropic API key (recommended)\n"
                "• OpenAI API key"
            )
            self.show_settings()
            return

        self.drop_area.setVisible(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("Judging...")

        self.current_worker = JudgingWorker(file_path)
        self.current_worker.progress.connect(self.update_progress)
        self.current_worker.finished.connect(self.judging_finished)
        self.current_worker.start()

    def update_progress(self, message: str):
        """Update progress bar text."""
        self.progress_bar.setFormat(message)

    def judging_finished(self, result: dict):
        """Handle judging completion."""
        self.drop_area.setVisible(True)
        self.progress_bar.setVisible(False)

        if result["success"]:
            self.load_recent_rounds()

            msg = QMessageBox(self)
            msg.setWindowTitle("Success")
            msg.setText("✓ Round judged successfully!")
            msg.setInformativeText(f"Round ID: {result['round_id'][:12]}...")
            msg.setDetailedText(result["diff"])
            msg.setIcon(QMessageBox.Icon.Information)
            msg.exec()
        else:
            error_text = result['error']

            # Check if it's a "all providers failed" error
            if "all llm providers failed" in error_text.lower():
                # Show more helpful error message
                providers = get_available_providers()
                if len(providers) >= 2:
                    error_msg = (
                        f"❌ All LLM providers hit rate limits or errors:\n\n{error_text}\n\n"
                        f"💡 What to do:\n"
                        f"• Wait 1-5 minutes for rate limits to reset\n"
                        f"• Try again - limits usually reset quickly\n"
                        f"• Or upgrade to higher tier API plan for more capacity"
                    )
                else:
                    error_msg = (
                        f"❌ LLM provider failed:\n\n{error_text}\n\n"
                        f"💡 Tip: Set BOTH Anthropic and OpenAI API keys in Settings\n"
                        f"   for automatic fallback when one hits rate limits!"
                    )
                QMessageBox.critical(self, "Rate Limit / Error", error_msg)
            else:
                QMessageBox.critical(self, "Error", f"Judging failed:\n\n{error_text}")

    def load_recent_rounds(self):
        """Load recent rounds into list and store for filtering."""
        self.all_rounds = self.store.list_rounds()
        self.filter_rounds("")  # Show all initially

    def clear_search(self):
        """Clear the search box."""
        self.search_box.clear()

    def filter_rounds(self, search_text: str):
        """Filter rounds based on search text."""
        self.rounds_list.clear()
        search_text = search_text.lower().strip()

        if not self.all_rounds:
            item = QListWidgetItem("No rounds yet • Drop a transcript to begin")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor(COLORS['text_secondary']))
            self.rounds_list.addItem(item)
            self.results_label.setText("")
            return

        # Filter rounds
        filtered_rounds = []
        for round_data in self.all_rounds:
            if self._matches_search(round_data, search_text):
                filtered_rounds.append(round_data)

        # Display filtered results
        if not filtered_rounds:
            item = QListWidgetItem("No matches found")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor(COLORS['text_secondary']))
            self.rounds_list.addItem(item)
            self.results_label.setText(f"0 of {len(self.all_rounds)} rounds")
            return

        # Show up to 50 results
        for round_data in filtered_rounds[:50]:
            date = round_data.get("date", "Unknown")
            resolution = round_data.get("resolution") or "Unknown"
            aff = round_data.get("aff", "")
            neg = round_data.get("neg", "")

            # Build display text
            resolution_short = resolution[:50] + "..." if len(resolution) > 50 else resolution
            display_text = f"{date}  •  {resolution_short}"

            # Add debater names if available
            if aff or neg:
                names = []
                if aff:
                    names.append(f"Aff: {aff}")
                if neg:
                    names.append(f"Neg: {neg}")
                display_text += f"\n    {' | '.join(names)}"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, round_data["round_id"])
            self.rounds_list.addItem(item)

        # Update results count
        if search_text:
            self.results_label.setText(
                f"Found {len(filtered_rounds)} of {len(self.all_rounds)} rounds"
            )
        else:
            self.results_label.setText(
                f"Showing {min(len(filtered_rounds), 50)} of {len(self.all_rounds)} rounds"
            )

    def _matches_search(self, round_data: dict, search_text: str) -> bool:
        """Check if round matches search criteria."""
        if not search_text:
            return True

        # Searchable fields
        searchable = [
            round_data.get("date") or "",
            round_data.get("resolution") or "",
            round_data.get("aff") or "",
            round_data.get("neg") or "",
            round_data.get("round_id") or "",
        ]

        # Convert all to lowercase (handle None values)
        searchable = [str(field).lower() if field else "" for field in searchable]

        # Check if search text appears in any field
        # Support wildcard with * (e.g., "nuclear*weapons")
        if "*" in search_text:
            # Simple wildcard matching
            parts = search_text.split("*")
            for field in searchable:
                matches = True
                pos = 0
                for part in parts:
                    if part:  # Skip empty parts
                        idx = field.find(part, pos)
                        if idx == -1:
                            matches = False
                            break
                        pos = idx + len(part)
                if matches:
                    return True
        else:
            # Simple contains search
            for field in searchable:
                if search_text in field:
                    return True

        return False

    def view_round(self, item: QListWidgetItem):
        """View a past round."""
        round_id = item.data(Qt.ItemDataRole.UserRole)
        if not round_id:
            return

        try:
            round_path = self.store.round_path(round_id)
            diff_file = round_path / "diff.md"

            if not diff_file.exists():
                QMessageBox.warning(self, "Not Found", "Round diff not found.")
                return

            diff_text = diff_file.read_text(encoding="utf-8")

            dialog = QDialog(self)
            dialog.setWindowTitle(f"Round {round_id[:12]}...")
            dialog.setMinimumSize(900, 700)

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(30, 30, 30, 30)

            text_view = QTextEdit()
            text_view.setReadOnly(True)
            text_view.setText(diff_text)
            text_view.setFont(QFont("SF Mono", 12))
            text_view.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {COLORS['surface']};
                    border: 2px solid {COLORS['border']};
                    border-radius: 12px;
                    padding: 20px;
                }}
            """)
            layout.addWidget(text_view)

            close_btn = QPushButton("Close")
            close_btn.setMinimumHeight(44)
            close_btn.setObjectName("primary")
            close_btn.clicked.connect(dialog.close)
            layout.addWidget(close_btn)

            dialog.exec()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load round: {e}")


def main():
    """Launch the beautiful GUI application."""
    app = QApplication(sys.argv)
    app.setApplicationName("JudgeAI")

    # Set app-wide font (use system default on non-Mac)
    font = QFont()
    font.setPointSize(11)
    if sys.platform == "darwin":  # macOS
        font.setFamily("SF Pro Text")
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
