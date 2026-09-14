# JudgeAI Desktop App Guide

## Quick Start

### Mac

**Double-click:** `JudgeAI.command`

The app will:
1. Activate the Python environment
2. Launch the GUI window
3. Show drag-and-drop interface

### Windows

**Double-click:** `JudgeAI.bat`

The app will:
1. Activate the Python environment
2. Launch the GUI window
3. Show drag-and-drop interface

### Linux

```bash
source .venv/bin/activate
python gui_app.py
```

---

## First-Time Setup

When you launch the app for the first time:

1. Click **⚙ Settings**
2. Choose your LLM provider
3. Enter API key:
   - **Anthropic API**: Get key at https://console.anthropic.com/
   - **OpenAI API**: Get key at https://platform.openai.com/api-keys
4. Click **Save**

---

## How to Use

### Judge a New Round

**Method 1: Drag and Drop**
1. Drag a transcript file (`.txt` or `.md`)
2. Drop onto the "📄 Drop Transcript Here" area
3. Wait for judging to complete
4. View results dialog

**Method 2: Browse for File**
1. Click on the "📄 Drop Transcript Here" area
2. Select a transcript file
3. Wait for judging to complete
4. View results dialog

### View Past Rounds

1. See "Recent Rounds" list at bottom
2. Double-click any round
3. View full diff and ballots

### Judging Progress

While judging, you'll see:
- Parsing transcript...
- Building LLM client...
- Judging with [Provider]...
- Generating cross-paradigm diff...
- Saving results...

Typical time: 2-4 minutes per round (N=3 runs across 4 paradigms)

---

## Features

### ✓ Drag-and-Drop Interface
- Drop transcript files directly
- No typing file paths
- Visual feedback

### ✓ Settings Management
- Configure LLM provider
- Store API keys securely
- Auto-detect provider

### ✓ Recent Rounds Browser
- See last 20 rounds
- Double-click to view
- Date + resolution preview

### ✓ Background Processing
- UI stays responsive during judging
- Progress updates shown
- Can cancel if needed

### ✓ Clean Results Display
- Cross-paradigm diff
- Individual ballots
- Monospace font for readability

---

## Status Indicators

**Bottom left shows LLM status:**

- `✓ LLM: Anthropic API` - Green, ready to judge
- `✓ LLM: OpenAI API` - Green, ready to judge
- `⚠ LLM: Not configured` - Orange, needs setup

---

## Troubleshooting

### "LLM Not Configured" warning

**Solution:** Click ⚙ Settings and add an API key

### "PyQt6 not installed" error

**Solution:**
```bash
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install PyQt6
```

### App won't launch on Mac

**Solution:** Right-click `JudgeAI.command` → Open

(First time only - macOS security)

### File not found error

**Solution:** Make sure transcript is a text file (`.txt` or `.md`)

---

## Keyboard Shortcuts

- **⌘Q** / **Alt+F4** - Quit app
- **⌘,** / **Ctrl+,** - Open settings (if implemented)
- **F5** - Refresh recent rounds list

---

## Comparison: GUI vs CLI vs Web UI

| Feature | Desktop App | CLI | Web UI |
|---------|-------------|-----|--------|
| **Ease of use** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| **Drag-and-drop** | ✓ | ✗ | ✓ |
| **No terminal** | ✓ | ✗ | ✗ |
| **No browser** | ✓ | ✓ | ✗ |
| **Native feel** | ✓ | ✓ | ✗ |
| **Offline** | ✓ | ✓ | ✓ |
| **Double-click launch** | ✓ | ✗ | ✗ |

**Recommendation:** Use the Desktop App for daily use, CLI for scripting/automation.

---

## What Gets Judged

When you drop a transcript, JudgeAI:

1. **Extracts structure** - 7 LD speeches
2. **Generates flow** - Argument tracking
3. **Judges 4 paradigms** - Lay, Educated Lay, Traditional LD, Technical Circuit
4. **Runs N=3 per paradigm** - Statistical robustness
5. **Generates diff** - Cross-paradigm comparison + strategic recommendations
6. **Saves to Desktop** - `~/Desktop/JudgeAI/Ballots/<Round_ID>/`

**Cost:** ~$0.75-0.80 per round (Anthropic), ~$2-3 per round (OpenAI)

---

## Files Created

After judging a round:

```
~/Desktop/JudgeAI/Ballots/<Round_ID>/
├── metadata.json        # Date, resolution, debaters
├── diff.md             # Cross-paradigm diff + strategic recommendations
├── judge_lay.md        # Lay Parent ballot
├── judge_educated_lay.md  # Educated Lay ballot
├── judge_traditional.md   # Traditional LD ballot
├── judge_circuit.md       # Technical Circuit ballot
└── flow.md             # Extracted argument flow
```

---

## Version Info

- **App Version:** v0.6 (Desktop App)
- **Features:** Multi-provider LLM, Strategic recommendations, Eval gates
- **Platforms:** macOS, Windows, Linux
- **Python Required:** 3.12+
- **Framework:** PyQt6

---

## Need Help?

- **Settings issues:** Click ⚙ Settings, verify API key
- **Judging errors:** Check LLM status in bottom left
- **File issues:** Make sure transcript is `.txt` or `.md`
- **General questions:** See `README.md`

---

**Enjoy judging!** 🎉
