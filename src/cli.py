"""
Command-line interface.

Commands land here increment by increment. Currently: `new` up to input
loading (Story 1.1). Structure detection, judging, and the diff arrive in
Phases 2-4; list/show/rm in Phase 5.
"""

import sys
from pathlib import Path
from typing import Optional

import click

from .archive import archive_input_files
from .bedrock_client import (
    DEBUG_LOG_PATH,
    BedrockError,
    build_client,
    resolve_model_id,
)
from .ingest import (
    DEBATE_TYPES,
    IngestAborted,
    IngestError,
    RoundInput,
    load_round_input,
)
from .documents import read_transcript_text
from .detection import (
    NO_RESOLUTION_MESSAGE,
    DetectionError,
    ResolutionCandidate,
    detect_structure,
    mismatch_message,
    missing_speeches,
)
from .metadata import (
    RoundMetadata,
    confirm_detected_resolution,
    load_metadata_file,
    resolve_metadata,
)
from .judging import (
    DEFAULT_PARADIGMS,
    DEFAULT_RUNS,
    extract_flow,
    generate_diff,
    needs_flow,
    cap_violation,
    cost_line,
    judge_round,
    PARADIGMS,
    UnknownParadigm,
    build_system_prompts,
    parse_personas,
    valid_persona_names,
)
from .storage import LocalDiskBallotStore, StorageError, generate_round_id
from .structure import label_files
from .transcript import format_structured_transcript, summarize_speeches


def print_banner() -> None:
    """
    Name the model in use at startup (Story 6.1).

    Goes to stderr so stdout carries only real output (ballots, diff) and stays
    pipeable — the same rule Story 7.1 sets for --verbose.
    """
    click.echo(f"JudgeAI v0.1 | Model: {resolve_model_id()}", err=True)


@click.group()
def cli() -> None:
    """JudgeAI v0.1 — multi-paradigm LD debate judge."""
    print_banner()


