#!/usr/bin/env python3
"""
JudgeAI v0.2 — Streamlit Web UI

Usage: streamlit run app.py
"""

import sys
from pathlib import Path
import streamlit as st
import tempfile
import subprocess

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.judging import PARADIGMS
from src.storage import LocalDiskBallotStore, StorageError

# Page config
st.set_page_config(
    page_title="JudgeAI",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize store
store = LocalDiskBallotStore()


def format_diff_for_display(diff_text: str) -> str:
    """Format diff sections with better spacing for readability."""
    lines = diff_text.split('\n')
    formatted_lines = []

    in_paradigm_section = False
    in_strategy_section = False

    for i, line in enumerate(lines):
        # Check section headers
        if "—— PARADIGM DECISIONS ——" in line:
            in_paradigm_section = True
            formatted_lines.append(line)
            continue
        elif "—— PRIMARY FLIP POINT ——" in line:
            in_paradigm_section = False
            formatted_lines.append(line)
            continue
        elif "FOR AFF:" in line or "FOR NEG:" in line:
            in_strategy_section = True
            formatted_lines.append("\n" + line)  # Add blank line before section
            continue

        # Format paradigm decisions: add newline before each paradigm
        if in_paradigm_section and line.strip() and ":" in line:
            # Lines like "Lay Parent: clear NEG (3/3) — ..."
            if any(p in line for p in ["Lay Parent:", "Educated Lay:", "Traditional LD:", "Technical Circuit:"]):
                formatted_lines.append("\n" + line)
                continue

        # Format strategic recommendations: add newline before each paradigm
        if in_strategy_section and line.strip() and "(" in line and ")" in line:
            # Lines like "Lay Parent (won 3/3): ..."
            if any(p in line for p in ["Lay Parent", "Educated Lay", "Traditional LD", "Technical Circuit"]):
                formatted_lines.append("\n" + line)
                continue

        formatted_lines.append(line)

    return '\n'.join(formatted_lines)

# Title
st.title("⚖️ JudgeAI v0.2")
st.caption("Multi-paradigm Lincoln-Douglas debate judge")

# Sidebar: History
st.sidebar.header("Past Rounds")

# Load history
rounds = store.list_rounds()
if rounds:
    st.sidebar.caption(f"{len(rounds)} round(s) judged")
    for round_data in rounds[:10]:  # Show most recent 10
        round_id = round_data["round_id"]
        short_id = round_data.get("short_id", round_id[:6])
        date = round_data.get("date", "")
        resolution = round_data.get("resolution", "Unknown")
        resolution_short = resolution[:30] + "…" if len(resolution) > 30 else resolution
        aff = round_data.get("aff", "?")
        neg = round_data.get("neg", "?")

        # Format: date, debaters, resolution (left-aligned)
        button_label = f"{date}\n{aff} v {neg}\n{resolution_short}"
        if st.sidebar.button(button_label, key=round_id, use_container_width=True):
            st.session_state.selected_round = round_id
else:
    st.sidebar.caption("No rounds yet")
    st.sidebar.caption("Judge a round to see history")

# Main area
tab1, tab2 = st.tabs(["⚖️ New Round", "📄 View Round"])

with tab1:
    st.header("Judge a New Round")

    # File upload
    uploaded_file = st.file_uploader(
        "📁 Upload debate transcript (.txt)",
        type=["txt"],
        help="Upload a single transcript file. Structure will be auto-detected."
    )

    if uploaded_file:
        # Show file info
        file_size = len(uploaded_file.getvalue())
        st.caption(f"Uploaded: {uploaded_file.name} ({file_size:,} bytes)")

        # Read transcript
        transcript_text = uploaded_file.getvalue().decode('utf-8')
        word_count = len(transcript_text.split())
        st.caption(f"Word count: {word_count:,}")

        # Auto-detect resolution on first upload
        if "last_uploaded_file" not in st.session_state or st.session_state.last_uploaded_file != uploaded_file.name:
            st.session_state.last_uploaded_file = uploaded_file.name
            st.session_state.detected_resolution = None
            st.session_state.detected_aff = None
            st.session_state.detected_neg = None

            with st.spinner("🔍 Auto-detecting resolution and structure..."):
                try:
                    from src.bedrock_client import build_client
                    from src.detection import detect_structure

                    # Build client for detection
                    client = build_client()

                    # Detect structure and resolution
                    result, speeches = detect_structure(client, transcript_text, debate_format="LD")

                    # Store detected values
                    if result.resolution_text:
                        st.session_state.detected_resolution = result.resolution_text
                        st.success(f"✅ Detected resolution: {result.resolution_text}")
                    else:
                        st.info("ℹ️ Could not auto-detect resolution. Please enter manually.")

                    # Try to extract debater names from transcript header
                    # Look for patterns like "Affirmative: Name" or "Aff: Name"
                    import re
                    aff_match = re.search(r'Affirmative.*?:\s*([A-Z][a-z]+)', transcript_text[:1000], re.I)
                    neg_match = re.search(r'Negative.*?:\s*([A-Z][a-z]+)', transcript_text[:1000], re.I)

                    if aff_match:
                        st.session_state.detected_aff = aff_match.group(1)
                    if neg_match:
                        st.session_state.detected_neg = neg_match.group(1)

                except Exception as e:
                    st.warning(f"⚠️ Auto-detection failed: {e}")
                    st.caption("You can still enter metadata manually and judge the round.")

        # Metadata inputs
        st.subheader("Round Details")

        col1, col2 = st.columns(2)
        with col1:
            resolution = st.text_input(
                "Resolution",
                value=st.session_state.get("detected_resolution", ""),
                placeholder="e.g., The possession of nuclear weapons is immoral",
                help="Auto-detected from transcript. You can edit before judging."
            )
            aff_name = st.text_input(
                "Affirmative debater",
                value=st.session_state.get("detected_aff", "Aff")
            )

        with col2:
            debate_format = st.selectbox("Format", ["LD"], help="Only LD supported in v0.1")
            neg_name = st.text_input(
                "Negative debater",
                value=st.session_state.get("detected_neg", "Neg")
            )

        # Paradigm selection
        st.subheader("Judge Settings")

        col1, col2 = st.columns(2)
        with col1:
            selected_paradigms = st.multiselect(
                "Judge paradigms",
                options=["lay", "educated_lay", "traditional", "circuit"],
                default=["lay", "educated_lay", "traditional", "circuit"],
                format_func=lambda x: PARADIGMS[x].display_name,
                help="Select which judge paradigms to simulate"
            )

        with col2:
            runs = st.number_input(
                "Runs per paradigm",
                min_value=1,
                max_value=9,
                value=3,
                help="Each paradigm judges N times; verdict comes from the split"
            )

        # Judge button
        if selected_paradigms and st.button("⚖️ Judge Round", type="primary", use_container_width=True):
            with st.spinner("Judging in progress... This takes ~3 minutes for 4 paradigms"):
                try:
                    # Import required modules
                    from src.bedrock_client import build_client
                    from src import judging, storage, transcript, structure
                    from datetime import datetime

                    # Build client
                    client = build_client()

                    # Simple structure detection: assume single-file transcript
                    # For v0.2, skip complex detection and use transcript as-is
                    # The flow pass will handle speech parsing

                    # Format structured transcript
                    structured = f"""ROUND
Format: {debate_format}
Resolution: "{resolution or '(not provided)'}"
Aff: {aff_name} | Neg: {neg_name}

=== TRANSCRIPT ===

{transcript_text}
"""

                    # Generate round ID
                    round_id = storage.generate_round_id(
                        {
                            "resolution": resolution or "unknown",
                            "aff": aff_name,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                        },
                        existing_ids=[r["round_id"] for r in store.list_rounds()],
                    )

                    # Judge the round
                    result = judging.judge_round(
                        client=client,
                        structured_transcript=structured,
                        paradigms=selected_paradigms,
                        runs=runs
                    )

                    # Generate diff
                    diff_response = judging.generate_diff(
                        client=client,
                        round_id=round_id,
                        date=datetime.now().strftime("%Y-%m-%d"),
                        resolution=resolution or None,
                        aff=aff_name,
                        neg=neg_name,
                        result=result
                    )
                    diff_text = diff_response.text

                    # Save results
                    round_path = store.round_path(round_id)
                    round_path.mkdir(parents=True, exist_ok=True)

                    # Save structured transcript
                    (round_path / "structured_transcript.md").write_text(structured, encoding="utf-8")

                    # Save diff
                    (round_path / "diff.md").write_text(diff_text, encoding="utf-8")

                    # Save ballots
                    for verdict in result.verdicts:
                        if verdict.representative:
                            ballot_file = round_path / PARADIGMS[verdict.paradigm].ballot_filename
                            ballot_file.write_text(verdict.representative.text, encoding="utf-8")

                    # Save metadata
                    import json
                    metadata = {
                        "round_id": round_id,
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "format": debate_format,
                        "resolution": resolution or None,
                        "aff": aff_name,
                        "neg": neg_name,
                        "paradigms": selected_paradigms,
                        "runs_per_paradigm": runs,
                        "decisions": {
                            v.paradigm: f"{v.winner} ({v.vote_share}) {v.label}"
                            for v in result.verdicts
                        },
                        "total_input_tokens": result.input_tokens,
                        "total_output_tokens": result.output_tokens,
                        "total_cost_usd": result.cost_usd,
                        "token_usage": result.token_usage(),  # Method, not property
                    }
                    (round_path / "metadata.json").write_text(
                        json.dumps(metadata, indent=2), encoding="utf-8"
                    )

                    # Success!
                    st.success(f"✅ Judging complete! Round ID: `{round_id}`")

                    # Display results
                    st.subheader("Cross-Paradigm Diff")

                    # Extract strategic recommendations if present
                    if "—— STRATEGIC RECOMMENDATIONS ——" in diff_text:
                        parts = diff_text.split("—— STRATEGIC RECOMMENDATIONS ——")
                        main_diff = parts[0].strip()
                        strategy_section = "—— STRATEGIC RECOMMENDATIONS ——\n" + parts[1].strip()

                        # Format and show main diff
                        formatted_main = format_diff_for_display(main_diff)
                        st.markdown(formatted_main)

                        # Highlight strategic recommendations
                        st.markdown("---")
                        st.markdown("### 🎯 Strategic Recommendations")
                        st.info("**How to win each judge type** — specific, actionable advice for both sides based on vote patterns")
                        formatted_strategy = format_diff_for_display(strategy_section)
                        st.markdown(formatted_strategy)
                    else:
                        # Fallback for rounds judged before v0.3
                        formatted_diff = format_diff_for_display(diff_text)
                        st.markdown(formatted_diff)

                    st.subheader("Individual Ballots")
                    for verdict in result.verdicts:
                        if verdict.representative:
                            with st.expander(f"**{PARADIGMS[verdict.paradigm].display_name}:** {verdict.winner} ({verdict.vote_share}) {verdict.label}"):
                                st.markdown(verdict.representative.text)

                    # Cost summary
                    cost_text = judging.cost_line(
                        result.input_tokens,
                        result.output_tokens,
                        result.cost_usd
                    )
                    st.caption(f"💰 {cost_text}")

                    # Set selected round for viewing
                    st.session_state.selected_round = round_id
                    st.info("👈 Round saved! View it anytime from the sidebar.")

                except Exception as e:
                    st.error(f"❌ Judging failed: {e}")
                    import traceback
                    with st.expander("Error details"):
                        st.code(traceback.format_exc())

    else:
        st.info("👆 Upload a transcript file to begin")

        # Show example
        with st.expander("💡 What should the transcript look like?"):
            st.markdown("""
The transcript should contain the full debate text, including:
- Affirmative Constructive (AC)
- Cross-examinations (CX)
- Negative Constructive (NC)
- Rebuttals (1AR, 2NR, 2AR)

JudgeAI will auto-detect speech boundaries using Claude's language understanding.

**Example formats accepted:**
- Plain text with speech labels (e.g., "--- Affirmative Constructive ---")
- Transcript from Otter.ai or similar transcription tools
- Copy-pasted debate speeches

**Tip:** The structure doesn't need to be perfect — the judge will figure it out!
            """)

with tab2:
    st.header("View Past Round")

    if "selected_round" in st.session_state:
        round_id = st.session_state.selected_round

        # Load round
        try:
            # Resolve round ID (returns list of matches)
            matches = store.resolve_round_id(round_id)
            if not matches:
                st.error(f"Round '{round_id}' not found")
            elif len(matches) > 1:
                st.error(f"Round ID '{round_id}' matches multiple rounds: {matches}")
            else:
                resolved_id = matches[0]

                # Load metadata
                metadata_file = store.round_path(resolved_id) / "metadata.json"
                import json
                metadata = json.loads(metadata_file.read_text())

                # Show metadata
                st.subheader(f"{metadata.get('resolution', 'Unknown resolution')}")

                # Extract debater names (handle both 'aff'/'neg' and 'Aff'/'Neg' formats)
                aff = metadata.get('aff') or metadata.get('Aff') or 'Aff'
                neg = metadata.get('neg') or metadata.get('Neg') or 'Neg'

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.caption(f"**Round:** `{resolved_id[:12]}…`")
                with col2:
                    st.caption(f"**Date:** {metadata.get('date', 'Unknown')}")
                with col3:
                    st.caption(f"**Debaters:** {aff} (AFF) vs {neg} (NEG)")

                # Cost info
                if "total_cost_usd" in metadata:
                    st.caption(f"💰 Cost: ${metadata['total_cost_usd']:.2f}")

                # Show diff if available
                try:
                    diff_text = store.load_diff(resolved_id)
                    st.subheader("Cross-Paradigm Diff")

                    # Extract strategic recommendations if present
                    if "—— STRATEGIC RECOMMENDATIONS ——" in diff_text:
                        parts = diff_text.split("—— STRATEGIC RECOMMENDATIONS ——")
                        main_diff = parts[0].strip()
                        strategy_section = "—— STRATEGIC RECOMMENDATIONS ——\n" + parts[1].strip()

                        # Format and show main diff
                        formatted_main = format_diff_for_display(main_diff)
                        st.markdown(formatted_main)

                        # Highlight strategic recommendations
                        st.markdown("---")
                        st.markdown("### 🎯 Strategic Recommendations")
                        st.info("**How to win each judge type** — specific, actionable advice for both sides based on vote patterns")
                        formatted_strategy = format_diff_for_display(strategy_section)
                        st.markdown(formatted_strategy)
                    else:
                        # Fallback for rounds judged before v0.3
                        formatted_diff = format_diff_for_display(diff_text)
                        st.markdown(formatted_diff)
                except StorageError:
                    st.info("No diff available for this round")

                # Show ballots
                st.subheader("Individual Ballots")
                decisions = metadata.get("decisions", {})
                personas = store.personas_for(resolved_id)

                for paradigm_key in personas:
                    paradigm = PARADIGMS.get(paradigm_key)
                    if paradigm:
                        decision = decisions.get(paradigm_key, "Unknown")
                        try:
                            ballot_text = store.load_ballot(resolved_id, paradigm_key)
                            with st.expander(f"**{paradigm.display_name}:** {decision}"):
                                st.markdown(ballot_text)
                        except StorageError:
                            st.warning(f"Ballot not found for {paradigm.display_name}")

                # Show transcript
                st.subheader("Debate Transcript")
                transcript_file = store.round_path(resolved_id) / "structured_transcript.md"
                if transcript_file.exists():
                    with st.expander("📄 View full transcript"):
                        transcript_text = transcript_file.read_text(encoding="utf-8")
                        st.text(transcript_text)
                else:
                    st.caption("Transcript not available for this round")

        except Exception as e:
            st.error(f"Failed to load round: {e}")
            import traceback
            st.code(traceback.format_exc())
    else:
        st.info("👈 Select a round from the sidebar to view its ballots and diff")

        # Show recent rounds preview
        if rounds:
            st.subheader("Recent Rounds")
            for round_data in rounds[:5]:
                round_id = round_data["round_id"]
                date = round_data.get("date", "")
                resolution = round_data.get("resolution", "Unknown")
                aff = round_data.get("aff", "?")
                decisions = round_data.get("decisions", {})

                with st.container():
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**{resolution}**")
                        st.caption(f"{date} · {aff} (AFF) · {len(decisions)} paradigm(s)")
                    with col2:
                        if st.button("View", key=f"view_{round_id}"):
                            st.session_state.selected_round = round_id
                            st.rerun()
                    st.divider()
