"""JudgeAI command-line interface."""

import sys
from pathlib import Path
from typing import Callable, Optional

import click

from .archive import archive_input_files
from .bedrock_client import DEBUG_LOG_PATH, build_client
from .detection import (
    NO_RESOLUTION_MESSAGE,
    DetectionError,
    ResolutionCandidate,
    mismatch_message,
    missing_speeches,
)
from .documents import read_transcript_text
from .ingest import DEBATE_TYPES, IngestAborted, IngestError, RoundInput, load_round_input
from .judging import (
    DEFAULT_PARADIGMS,
    DEFAULT_RUNS,
    PARADIGMS,
    UnknownParadigm,
    build_system_prompts,
    cap_violation,
    cost_line,
    extract_flow,
    generate_diff,
    judge_round,
    needs_flow,
    parse_personas,
    valid_persona_names,
)
from .llm_client import CredentialsError, ModelInvocationError
from .metadata import (
    RoundMetadata,
    confirm_detected_resolution,
    detect_participant_names,
    load_metadata_file,
    resolve_metadata,
)
from .storage import LocalDiskBallotStore, StorageError, generate_round_id
from .structure import label_files
from .transcript import format_structured_transcript, summarize_speeches


def print_banner() -> None:
    # Do not claim a model before provider selection actually happens.
    click.echo("JudgeAI v0.1", err=True)


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
    help=f"Debate format ({'/'.join(DEBATE_TYPES)}). v0.1 judging implements LD only.",
)
@click.option("--all", "select_all", is_flag=True, help="Judge every round in the inbox.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Accept confirmation prompts automatically.")
@click.option("--resolution", default=None, help="Round resolution; overrides auto-detection unless round.yaml supplies one.")
@click.option(
    "--personas",
    default=None,
    help=f"Comma-separated paradigms. Valid: {valid_persona_names()}.",
)
@click.option("--verbose", is_flag=True, help="Print model prompts/responses to stderr.")
@click.option(
    "--runs",
    default=DEFAULT_RUNS,
    show_default=True,
    type=click.IntRange(1, 9),
    help="Judge each paradigm this many times.",
)
@click.option("--dry-run", "dry_run", is_flag=True, help="Preview prompts without model calls or cost.")
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
    """Judge a new round from a transcript file/folder or the LD inbox."""
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
        click.echo("Aborted.", err=True)
        return
    except IngestError as exc:
        raise click.ClickException(str(exc)) from exc

    for index, round_input in enumerate(rounds, 1):
        if len(rounds) > 1:
            click.echo(f"\n--- Round {index} of {len(rounds)} ---", err=True)
        _run_one_round(
            round_input=round_input,
            resolution=resolution,
            paradigm_keys=paradigm_keys,
            verbose=verbose,
            runs=runs,
            dry_run=dry_run,
            assume_yes=assume_yes,
        )