@cli.command()
@click.argument("path_or_type")
@click.option(
    "--format",
    "debate_format",
    default="LD",
    show_default=True,
    help=f"Debate format ({'/'.join(DEBATE_TYPES)}). v0.1 implements LD only.",
)
@click.option(
    "--all",
    "select_all",
    is_flag=True,
    help="Judge every round in the inbox in sequence instead of picking one.",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Accept confirmation prompts automatically (for non-interactive runs).",
)
@click.option(
    "--resolution",
    default=None,
    help="Round resolution. Overrides auto-detection; a round.yaml still wins.",
)
@click.option(
    "--personas",
    default=None,
    help=f"Comma-separated paradigms to judge with. Valid: {valid_persona_names()}.",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Print every model call's prompts and response to stderr (Story 7.1).",
)
@click.option(
    "--runs",
    default=DEFAULT_RUNS,
    show_default=True,
    type=click.IntRange(1, 9),
    help="Judge each paradigm this many times; the lean label comes from the split.",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Show what would be sent to the model, then exit. No calls, no cost.",
)
def new(
    path_or_type: str,
    debate_format: str,
    select_all: bool,
    assume_yes: bool,
    resolution: Optional[str],
    personas: Optional[str],
    verbose: bool,
    runs: int,
    dry_run: bool,
) -> None:
    """
    Judge a new round.

    PATH_OR_TYPE is a .txt file, a folder of speech files, or a debate type
    (auto-picks from that inbox).

    \b
    Examples:
      judge.py new LD
      judge.py new ~/Desktop/JudgeAI/New_Rounds/LD/round.txt
      judge.py new rounds/mark_priya/
    """
    try:
        paradigm_keys = parse_personas(personas)
    except UnknownParadigm as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        rounds = load_round_input(
            path_or_type,
            debate_format=debate_format,
            select_all=select_all,
            confirm=_auto_confirm if assume_yes else None,
        )
    except IngestAborted:
        # A declined confirmation is a deliberate choice, not a failure: exit 0
        # with no error decoration and nothing spent.
        click.echo("Aborted.", err=True)
        return
    except IngestError as exc:
        raise click.ClickException(str(exc)) from exc

    for index, round_input in enumerate(rounds, 1):
        if len(rounds) > 1:
            click.echo(f"\n--- Round {index} of {len(rounds)} ---", err=True)
        _report_loaded(round_input)

        # Story 1.3. `detected_resolution` stays None until Story 2.4 supplies
        # it from the structure-detection pass.
        try:
            yaml_metadata = (
                load_metadata_file(round_input.metadata_file)
                if round_input.metadata_file
                else {}
            )
        except IngestError as exc:
            raise click.ClickException(str(exc)) from exc

        # Labels from filenames first (Story 2.3); the model only gets called
        # when the names don't already say what each speech is.
        labeling = label_files(round_input.files, round_input.debate_format)
        detected_resolution = None

        if labeling.needs_model and not dry_run:
            client = build_client(dry_run=False, verbose=verbose)
            try:
                labeling, detected_resolution = _detect(
                    client, round_input, labeling, assume_yes=assume_yes
                )
            except (DetectionError, BedrockError) as exc:
                raise click.ClickException(str(exc)) from exc

        _report_structure(labeling)

        metadata = resolve_metadata(
            yaml_metadata=yaml_metadata,
            cli_resolution=resolution,
            detected_resolution=detected_resolution,
        )
        _report_metadata(metadata, round_input)

        structured = format_structured_transcript(
            labeling.speeches,
            debate_format=round_input.debate_format,
            resolution=metadata.resolution,
            aff=metadata.aff,
            neg=metadata.neg,
        )

        if dry_run:
            _report_dry_run(
                structured, labeling, paradigm_keys, verbose=verbose
            )
            continue

        # Story 2.2: last chance to fix boundaries before judging is paid for.
        proceed, structured = confirm_structure(structured)
        if not proceed:
            click.echo("Aborted. Nothing saved, no tokens spent.", err=True)
            continue

        # Story 5.1: Round_ID from the confirmed metadata.
        store = LocalDiskBallotStore()
        round_id = generate_round_id(
            {
                "resolution": metadata.resolution,
                "aff": metadata.aff,
                "date": _today(),
            },
            existing_ids=[r["round_id"] for r in store.list_rounds()],
        )
        click.echo(f"\nRound ID: {round_id}", err=True)

        client = build_client(dry_run=False, verbose=verbose)

        # Pass 1: flow the round once, shared across every paradigm allowed to see
        # it. Withheld entirely from Lay Parent, who took no notes.
        flow_text = None
        flow_response = None
        if needs_flow(paradigm_keys):
            click.echo("\nFlowing the round... ", nl=False, err=True)
            flow_response = extract_flow(client, structured)
            flow_text = flow_response.text
            click.echo(
                f"done  {flow_response.output_tokens:>4} out, "
                f"{flow_response.latency_seconds:>5.1f}s, "
                f"${flow_response.cost_usd:.4f}",
                err=True,
            )

        plural = "" if runs == 1 else f" x {runs} runs"
        click.echo(
            f"\nJudging with {len(paradigm_keys)} paradigm(s){plural}:", err=True
        )
        result = judge_round(
            client,
            structured,
            paradigm_keys,
            store=store,
            round_id=round_id,
            on_start=_ballot_start,
            on_run=_report_run,
            on_finish=_report_verdict,
            flow_text=flow_text,
            runs=runs,
        )
        if flow_response is not None:
            result.flow_input_tokens = flow_response.input_tokens
            result.flow_output_tokens = flow_response.output_tokens
            result.flow_cost_usd = flow_response.cost_usd
            store.save_flow(round_id, flow_text)

        _persist_round(store, round_id, structured, metadata, result, round_input)

        if len(result.failures) >= 3 and len(paradigm_keys) > 1:
            # Story 4.3: too little survived to compare.
            raise click.ClickException(
                f"Too many persona failures ({len(result.failures)}/"
                f"{len(paradigm_keys)}). Diff skipped. Check {DEBUG_LOG_PATH}."
            )

        if len(result.successful) == 1 and len(paradigm_keys) == 1:
            # Story 3.2: one persona means nothing to compare, so print the
            # representative ballot rather than a diff.
            click.echo(f"\n{result.successful[0].representative.text}")
        elif len(paradigm_keys) == 1:
            raise click.ClickException("The only requested persona failed.")
        else:
            # Story 4.1: the primary output is a compact cross-paradigm diff.
            click.echo("\nGenerating cross-paradigm diff... ", nl=False, err=True)
            diff_response = generate_diff(
                client,
                round_id,
                _today(),
                metadata.resolution if metadata.has_resolution else None,
                metadata.aff_label,
                metadata.neg_label,
                result,
            )
            result.diff_input_tokens = diff_response.input_tokens
            result.diff_output_tokens = diff_response.output_tokens
            result.diff_cost_usd = diff_response.cost_usd
            click.echo(
                f"done  {diff_response.output_tokens:>4} out, "
                f"{diff_response.latency_seconds:>5.1f}s, "
                f"${diff_response.cost_usd:.4f}",
                err=True,
            )
            store.save_diff(round_id, diff_response.text)
            # Re-persist so metadata.json's totals include the diff cost.
            _persist_round(
                store, round_id, structured, metadata, result, round_input, quiet=True
            )
            click.echo(f"\n{diff_response.text}")

        _archive_if_successful(round_input, round_id, result, paradigm_keys)

        click.echo(
            "\n" + cost_line(
                result.input_tokens, result.output_tokens, result.cost_usd
            ),
            err=True,
        )


