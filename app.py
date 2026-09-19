#!/usr/bin/env python3
"""JudgeAI Streamlit UI using the canonical CLI pipeline."""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.bedrock_client import build_client
from src.config import (
    clear_api_key,
    get_available_providers,
    load_into_environment,
    set_api_key,
    set_provider_preference,
)
from src.judging import PARADIGMS
from src.storage import LocalDiskBallotStore, StorageError

load_into_environment()
store = LocalDiskBallotStore()

st.set_page_config(
    page_title="JudgeAI",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def provider_label() -> str:
    try:
        client = build_client(verbose=False)
        provider = getattr(client, "current_provider_name", type(client).__name__)
        model = getattr(client, "model_id", "")
        return f"{provider} · {model}" if model else provider
    except Exception:
        configured = get_available_providers()
        return ", ".join(configured) if configured else "Not configured"


def run_round(uploaded_file, resolution: str, personas: list[str], runs: int):
    """Stage the upload and run exactly the same pipeline as `judge.py new`."""
    suffix = Path(uploaded_file.name).suffix.lower() or ".txt"
    with tempfile.TemporaryDirectory(prefix="judgeai_streamlit_") as tmp:
        path = Path(tmp) / f"round{suffix}"
        path.write_bytes(uploaded_file.getvalue())

        command = [
            sys.executable,
            str(PROJECT_ROOT / "judge.py"),
            "new",
            str(path),
            "--format",
            "LD",
            "--yes",
            "--runs",
            str(runs),
            "--personas",
            ",".join(personas),
        ]
        if resolution.strip():
            command.extend(["--resolution", resolution.strip()])

        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    combined = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
    match = re.search(r"Round ID:\s*([^\s]+)", combined)
    return completed.returncode, match.group(1) if match else None, completed.stdout or "", completed.stderr or ""


def show_round(round_id: str) -> None:
    matches = store.resolve_round_id(round_id)
    if not matches:
        st.error(f"Round '{round_id}' not found")
        return
    if len(matches) > 1:
        st.error(f"Round ID '{round_id}' matches multiple rounds: {matches}")
        return

    resolved = matches[0]
    try:
        metadata = store.load_metadata(resolved)
    except Exception:
        metadata_path = store.round_path(resolved) / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}

    st.subheader(metadata.get("resolution") or "Unknown resolution")
    st.caption(
        f"Round `{resolved}` · {metadata.get('date', 'Unknown date')} · "
        f"{metadata.get('aff') or 'Aff'} vs {metadata.get('neg') or 'Neg'}"
    )
    if metadata.get("total_cost_usd") is not None:
        st.caption(f"Estimated cost: ${float(metadata['total_cost_usd']):.4f}")

    try:
        diff = store.load_diff(resolved)
    except StorageError:
        diff = None

    if diff:
        st.markdown("### Cross-Paradigm Diff")
        st.markdown(diff)
    else:
        st.markdown("### Ballots")
        found = False
        for key, paradigm in PARADIGMS.items():
            try:
                ballot = store.load_ballot(resolved, key)
            except StorageError:
                continue
            found = True
            with st.expander(paradigm.display_name, expanded=True):
                st.markdown(ballot)
        if not found:
            st.warning("No saved ballots were found for this round.")


st.title("⚖️ JudgeAI")
st.caption("Multi-paradigm Lincoln-Douglas debate judge")
st.sidebar.caption(f"Provider: {provider_label()}")

with st.sidebar.expander("API Settings"):
    provider_choice = st.selectbox(
        "Provider",
        ["Auto-detect", "OpenAI API", "Anthropic API"],
        index=0,
    )
    new_openai = st.text_input("OpenAI key", type="password", placeholder="Leave blank to keep current key")
    new_anthropic = st.text_input("Anthropic key", type="password", placeholder="Leave blank to keep current key")
    col_save, col_clear = st.columns(2)
    if col_save.button("Save settings", use_container_width=True):
        if new_openai.strip():
            set_api_key("openai", new_openai.strip())
        if new_anthropic.strip():
            set_api_key("anthropic", new_anthropic.strip())
        pref = {
            "Auto-detect": "auto",
            "OpenAI API": "openai",
            "Anthropic API": "anthropic",
        }[provider_choice]
        set_provider_preference(pref)
        load_into_environment()
        st.success("Saved")
        st.rerun()
    if col_clear.button("Clear keys", use_container_width=True):
        clear_api_key("openai")
        clear_api_key("anthropic")
        set_provider_preference("auto")
        st.success("Keys cleared")
        st.rerun()

rounds = store.list_rounds()
st.sidebar.header("Past Rounds")
if rounds:
    for row in rounds[:15]:
        round_id = row["round_id"]
        label = f"{row.get('date') or ''} · {row.get('aff') or 'Aff'} v {row.get('neg') or 'Neg'}"
        if st.sidebar.button(label, key=f"history-{round_id}", use_container_width=True):
            st.session_state.selected_round = round_id
else:
    st.sidebar.caption("No rounds yet")

new_tab, history_tab = st.tabs(["⚖️ New Round", "📄 View Round"])

with new_tab:
    st.header("Judge a New Round")
    uploaded = st.file_uploader("Upload transcript", type=["txt", "rtf"])
    resolution = st.text_input("Resolution override (optional)")

    selected = st.multiselect(
        "Judge paradigms",
        options=list(PARADIGMS.keys()),
        default=list(PARADIGMS.keys()),
        format_func=lambda key: PARADIGMS[key].display_name,
    )
    runs = st.number_input("Runs per paradigm", min_value=1, max_value=9, value=3, step=1)

    if uploaded and selected and st.button("⚖️ Judge Round", type="primary", use_container_width=True):
        with st.spinner("Running JudgeAI's canonical detection → flow → judging → diff pipeline..."):
            code, round_id, stdout, stderr = run_round(uploaded, resolution, selected, int(runs))

        if code != 0:
            st.error("Judging failed")
            st.code((stderr + "\n" + stdout).strip())
        else:
            st.success(f"Judging complete{f' · {round_id}' if round_id else ''}")
            if round_id:
                st.session_state.selected_round = round_id
                show_round(round_id)
            elif stdout.strip():
                st.markdown(stdout)

with history_tab:
    st.header("View Past Round")
    if st.session_state.get("selected_round"):
        show_round(st.session_state.selected_round)
    else:
        st.info("Choose a round from the sidebar.")