def _run_one_round(
    round_input: RoundInput,
    resolution: Optional[str],
    paradigm_keys: list[str],
    verbose: bool,
    runs: int,
    dry_run: bool,
    assume_yes: bool,
) -> None:
    _report_loaded(round_input)

    try:
        yaml_metadata = (
            load_metadata_file(round_input.metadata_file)
            if round_input.metadata_file
            else {}
        )
    except IngestError as exc:
        raise click.ClickException(str(exc)) from exc

    labeling = label_files(round_input.files, round_input.debate_format)
    detected_resolution = None
    client = None

    if labeling.needs_model and not dry_run:
        client = _build_reported_client(verbose=verbose)
        try:
            labeling, detected_resolution = _detect(
                client, round_input, labeling, assume_yes=assume_yes
            )
        except (DetectionError, ModelInvocationError, CredentialsError) as exc:
            raise click.ClickException(str(exc)) from exc
        except IngestAborted:
            click.echo("Aborted.", err=True)
            return

    _report_structure(labeling)
    participants = detect_participant_names(round_input.files, labeling.speeches)
    metadata = resolve_metadata(
        yaml_metadata=yaml_metadata,
        cli_resolution=resolution,
        detected_resolution=detected_resolution,
        detected_aff=participants.get("aff"),
        detected_neg=participants.get("neg"),
        prompt=(lambda _prompt: "") if assume_yes else None,
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
        _report_dry_run(structured, labeling, paradigm_keys, verbose=verbose)
        return

    if assume_yes:
        click.echo("\nStructure confirmation [auto-confirmed via --yes]", err=True)
        proceed = True
    else:
        proceed, structured = confirm_structure(structured)
    if not proceed:
        click.echo("Aborted. Nothing saved, no tokens spent.", err=True)
        return

    store = LocalDiskBallotStore()
    round_id = generate_round_id(
        {
            "resolution": metadata.resolution,
            "aff": metadata.aff,
            "date": _today(),
        },
        existing_ids=[row["round_id"] for row in store.list_rounds()],
    )
    click.echo(f"\nRound ID: {round_id}", err=True)

    if client is None:
        client = _build_reported_client(verbose=verbose)

    flow_text = None
    flow_response = None
    if needs_flow(paradigm_keys):
        click.echo("\nFlowing the round... ", nl=False, err=True)
        try:
            flow_response = extract_flow(client, structured)
        except (ModelInvocationError, CredentialsError) as exc:
            raise click.ClickException(f"Flow extraction failed: {exc}") from exc
        flow_text = flow_response.text
        click.echo(
            f"done  {flow_response.output_tokens:>4} out, "
            f"{flow_response.latency_seconds:>5.1f}s, "
            f"${flow_response.cost_usd:.4f}",
            err=True,
        )

    plural = "" if runs == 1 else f" x {runs} runs"
    click.echo(f"\nJudging with {len(paradigm_keys)} paradigm(s){plural}:", err=True)

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
        try:
            store.save_flow(round_id, flow_text)
        except StorageError as exc:
            click.echo(f"Warning: could not save flow: {exc}", err=True)

    _persist_round(store, round_id, structured, metadata, result, round_input)

    # Preserve the v0.1 edge-case contract: three or more persona failures
    # abort the comparison with the established message. Also guard smaller
    # custom persona sets from trying to diff fewer than two successful ballots.
    if len(result.failures) >= 3 and len(paradigm_keys) > 1:
        raise click.ClickException(
            f"Too many persona failures ({len(result.failures)}/{len(paradigm_keys)}). "
            f"Diff skipped. Check {DEBUG_LOG_PATH}."
        )
    if len(paradigm_keys) > 1 and len(result.successful) < 2:
        raise click.ClickException(
            f"Only {len(result.successful)} of {len(paradigm_keys)} paradigms succeeded. "
            f"Diff skipped. Check {DEBUG_LOG_PATH}."
        )

    if len(paradigm_keys) == 1:
        if len(result.successful) == 1:
            click.echo(f"\n{result.successful[0].representative.text}")
        else:
            raise click.ClickException("The only requested persona failed.")
    else:
        click.echo("\nGenerating cross-paradigm diff... ", nl=False, err=True)
        try:
            diff_response = generate_diff(
                client,
                round_id,
                _today(),
                metadata.resolution if metadata.has_resolution else None,
                metadata.aff_label,
                metadata.neg_label,
                result,
            )
        except (ModelInvocationError, CredentialsError) as exc:
            raise click.ClickException(f"Cross-paradigm diff failed: {exc}") from exc

        result.diff_input_tokens = diff_response.input_tokens
        result.diff_output_tokens = diff_response.output_tokens
        result.diff_cost_usd = diff_response.cost_usd
        click.echo(
            f"done  {diff_response.output_tokens:>4} out, "
            f"{diff_response.latency_seconds:>5.1f}s, "
            f"${diff_response.cost_usd:.4f}",
            err=True,
        )
        try:
            store.save_diff(round_id, diff_response.text)
        except StorageError as exc:
            raise click.ClickException(f"Could not save diff: {exc}") from exc
        _persist_round(store, round_id, structured, metadata, result, round_input, quiet=True)
        click.echo(f"\n{diff_response.text}")

    _archive_if_successful(round_input, round_id, result, paradigm_keys)
    click.echo("\n" + cost_line(result.input_tokens, result.output_tokens, result.cost_usd), err=True)


@cli.command("list")
@click.option("--full", is_flag=True, help="Show the full Round_ID.")
def list_cmd(full: bool) -> None:
    store = LocalDiskBallotStore()
    rounds = store.list_rounds()
    if not rounds:
        click.echo(
            "No rounds judged yet. Drop a transcript in "
            "~/Desktop/JudgeAI/New_Rounds/<type>/ and run "
            "`python judge.py new <type>` to judge your first round."
        )
        return

    def trunc(text: Optional[str], limit: int) -> str:
        text = text or ""
        return text if len(text) <= limit else text[: limit - 1] + "…"

    headers = ("ROUND_ID", "DATE", "FMT", "RESOLUTION", "AFF", "PARADIGMS")
    table = [headers]
    for row in rounds:
        table.append(
            (
                row["round_id"] if full else f"{row['short_id']}…",
                row.get("date") or "(no date)",
                row.get("format") or "?",
                trunc(row.get("resolution"), 45) or "(no resolution)",
                row.get("aff") or "(no aff)",
                ", ".join(row.get("paradigms") or []) or "(none)",
            )
        )
    widths = [max(len(row[index]) for row in table) for index in range(len(headers))]
    for index, row in enumerate(table):
        click.echo("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
        if index == 0:
            click.echo("  ".join("-" * width for width in widths))


@cli.command("show")
@click.argument("round_id")
@click.option("--persona", default=None, help=f"Show one paradigm ballot. Valid: {valid_persona_names()}.")
def show_cmd(round_id: str, persona: Optional[str]) -> None:
    store = LocalDiskBallotStore()
    resolved = _resolve_single(store, round_id)
    if persona is not None:
        key = persona.strip().lower()
        if key not in PARADIGMS:
            raise click.ClickException(f"Unknown persona '{persona}'. Valid: {valid_persona_names()}.")
        try:
            click.echo(store.load_ballot(resolved, key))
        except StorageError as exc:
            judged = ", ".join(store.personas_for(resolved)) or "none"
            raise click.ClickException(
                f"No {PARADIGMS[key].display_name} ballot for '{resolved}'. Judged: {judged}."
            ) from exc
        return
    try:
        click.echo(store.load_diff(resolved))
    except StorageError as exc:
        raise click.ClickException(
            f"No diff saved for '{resolved}'. Try `show {round_id} --persona <name>`."
        ) from exc


@cli.command("rm")
@click.argument("round_id")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Delete without confirmation.")
def rm_cmd(round_id: str, assume_yes: bool) -> None:
    store = LocalDiskBallotStore()
    resolved = _resolve_single(store, round_id)
    if not assume_yes and not click.confirm(
        f"Delete round '{resolved}' and all its ballots?", default=False
    ):
        click.echo("Nothing deleted.")
        return
    store.delete_round(resolved)
    click.echo(f"Deleted round '{resolved}'. Archived input was left in place.")


def _resolve_single(store, round_id: str) -> str:
    matches = store.resolve_round_id(round_id)
    if not matches:
        raise click.ClickException(f"Round '{round_id}' not found. Try `judge.py list`.")
    if len(matches) > 1:
        listing = "\n".join(f"  {match}" for match in matches)
        raise click.ClickException(
            f"'{round_id}' matches multiple rounds:\n{listing}\nRe-run with a more specific ID."
        )
    return matches[0]


def _build_reported_client(verbose: bool = False):
    try:
        client = build_client(dry_run=False, verbose=verbose)
    except (CredentialsError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    provider = getattr(client, "current_provider_name", type(client).__name__)
    model = getattr(client, "model_id", "unknown model")
    click.echo(f"LLM: {provider} | {model}", err=True)
    return client


def _auto_confirm(message: str) -> bool:
    click.echo(f"{message} [auto-confirmed via --yes]", err=True)
    return True


def _report_metadata(metadata: RoundMetadata, round_input: RoundInput) -> None:
    click.echo("\nMetadata:", err=True)
    if metadata.has_resolution:
        click.echo(
            f'  Resolution: "{metadata.resolution}" ({metadata.sources.get("resolution")})',
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
            f'  Note: auto-detected resolution overridden: "{metadata.overridden_detection}"',
            err=True,
        )


def _report_structure(labeling) -> None:
    click.echo("\nStructure:", err=True)
    origins = {"filename": "from filename", "model": "detected", "unlabeled": "unlabeled"}
    for row in summarize_speeches(labeling.speeches):
        origin = origins.get(row["source"], row["source"])
        click.echo(
            f"  {row['index']}. {row['label']:<6} (~{row['words']:,} words, {row['speaker']}) "
            f"[{origin}: {row['file']}]",
            err=True,
        )
    if labeling.duplicates:
        click.echo(f"  Duplicate labels: {', '.join(labeling.duplicates)}", err=True)
    if labeling.needs_model:
        missing = labeling.missing_labels
        detail = f" Missing: {', '.join(missing)}." if missing else ""
        click.echo(f"  Structure detection needed.{detail}", err=True)
    elif any(s.source == "model" for s in labeling.speeches):
        click.echo("  Structure detected from the transcript.", err=True)
    else:
        click.echo("  All speeches labeled from filenames — no detection call needed.", err=True)


def _report_dry_run(structured: str, labeling, paradigm_keys=None, verbose: bool = False) -> None:
    click.echo("\n=== DRY RUN — no model calls, no files written ===", err=True)
    click.echo(
        f"Would send a structured transcript of {len(structured):,} chars (~{len(structured) // 4:,} tokens).",
        err=True,
    )
    keys = list(paradigm_keys or DEFAULT_PARADIGMS)
    if labeling.needs_model:
        click.echo("Would call: structure detection.", err=True)
    if needs_flow(keys):
        click.echo("Would call: shared flow extraction.", err=True)
    for key in keys:
        click.echo(
            f"Would call: {PARADIGMS[key].display_name} (RFD cap {PARADIGMS[key].rfd_word_cap}w).",
            err=True,
        )
    if len(keys) >= 2:
        click.echo("Would call: cross-paradigm diff.", err=True)
    click.echo("\n--- STRUCTURED TRANSCRIPT ---")
    click.echo(structured if verbose else _elide(structured))
    for key, prompt in build_system_prompts(keys).items():
        click.echo(f"\n--- SYSTEM PROMPT: {PARADIGMS[key].display_name} ---")
        click.echo(prompt if verbose else _elide(prompt, head=700))
    click.echo("\nNo cost incurred.", err=True)


def _elide(text: str, head: int = 1200) -> str:
    if len(text) <= head:
        return text
    remaining = len(text) - head
    return f"{text[:head]}\n\n... [{remaining:,} more chars — pass --verbose for the full text]"


def _report_loaded(round_input: RoundInput) -> None:
    mode = "folder of speech files" if round_input.is_folder else "single file"
    total_chars = sum(len(read_transcript_text(file)) for file in round_input.files)
    click.echo(f"\nLoaded {round_input.name} ({mode})", err=True)
    click.echo(f"  Format: {round_input.debate_format}", err=True)
    click.echo(f"  Files:  {len(round_input.files)}", err=True)
    for file in round_input.files:
        click.echo(f"    - {file.name}", err=True)
    if round_input.metadata_file:
        click.echo(f"  Metadata: {round_input.metadata_file.name}", err=True)
    click.echo(f"  Size:   {total_chars:,} chars", err=True)
    click.echo("\nNext: detecting transcript structure.", err=True)


def _detect(client, round_input, labeling, assume_yes: bool = False):
    from .detection import detect_structure
    from .structure import LabelingResult, expected_labels

    candidates = []
    detected_speeches = []
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
    found = [speech.label for speech in labeling.speeches if speech.label]
    missing = missing_speeches(found, round_input.debate_format)
    if missing:
        message = mismatch_message(len(found), missing, expected)
        if assume_yes:
            click.echo(f"{message} [auto-confirmed via --yes]", err=True)
        elif not click.confirm(message, default=True, err=True):
            raise IngestAborted(message)

    if candidates:
        ask = (lambda _prompt: "") if assume_yes else _ask
        return labeling, confirm_detected_resolution(candidates, ask=ask)

    click.echo(f"\n{NO_RESOLUTION_MESSAGE}", err=True)
    return labeling, None


def _ask(prompt: str) -> str:
    try:
        return click.prompt(prompt, default="", show_default=False, err=True)
    except (click.Abort, EOFError, OSError):
        return ""


CONFIRM_PROMPT = "Confirm? [Y/edit/quit]"


def confirm_structure(
    structured: str,
    ask: Optional[Callable[[str], str]] = None,
    launch_editor: Optional[Callable[[str], Optional[str]]] = None,
):
    from .transcript import parse_structured_transcript

    respond = ask or _ask
    edit = launch_editor or _launch_editor
    while True:
        answer = (respond(CONFIRM_PROMPT) or "").strip().lower()
        if answer in ("", "y", "yes"):
            return True, structured
        if answer in ("q", "quit", "n", "no"):
            return False, structured
        if answer in ("e", "edit"):
            edited = edit(structured)
            if edited and edited.strip():
                if parse_structured_transcript(edited):
                    structured = edited
                else:
                    click.echo(
                        "  Edited transcript has no `=== LABEL ===` headers; keeping the previous version.",
                        err=True,
                    )
            continue
        click.echo(f"  Unrecognized answer {answer!r}. {CONFIRM_PROMPT}", err=True)


def _launch_editor(structured: str) -> Optional[str]:
    import subprocess
    import tempfile

    from .transcript import resolve_editor

    editor = resolve_editor()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as handle:
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


def _persist_round(store, round_id, structured, metadata, result, round_input, quiet: bool = False) -> None:
    payload = {
        **metadata.to_dict(),
        "round_id": round_id,
        "format": round_input.debate_format,
        "date": _today(),
        "input": round_input.name,
        "paradigms": [verdict.paradigm for verdict in result.successful],
        "failed_paradigms": [verdict.paradigm for verdict in result.failures],
        "runs_per_paradigm": len(result.verdicts[0].runs) if result.verdicts else 0,
        "decisions": {verdict.paradigm: verdict.decision for verdict in result.verdicts},
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
            f"\nCannot write results to {store.round_path(round_id)}: {exc}. Ballots printed below:",
            err=True,
        )
        for verdict in result.successful:
            click.echo(f"\n=== {PARADIGMS[verdict.paradigm].display_name} ===")
            click.echo(verdict.representative.text)
        return
    if not quiet:
        click.echo(f"\nSaved to {store.round_path(round_id)}", err=True)


def _archive_if_successful(round_input, round_id, result, paradigm_keys) -> None:
    if result.failures:
        click.echo(
            f"\n{len(result.failures)} of {len(paradigm_keys)} paradigms failed — inputs left in place for retry.",
            err=True,
        )
        return
    outcome = archive_input_files(round_input, round_id)
    if not outcome.ok:
        click.echo(f"\n{outcome.warning}", err=True)
        return
    click.echo(f"\nArchived {outcome.count} input file(s) to {outcome.archive_dir}", err=True)


def _ballot_start(paradigm, runs: int = 1) -> None:
    from .judging import FLOW_NONE, FLOW_PARTIAL
    note = {FLOW_NONE: " (no flow)", FLOW_PARTIAL: " (own notes)"}.get(paradigm.flow_access, "")
    click.echo(f"  {paradigm.display_name}{note}", err=True)


def _report_run(paradigm, index: int, total: int, ballot) -> None:
    from .judging import extract_winner
    if ballot.failed:
        click.echo(
            f"    {paradigm.display_name} run {index}/{total}: FAILED ({ballot.error[:80]})",
            err=True,
        )
        return
    winner = extract_winner(ballot.text) or "?"
    click.echo(
        f"    {paradigm.display_name} run {index}/{total}: {winner:<4} "
        f"{ballot.output_tokens:>4} out, {ballot.latency_seconds:>5.1f}s, ${ballot.cost_usd:.4f}",
        err=True,
    )


def _report_verdict(paradigm, verdict) -> None:
    click.echo(f"    -> {paradigm.display_name}: {verdict.decision}", err=True)
    representative = verdict.representative
    if representative is not None:
        over = cap_violation(verdict.paradigm, representative.text)
        if over:
            click.echo(f"       warning: {over}", err=True)