@cli.command("list")
@click.option(
    "--full",
    is_flag=True,
    help="Show the full Round_ID instead of the 6-digit prefix.",
)
def list_cmd(full: bool) -> None:
    """List past rounds, newest first (Story 5.2)."""
    store = LocalDiskBallotStore()
    rounds = store.list_rounds()
    if not rounds:
        click.echo(
            "No rounds judged yet. Drop a transcript in "
            "~/Desktop/JudgeAI/New_Rounds/<type>/ and run "
            "`python judge.py new <type>` to judge your first round."
        )
        return

    def _trunc(text: Optional[str], limit: int) -> str:
        text = text or ""
        return text if len(text) <= limit else text[: limit - 1] + "…"

    headers = ("ROUND_ID", "DATE", "FMT", "RESOLUTION", "AFF", "PARADIGMS")
    table = [headers]
    for r in rounds:
        table.append(
            (
                r["round_id"] if full else f"{r['short_id']}…",
                r.get("date") or "(no date)",
                r.get("format") or "?",
                _trunc(r.get("resolution"), 45) or "(no resolution)",
                r.get("aff") or "(no aff)",
                ", ".join(r.get("paradigms") or []) or "(none)",
            )
        )

    widths = [max(len(row[i]) for row in table) for i in range(len(headers))]
    for index, row in enumerate(table):
        click.echo("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
        if index == 0:  # underline the header
            click.echo("  ".join("-" * w for w in widths))


def _resolve_single(store, round_id: str) -> str:
    """
    Map a user-supplied id to exactly one Round_ID, or fail loudly (Stories 5.3,
    5.4). Not-found and ambiguous both raise, so callers never act on a guess.
    """
    matches = store.resolve_round_id(round_id)
    if not matches:
        raise click.ClickException(
            f"Round '{round_id}' not found. Try `judge.py list` to see "
            f"available rounds."
        )
    if len(matches) > 1:
        listing = "\n".join(f"  {m}" for m in matches)
        raise click.ClickException(
            f"'{round_id}' matches multiple rounds:\n{listing}\n"
            f"Re-run with a more specific ID."
        )
    return matches[0]


@cli.command("show")
@click.argument("round_id")
@click.option(
    "--persona",
    default=None,
    help=f"Show one paradigm's full ballot instead of the diff. Valid: "
    f"{valid_persona_names()}.",
)
def show_cmd(round_id: str, persona: Optional[str]) -> None:
    """Print a past round's diff, or one paradigm's ballot (Story 5.3)."""
    store = LocalDiskBallotStore()
    resolved = _resolve_single(store, round_id)

    if persona is not None:
        key = persona.strip().lower()
        if key not in PARADIGMS:
            raise click.ClickException(
                f"Unknown persona '{persona}'. Valid: {valid_persona_names()}."
            )
        try:
            click.echo(store.load_ballot(resolved, key))
        except StorageError:
            judged = ", ".join(store.personas_for(resolved)) or "none"
            raise click.ClickException(
                f"No {PARADIGMS[key].display_name} ballot for round '{resolved}'. "
                f"Judged paradigms: {judged}."
            )
        return

    try:
        click.echo(store.load_diff(resolved))
    except StorageError:
        raise click.ClickException(
            f"No diff saved for round '{resolved}' (it may have been judged with "
            f"a single paradigm). Try `show {round_id} --persona <name>`."
        )


@cli.command("rm")
@click.argument("round_id")
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    help="Delete without the confirmation prompt.",
)
def rm_cmd(round_id: str, assume_yes: bool) -> None:
    """Delete a past round's ballots (Story 5.4). Archived inputs are untouched."""
    store = LocalDiskBallotStore()
    resolved = _resolve_single(store, round_id)
    if not assume_yes and not click.confirm(
        f"Delete round '{resolved}' and all its ballots?", default=False
    ):
        click.echo("Nothing deleted.")
        return
    store.delete_round(resolved)
    click.echo(
        f"Deleted round '{resolved}'. (Archived input in Past_Rounds/ was left "
        f"in place.)"
    )


def _auto_confirm(message: str) -> bool:
    """
    Answer yes to a prompt on the user's behalf under --yes.

    Still echoes what was confirmed, so an auto-accepted warning stays visible
    in the transcript rather than being silently swallowed.
    """
    click.echo(f"{message} [auto-confirmed via --yes]", err=True)
    return True


def _report_metadata(metadata: RoundMetadata, round_input: RoundInput) -> None:
    """Show the resolved metadata and where each field came from (Story 1.3)."""
    click.echo("\nMetadata:", err=True)
    if metadata.has_resolution:
        click.echo(
            f'  Resolution: "{metadata.resolution}" '
            f"({metadata.sources.get('resolution')})",
            err=True,
        )
    else:
        click.echo("  Resolution: (none — ballots won't quote one)", err=True)

    for label, value, key in (
        ("Aff", metadata.aff_label, "aff"),
        ("Neg", metadata.neg_label, "neg"),
    ):
        origin = metadata.sources.get(key)
        note = f"({origin})" if origin != "skipped" else "(generic label)"
        click.echo(f"  {label}: {value} {note}", err=True)

    if metadata.overridden_detection:
        click.echo(
            f"  Note: auto-detected resolution overridden: "
            f'"{metadata.overridden_detection}"',
            err=True,
        )


def _report_structure(labeling) -> None:
    """Show the speech structure read from filenames (Story 2.3)."""
    click.echo("\nStructure:", err=True)
    origins = {
        "filename": "from filename",
        "model": "detected",
        "unlabeled": "unlabeled",
    }
    for row in summarize_speeches(labeling.speeches):
        origin = origins.get(row["source"], row["source"])
        click.echo(
            f"  {row['index']}. {row['label']:<6} "
            f"(~{row['words']:,} words, {row['speaker']}) "
            f"[{origin}: {row['file']}]",
            err=True,
        )
    if labeling.duplicates:
        click.echo(
            f"  Duplicate labels: {', '.join(labeling.duplicates)}", err=True
        )
    if labeling.needs_model:
        missing = labeling.missing_labels
        detail = f" Missing: {', '.join(missing)}." if missing else ""
        click.echo(
            f"  Structure detection needed.{detail}",
            err=True,
        )
    elif any(s.source == "model" for s in labeling.speeches):
        click.echo("  Structure detected from the transcript.", err=True)
    else:
        click.echo(
            "  All speeches labeled from filenames — "
            "no detection call needed.",
            err=True,
        )


def _report_dry_run(
    structured: str, labeling, paradigm_keys=None, verbose: bool = False
) -> None:
    """
    Show what would be sent, without sending it (Story 7.2).

    Prints to stdout: in dry-run the assembled prompt *is* the output, so it
    should be redirectable to a file for inspection.
    """
    click.echo("\n=== DRY RUN — no model calls, no files written ===", err=True)
    click.echo(
        f"Would send a structured transcript of "
        f"{len(structured):,} chars (~{len(structured) // 4:,} tokens).",
        err=True,
    )
    keys = list(paradigm_keys or DEFAULT_PARADIGMS)
    if labeling.needs_model:
        click.echo("Would call: structure detection.", err=True)
    for key in keys:
        click.echo(
            f"Would call: {PARADIGMS[key].display_name} "
            f"(RFD cap {PARADIGMS[key].rfd_word_cap}w).",
            err=True,
        )
    if len(keys) >= 2:
        click.echo("Would call: cross-paradigm diff.", err=True)
    else:
        click.echo("Diff skipped: only one persona, nothing to compare.", err=True)

    click.echo("\n--- STRUCTURED TRANSCRIPT ---")
    click.echo(structured if verbose else _elide(structured))

    for key, prompt in build_system_prompts(keys).items():
        click.echo(f"\n--- SYSTEM PROMPT: {PARADIGMS[key].display_name} ---")
        click.echo(prompt if verbose else _elide(prompt, head=700))

    click.echo("\nNo cost incurred.", err=True)


def _elide(text: str, head: int = 1200) -> str:
    """Trim long output unless --verbose asked for everything."""
    if len(text) <= head:
        return text
    remaining = len(text) - head
    return (
        f"{text[:head]}\n\n"
        f"... [{remaining:,} more chars — pass --verbose for the full text]"
    )


def _report_loaded(round_input: RoundInput) -> None:
    """Summarize what was loaded, pending structure detection (Phase 2)."""
    mode = "folder of speech files" if round_input.is_folder else "single file"
    total_chars = sum(len(read_transcript_text(f)) for f in round_input.files)

    click.echo(f"\nLoaded {round_input.name} ({mode})", err=True)
    click.echo(f"  Format: {round_input.debate_format}", err=True)
    click.echo(f"  Files:  {len(round_input.files)}", err=True)
    for file in round_input.files:
        click.echo(f"    - {file.name}", err=True)
    if round_input.metadata_file:
        click.echo(f"  Metadata: {round_input.metadata_file.name}", err=True)
    click.echo(f"  Size:   {total_chars:,} chars", err=True)
    click.echo("\nNext: structure detection (Phase 2, not yet built).", err=True)


def _detect(client, round_input, labeling, assume_yes: bool = False):
    """
    Run structure detection and resolution auto-detect (Stories 2.1, 2.4).

    Returns (labeling, confirmed_resolution). Detection replaces filename-based
    labeling only when it actually found more speeches — a worse result is not
    an improvement.
    """
    from .detection import detect_structure, mismatch_message, missing_speeches
    from .structure import LabelingResult, expected_labels

    candidates = []
    detected_speeches = []

    # One call per file: a folder's 1AC and 1NC can state different resolutions,
    # which is exactly the conflict Story 2.4 has to surface.
    for source in round_input.files:
        text = read_transcript_text(source)
        result, speeches = detect_structure(client, text, round_input.debate_format)
        detected_speeches.extend(speeches)
        if result.resolution_text:
            candidates.append(
                ResolutionCandidate(
                    text=result.resolution_text,
                    source_label=(result.labels[0] if result.labels else source.name),
                    confidence=result.resolution_confidence,
                    quote=result.resolution_quote,
                )
            )

    if len(detected_speeches) > labeling.labeled_count:
        labeling = LabelingResult(speeches=detected_speeches)
        labeling._expected = expected_labels(round_input.debate_format)

    expected = len(expected_labels(round_input.debate_format)) or len(detected_speeches)
    found = [s.label for s in labeling.speeches if s.label]
    missing = missing_speeches(found, round_input.debate_format)
    if missing:
        message = mismatch_message(len(found), missing, expected)
        # Defaults to yes, per Story 2.1's "[Y/n]" — a partial round is usually
        # still worth judging.
        if assume_yes:
            click.echo(f"{message} [auto-confirmed via --yes]", err=True)
        elif not click.confirm(message, default=True, err=True):
            raise IngestAborted(message)

    confirmed = None
    if candidates:
        confirmed = confirm_detected_resolution(candidates, ask=_ask)
    else:
        click.echo(f"\n{NO_RESOLUTION_MESSAGE}", err=True)
    return labeling, confirmed


def _ask(prompt: str) -> str:
    """Free-text prompt for the resolution flow; Enter accepts the default."""
    try:
        return click.prompt(prompt, default="", show_default=False, err=True)
    except (click.Abort, EOFError, OSError):
        return ""


CONFIRM_PROMPT = "Confirm? [Y/edit/quit]"


def confirm_structure(
    structured: str,
    ask: Optional[callable] = None,
    launch_editor: Optional[callable] = None,
):
    """
    Confirm, edit, or abandon the detected structure (Story 2.2).

    Returns (proceed, structured_transcript). `edit` reopens the editor until the
    user confirms, so a mistake in the editor doesn't force a restart of the run.
    """
    from .transcript import parse_structured_transcript

    respond = ask or _ask
    edit = launch_editor or _launch_editor

    while True:
        answer = (respond(CONFIRM_PROMPT) or "").strip().lower()

        if answer in ("", "y", "yes"):
            return True, structured
        if answer in ("q", "quit", "n", "no"):
            # Story 2.2: exit without saving anything or spending model tokens.
            return False, structured
        if answer in ("e", "edit"):
            edited = edit(structured)
            if edited and edited.strip():
                if parse_structured_transcript(edited):
                    structured = edited
                else:
                    click.echo(
                        "  Edited transcript has no `=== LABEL ===` headers; "
                        "keeping the previous version.",
                        err=True,
                    )
            continue
        click.echo(f"  Unrecognized answer {answer!r}. {CONFIRM_PROMPT}", err=True)


def _launch_editor(structured: str) -> Optional[str]:
    """
    Open the structured transcript in $EDITOR and return what came back.

    Uses a real temp file rather than click.edit()'s default so the editor choice
    honours JUDGEAI_EDITOR/VISUAL/EDITOR and failures are reportable.
    """
    import subprocess
    import tempfile

    from .transcript import resolve_editor

    editor = resolve_editor()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(structured)
        temp_path = handle.name

    try:
        subprocess.run([*editor.split(), temp_path], check=True)
        return Path(temp_path).read_text(encoding="utf-8")
    except (OSError, subprocess.CalledProcessError) as exc:
        click.echo(f"  Could not open editor ({editor}): {exc}", err=True)
        return None
    finally:
        try:
            Path(temp_path).unlink()
        except OSError:
            pass


def _today() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d")


def _persist_round(
    store, round_id, structured, metadata, result, round_input, quiet: bool = False
) -> None:
    """
    Write the transcript and metadata (Stories 5.1, 6.2).

    Ballots were already saved as they arrived. A write failure here must not
    discard a paid-for run, so ballots fall back to stdout.
    """
    payload = {
        **metadata.to_dict(),
        "round_id": round_id,
        "format": round_input.debate_format,
        "date": _today(),
        "input": round_input.name,
        "paradigms": [v.paradigm for v in result.successful],
        "failed_paradigms": [v.paradigm for v in result.failures],
        "runs_per_paradigm": len(result.verdicts[0].runs) if result.verdicts else 0,
        "decisions": {v.paradigm: v.decision for v in result.verdicts},
        "token_usage": result.token_usage(),
        "total_input_tokens": result.input_tokens,
        "total_output_tokens": result.output_tokens,
        "total_cost_usd": round(result.cost_usd, 6),
    }
    try:
        store.save_transcript(round_id, structured)
        store.save_metadata(round_id, payload)
    except StorageError as exc:
        click.echo(
            f"\nCannot write ballots to {store.round_path(round_id)}: {exc}. "
            f"Ballots printed to stdout below:",
            err=True,
        )
        for verdict in result.successful:
            click.echo(f"\n=== {PARADIGMS[verdict.paradigm].display_name} ===")
            click.echo(verdict.representative.text)
        return
    if not quiet:
        click.echo(f"\nSaved to {store.round_path(round_id)}", err=True)


def _archive_if_successful(round_input, round_id, result, paradigm_keys) -> None:
    """
    Move the inputs to the archive, but only on success (Story 1.4).

    "Success" means every requested paradigm produced a ballot. A partial run
    leaves the inputs in the inbox so the round can simply be re-run — moving
    them would make retrying a manual file hunt.
    """
    if result.failures:
        click.echo(
            f"\n{len(result.failures)} of {len(paradigm_keys)} paradigms failed — "
            f"inputs left in the inbox for a retry.",
            err=True,
        )
        return

    outcome = archive_input_files(round_input, round_id)
    if not outcome.ok:
        click.echo(f"\n{outcome.warning}", err=True)
        return
    click.echo(
        f"\nArchived {outcome.count} input file(s) to {outcome.archive_dir}",
        err=True,
    )


def _ballot_start(paradigm, runs: int = 1) -> None:
    """Announce a paradigm, noting how much of the flow it may use."""
    from .judging import FLOW_NONE, FLOW_PARTIAL

    note = {FLOW_NONE: " (no flow)", FLOW_PARTIAL: " (own notes)"}.get(
        paradigm.flow_access, ""
    )
    click.echo(f"  {paradigm.display_name}{note}", err=True)


def _report_run(paradigm, index: int, total: int, ballot) -> None:
    """One line per run, so a long multi-run round shows progress."""
    from .judging import extract_winner

    if ballot.failed:
        click.echo(
            f"    {paradigm.display_name} run {index}/{total}: "
            f"FAILED ({ballot.error[:50]})",
            err=True,
        )
        return
    winner = extract_winner(ballot.text) or "?"
    click.echo(
        f"    {paradigm.display_name} run {index}/{total}: {winner:<4} "
        f"{ballot.output_tokens:>4} out, {ballot.latency_seconds:>5.1f}s, "
        f"${ballot.cost_usd:.4f}",
        err=True,
    )


def _report_verdict(paradigm, verdict) -> None:
    """The paradigm's collapsed decision, plus any cap warning."""
    from .judging import cap_violation

    click.echo(f"    -> {paradigm.display_name}: {verdict.decision}", err=True)
    representative = verdict.representative
    if representative is not None:
        over = cap_violation(verdict.paradigm, representative.text)
        if over:
            click.echo(f"       warning: {over}", err=True)
