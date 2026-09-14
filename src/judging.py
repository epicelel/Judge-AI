"""
Paradigm registry and prompt assembly (Epic 3).

Four paradigms per MVP §4.5. They differ along philosophy, tolerance, and
vocabulary — not skill. There is no "best" judge here: a circuit judge and a
traditional judge are both expert, and they write near-opposite ballots on the
same round. That difference is the product (Story 3.3, the kill/proceed gate).

The judging pipeline itself lands in Increments 11-12; this module currently owns
the registry and system-prompt assembly so `--personas` and `--dry-run` work.
"""

import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .prompts import load_prompt

SHARED_STANDARDS = "shared/ld_standards"
FLOW_PROMPT = "shared/flow_extraction"

# How much of the flow each paradigm may see. This mirrors the recall tier stated
# in each persona prompt: a lay parent took no notes at all, so handing them a flow
# would turn them into a trained judge (User Stories Story 3.3 discussion,
# 2026-08-15).
FLOW_NONE = "none"        # judges from the transcript alone
FLOW_PARTIAL = "partial"  # sees it, but framed as their own imperfect notes
FLOW_FULL = "full"        # authoritative

FLOW_MAX_TOKENS = 6000
FLOW_TEMPERATURE = 0.0


@dataclass(frozen=True)
class Paradigm:
    """One judge persona."""

    key: str
    display_name: str
    prompt_name: str
    rfd_word_cap: int
    flow_access: str = "full"

    @property
    def ballot_filename(self) -> str:
        return f"judge_{self.key}.md"


# Order matters: it's the order ballots are generated and listed in the diff,
# running from least to most technical so the diff reads as a spectrum.
PARADIGM_LIST: Tuple[Paradigm, ...] = (
    Paradigm("lay", "Lay Parent", "judge_lay", 80, FLOW_NONE),
    Paradigm("educated_lay", "Educated Lay", "judge_educated_lay", 100, FLOW_PARTIAL),
    Paradigm("traditional", "Traditional LD", "judge_traditional", 150, FLOW_FULL),
    Paradigm("circuit", "Technical Circuit", "judge_circuit", 150, FLOW_FULL),
)

PARADIGMS: Dict[str, Paradigm] = {p.key: p for p in PARADIGM_LIST}
DEFAULT_PARADIGMS: List[str] = [p.key for p in PARADIGM_LIST]

ALL_KEYWORD = "all"


class UnknownParadigm(ValueError):
    """A --personas value that doesn't name a paradigm."""


def valid_persona_names() -> str:
    """The list quoted in Story 3.2's error message."""
    return ", ".join([*DEFAULT_PARADIGMS, ALL_KEYWORD])


def parse_personas(value: str = None) -> List[str]:
    """
    Turn a --personas value into paradigm keys (Story 3.2).

    None or "all" means every paradigm. Unknown names raise with the exact
    message the story specifies.
    """
    if value is None or value.strip().lower() == ALL_KEYWORD:
        return list(DEFAULT_PARADIGMS)

    keys: List[str] = []
    for raw in value.split(","):
        key = raw.strip().lower()
        if not key:
            continue
        if key == ALL_KEYWORD:
            return list(DEFAULT_PARADIGMS)
        if key not in PARADIGMS:
            raise UnknownParadigm(
                f"Unknown persona '{raw.strip()}'. Valid: {valid_persona_names()}."
            )
        if key not in keys:
            keys.append(key)

    if not keys:
        return list(DEFAULT_PARADIGMS)
    # Always judge in registry order, whatever order the flag listed them in.
    return [key for key in DEFAULT_PARADIGMS if key in keys]


def build_system_prompt(key: str) -> str:
    """
    Assemble one persona's system prompt.

    The persona file refers to `prompts/shared/ld_standards.md`; the model can't
    open files, so the standards are appended. Persona text comes first so its
    paradigm framing governs how the shared standards get read.
    """
    paradigm = PARADIGMS.get(key)
    if paradigm is None:
        raise UnknownParadigm(
            f"Unknown persona '{key}'. Valid: {valid_persona_names()}."
        )
    return (
        f"{load_prompt(paradigm.prompt_name).rstrip()}\n\n"
        f"---\n\n"
        f"# APPENDIX — Shared Standards\n\n"
        f"{load_prompt(SHARED_STANDARDS).rstrip()}\n"
    )


def build_system_prompts(keys: Sequence[str]) -> Dict[str, str]:
    return {key: build_system_prompt(key) for key in keys}


# --- The judging pipeline (Stories 3.1, 3.2, 6.2) ----------------------

BALLOT_MAX_TOKENS = 2048
# Some interpretive latitude, but not so much that reruns are unrecognizable.
BALLOT_TEMPERATURE = 0.4

# Paradigms judge concurrently (each still runs its N runs sequentially). The
# calls are I/O-bound Bedrock requests, so a small thread pool turns a full run
# from the sum of every ballot into the slowest single paradigm — ~10min to
# ~90s at N=3. Kept modest so we stay under Bedrock throughput limits; the client
# already retries a transient throttle.
BALLOT_CONCURRENCY = 4

# Each paradigm judges the round this many times; the lean label is derived from
# the split rather than from the model's self-report (Story 4.2, revised
# 2026-08-16). Ten single runs of one paradigm all self-reported "clear" —
# including the two that voted the minority way — so a single run's stated
# confidence carries no information.
DEFAULT_RUNS = 3

LABEL_CLEAR = "clear"
LABEL_SLIGHT = "slight lean"
LABEL_TOSSUP = "toss-up"

AFF = "AFF"
NEG = "NEG"

_WINNER_PATTERN = re.compile(
    r"^[#\s]*\**\s*WINNER\s*\**\s*:?\s*\**\s*(AFF|NEG)",
    re.IGNORECASE | re.MULTILINE,
)
_LEAN_PATTERN = re.compile(
    r"^[#\s]*\**\s*LEAN\s*\**\s*:?\s*\**\s*([a-z][a-z \-]*)",
    re.IGNORECASE | re.MULTILINE,
)


def extract_winner(ballot_text: str) -> Optional[str]:
    """Read the winner off a ballot, tolerating plain, bold, and heading forms."""
    match = _WINNER_PATTERN.search(ballot_text)
    return match.group(1).upper() if match else None


def extract_self_reported_lean(ballot_text: str) -> Optional[str]:
    """The label the model gave itself. Used only to detect a claimed toss-up."""
    match = _LEAN_PATTERN.search(ballot_text)
    return match.group(1).strip().lower() if match else None


def derive_label(winners: Sequence[str], self_leans: Sequence[Optional[str]]) -> str:
    """
    Turn a set of run outcomes into a confidence label (Story 4.2).

    At the default N=3: 3/3 is `clear`, 2/3 is `slight lean`. `strong lean` does
    not exist — the measurement resolution is 1/N, which supports two bands, and
    two measured bands beat four asserted ones.

    A `toss-up` cannot fall out of an odd-N vote share, so it is honoured when the
    model itself says the round is one in most runs.
    """
    valid = [w for w in winners if w]
    if not valid:
        return LABEL_TOSSUP

    claimed_tossup = sum(1 for lean in self_leans if lean and "toss" in lean)
    if claimed_tossup > len(valid) / 2:
        return LABEL_TOSSUP

    tally = Counter(valid).most_common()
    if len(tally) == 1:
        return LABEL_CLEAR
    if tally[0][1] == tally[1][1]:
        return LABEL_TOSSUP  # an even split, only reachable with even N
    return LABEL_SLIGHT


class JudgingError(Exception):
    """Judging failed in a way the user can act on."""


@dataclass
class Ballot:
    """One paradigm's ballot, or the record of its failure."""

    paradigm: str
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_seconds: float = 0.0
    failed: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed

    def usage(self) -> Dict[str, object]:
        """The per-paradigm entry written into metadata.json (Story 6.2)."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "latency_seconds": round(self.latency_seconds, 2),
            "failed": self.failed,
            **({"error": self.error} if self.failed else {}),
        }


@dataclass
class ParadigmVerdict:
    """One paradigm's N runs, collapsed into the decision that gets reported."""

    paradigm: str
    runs: List[Ballot] = field(default_factory=list)

    @property
    def completed(self) -> List[Ballot]:
        return [r for r in self.runs if r.ok and extract_winner(r.text)]

    @property
    def winners(self) -> List[str]:
        return [extract_winner(r.text) for r in self.completed]

    @property
    def winner(self) -> Optional[str]:
        """The majority winner across runs, or None if nothing parsed."""
        if not self.winners:
            return None
        return Counter(self.winners).most_common(1)[0][0]

    @property
    def votes_for_winner(self) -> int:
        return self.winners.count(self.winner) if self.winner else 0

    @property
    def vote_share(self) -> str:
        """e.g. "2/3" — shown alongside the label, being strictly more informative."""
        return f"{self.votes_for_winner}/{len(self.completed)}"

    @property
    def label(self) -> str:
        return derive_label(
            self.winners, [extract_self_reported_lean(r.text) for r in self.completed]
        )

    @property
    def representative(self) -> Optional[Ballot]:
        """
        The ballot shown to the user: the first run that reached the majority
        winner. Synthesizing across runs would cost another model call per
        paradigm, and picking a dissenting run would misrepresent the decision.
        """
        for run in self.completed:
            if extract_winner(run.text) == self.winner:
                return run
        return None

    @property
    def failed(self) -> bool:
        """Every run failed, or none produced a parseable winner."""
        return not self.completed

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def decision(self) -> str:
        """The one-line decision, e.g. "AFF (2/3) slight lean"."""
        if self.failed:
            return "FAILED — no ballot"
        return f"{self.winner} ({self.vote_share}) {self.label}"

    @property
    def input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.runs)

    @property
    def output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.runs)

    @property
    def cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.runs)

    def usage(self) -> Dict[str, object]:
        """The per-paradigm entry in metadata.json (Story 6.2)."""
        return {
            "winner": self.winner,
            "label": self.label,
            "vote_share": self.vote_share,
            "run_winners": self.winners,
            "runs": len(self.runs),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "failed": self.failed,
            **({"errors": [r.error for r in self.runs if r.failed]}
               if any(r.failed for r in self.runs) else {}),
        }

    def provenance_header(self, display_name: str) -> str:
        """Prepended to the saved ballot so the file records how it was decided."""
        return (
            f"<!-- JudgeAI: {display_name} · {self.winner} {self.vote_share} · "
            f"{self.label} · {len(self.runs)} run(s) -->\n\n"
        )


@dataclass
class JudgingResult:
    """Every ballot from one run, plus the totals."""

    verdicts: List[ParadigmVerdict] = field(default_factory=list)
    # The flow pass is one call shared across paradigms *and* across runs, so it is
    # accounted for separately rather than attributed to any single ballot.
    flow_input_tokens: int = 0
    flow_output_tokens: int = 0
    flow_cost_usd: float = 0.0
    # The cross-paradigm diff (Epic 4) is one meta-analysis call over the ballots,
    # accounted for separately like the flow rather than attributed to a paradigm.
    diff_input_tokens: int = 0
    diff_output_tokens: int = 0
    diff_cost_usd: float = 0.0

    @property
    def successful(self) -> List[ParadigmVerdict]:
        return [v for v in self.verdicts if v.ok]

    @property
    def failures(self) -> List[ParadigmVerdict]:
        return [v for v in self.verdicts if v.failed]

    @property
    def input_tokens(self) -> int:
        return (
            sum(v.input_tokens for v in self.verdicts)
            + self.flow_input_tokens
            + self.diff_input_tokens
        )

    @property
    def output_tokens(self) -> int:
        return (
            sum(v.output_tokens for v in self.verdicts)
            + self.flow_output_tokens
            + self.diff_output_tokens
        )

    @property
    def cost_usd(self) -> float:
        return (
            sum(v.cost_usd for v in self.verdicts)
            + self.flow_cost_usd
            + self.diff_cost_usd
        )

    @property
    def unanimous(self) -> bool:
        """Whether every successful paradigm reached the same winner (Story 4.3)."""
        winners = {v.winner for v in self.successful}
        return len(winners) == 1

    def token_usage(self) -> Dict[str, Dict[str, object]]:
        return {v.paradigm: v.usage() for v in self.verdicts}


def cost_line(input_tokens: int, output_tokens: int, cost_usd: float) -> str:
    """Story 6.2's closing total."""
    return (
        f"Total: {input_tokens:,} input + {output_tokens:,} output tokens "
        f"≈ ${cost_usd:.2f}"
    )


def judge_round(
    client,
    structured_transcript: str,
    paradigms: Sequence[str],
    store=None,
    round_id: str = None,
    on_start=None,
    on_run=None,
    on_finish=None,
    flow_text: Optional[str] = None,
    runs: int = DEFAULT_RUNS,
) -> JudgingResult:
    """
    Judge the round with each paradigm, `runs` times each (Technical Spec §7).

    Repetition is not redundancy: the lean label is derived from the split across
    runs, because a single run's self-reported confidence was measured to carry no
    information (Story 4.2). The flow and detection passes are computed once
    upstream and shared, so only the ballots multiply.

    A run that fails is recorded and the remaining runs continue; a paradigm counts
    as failed only when no run produced a parseable winner (Story 3.1). The
    representative ballot is saved as it becomes available, so a crash late in the
    sequence still leaves earlier paradigms on disk.
    """
    result = JudgingResult()
    system_prompts = {key: build_system_prompt(key) for key in paradigms}
    # The callbacks print progress; serialize them so concurrent paradigms don't
    # interleave mid-line. Each line is prefixed with the paradigm name upstream.
    report_lock = threading.Lock()

    def judge_one(key: str) -> ParadigmVerdict:
        paradigm = PARADIGMS[key]
        if on_start:
            with report_lock:
                on_start(paradigm, runs)

        verdict = ParadigmVerdict(paradigm=key)
        user_prompt = build_user_prompt(key, structured_transcript, flow_text)

        for index in range(runs):
            ballot = Ballot(paradigm=key)
            try:
                response = client.invoke(
                    system=system_prompts[key],
                    user=user_prompt,
                    max_tokens=BALLOT_MAX_TOKENS,
                    temperature=BALLOT_TEMPERATURE,
                )
            except Exception as exc:  # noqa: BLE001 — record and keep going
                ballot.failed = True
                ballot.error = str(exc)
            else:
                ballot.text = response.text.strip()
                ballot.input_tokens = response.input_tokens
                ballot.output_tokens = response.output_tokens
                ballot.cost_usd = response.cost_usd
                ballot.latency_seconds = response.latency_seconds

            verdict.runs.append(ballot)
            if on_run:
                with report_lock:
                    on_run(paradigm, index + 1, runs, ballot)

        representative = verdict.representative
        if store is not None and round_id and representative is not None:
            store.save_ballot(
                round_id,
                key,
                verdict.provenance_header(paradigm.display_name) + representative.text,
            )

        if on_finish:
            with report_lock:
                on_finish(paradigm, verdict)
        return verdict

    # Judge paradigms concurrently. pool.map preserves input order, so verdicts
    # land in registry order and the output is identical to a sequential run.
    workers = min(len(paradigms), BALLOT_CONCURRENCY) or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        result.verdicts = list(pool.map(judge_one, paradigms))

    return result


# --- RFD word-cap enforcement -----------------------------------------

# Models format the ballot block with plain labels, bold, or markdown headings,
# so all three have to be accepted. The first real run used "## RFD:" and an
# earlier, stricter pattern matched nothing — reporting a 207-word RFD as being
# within a 60-word cap. A parse failure must never read as a pass.
_RFD_BLOCK = re.compile(
    r"^[#\s]*\**RFD\**\s*:?\s*\n?(?P<body>.*?)"
    r"(?=^[#\s]*\**(?:SPEAKER\s+POINTS|KEY\s+VOTING)\b)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)


class RfdNotFound(Exception):
    """The ballot's RFD block could not be located."""


def extract_rfd(ballot_text: str) -> str:
    """
    Pull the RFD prose out of a ballot, for word-cap checking.

    Raises rather than returning "" so a formatting surprise surfaces instead of
    silently counting zero words and passing every cap.
    """
    match = _RFD_BLOCK.search(ballot_text)
    if not match:
        raise RfdNotFound(
            "Could not locate an RFD block between the RFD label and "
            "SPEAKER POINTS / KEY VOTING ISSUES."
        )
    return re.sub(r"\*+", "", match.group("body")).strip()


def rfd_word_count(ballot_text: str) -> int:
    return len(extract_rfd(ballot_text).split())


def cap_violation(paradigm_key: str, ballot_text: str) -> Optional[str]:
    """
    Report an over-cap RFD.

    The caps are what make Lay (60w) and Circuit (120w) visibly different
    paradigms rather than the same judge in different clothes, so a violation is
    surfaced rather than silently tolerated. The first real run produced a
    290-word Lay RFD.
    """
    paradigm = PARADIGMS.get(paradigm_key)
    if paradigm is None:
        return None
    try:
        words = rfd_word_count(ballot_text)
    except RfdNotFound as exc:
        return f"{paradigm.display_name} ballot format unrecognized: {exc}"
    if words <= paradigm.rfd_word_cap:
        return None
    return (
        f"{paradigm.display_name} RFD is {words} words, cap is "
        f"{paradigm.rfd_word_cap}."
    )


# --- The flow pass (PRD 5-pass pipeline, restored 2026-08-15) -----------

FLOW_FRAMING = {
    FLOW_FULL: (
        "A flow of this round has already been taken. Treat it as authoritative "
        "about what was said and what went unanswered:"
    ),
    FLOW_PARTIAL: (
        "Below are your own notes from the round. They are more organized than what "
        "you actually wrote, but they are still notes, not a trained flow: where "
        "they say an argument was DROPPED, what you can honestly say is that you "
        "did not record an answer — not that none was formally made. Rely on what "
        "you observed, and say where your notes were thin:"
    ),
}


def extract_flow(client, structured_transcript: str) -> "ModelResponse":
    """
    Pass 1: enumerate frameworks, answers, drops, evidence turns, and preclusion
    arguments as data, before any judging.

    Measured effect (2026-08-15, nuclear round with a known human ballot):
    single-pass judging returned the wrong winner on 4 of 4 paradigms; with this
    pass first, Technical Circuit returned the human-matching winner on 3 of 3
    runs, leading with the evidence turn the expert led with. One flow is shared
    across every paradigm that is allowed to see it, so it costs one call per
    round, not one per persona.
    """
    return client.invoke(
        system=load_prompt(FLOW_PROMPT),
        user=structured_transcript,
        max_tokens=FLOW_MAX_TOKENS,
        temperature=FLOW_TEMPERATURE,
    )


def needs_flow(paradigms: Sequence[str]) -> bool:
    """Whether any selected paradigm is permitted a flow."""
    return any(
        PARADIGMS[key].flow_access != FLOW_NONE for key in paradigms if key in PARADIGMS
    )


# --- The cross-paradigm diff (Epic 4, Story 4.1) -----------------------

DIFF_PROMPT = "cross_persona_diff"
DIFF_MAX_TOKENS = 1500
# Synthesis, not judgment: low temperature keeps the diff faithful to the ballots.
DIFF_TEMPERATURE = 0.2


def diff_decision_line(verdict: ParadigmVerdict) -> str:
    """
    The exact decision string the diff must reproduce, label-first to match the
    §4.6 format: e.g. "slight lean AFF (2/3)", "clear AFF (3/3)".
    """
    return f"{verdict.label} {verdict.winner} ({verdict.vote_share})"


def build_diff_input(
    round_id: str,
    date: str,
    resolution: Optional[str],
    aff: str,
    neg: str,
    result: JudgingResult,
) -> str:
    """
    Assemble the meta-analysis input: the round header, an all-agree note when the
    paradigms are unanimous, and each successful paradigm's exact decision line
    plus its representative ballot. The winner/share/label are computed here and
    handed to the model verbatim so the diff can never re-decide the round.
    """
    lines = [
        "## ROUND",
        f"Round: {round_id} ({date})",
        f'Resolution: "{resolution}"' if resolution else "Resolution: (none stated)",
        f"Aff: {aff} | Neg: {neg}",
    ]
    if result.successful and result.unanimous:
        lines += [
            "",
            "NOTE: Every paradigm below reached the SAME winner (a blowout). Use "
            "the all-agree line for the PRIMARY FLIP POINT.",
        ]
    lines += [
        "",
        "## PER-PARADIGM BALLOTS",
        "Reproduce each `DECISION (use verbatim):` line exactly; write only the "
        "reasons and flip points.",
    ]
    for verdict in result.verdicts:
        paradigm = PARADIGMS[verdict.paradigm]
        if verdict.failed:
            # Story 4.3: a failed paradigm still appears, marked, but carries no
            # ballot and is excluded from the flip point / win-lose summary.
            lines += [
                "",
                f"### {paradigm.display_name}",
                f"DECISION (use verbatim): {paradigm.display_name}: "
                f"[FAILED — no ballot]",
            ]
            continue
        lines += [
            "",
            f"### {paradigm.display_name}",
            f"DECISION (use verbatim): {paradigm.display_name}: "
            f"{diff_decision_line(verdict)}",
            "",
            verdict.representative.text.strip(),
        ]
    return "\n".join(lines)


def generate_diff(
    client,
    round_id: str,
    date: str,
    resolution: Optional[str],
    aff: str,
    neg: str,
    result: JudgingResult,
) -> "ModelResponse":
    """Pass 3: one call that turns the ballots into the compact §4.6 diff."""
    return client.invoke(
        system=load_prompt(DIFF_PROMPT),
        user=build_diff_input(round_id, date, resolution, aff, neg, result),
        max_tokens=DIFF_MAX_TOKENS,
        temperature=DIFF_TEMPERATURE,
    )


def build_user_prompt(
    key: str, structured_transcript: str, flow_text: Optional[str] = None
) -> str:
    """
    Assemble one paradigm's user prompt, attaching the flow only if permitted.

    A lay parent took no notes, so giving them a flow would make them a different
    judge entirely — the flow is withheld rather than filtered.
    """
    paradigm = PARADIGMS[key]
    if not flow_text or paradigm.flow_access == FLOW_NONE:
        return structured_transcript
    return (
        f"{structured_transcript}\n\n---\n\n"
        f"{FLOW_FRAMING[paradigm.flow_access]}\n\n{flow_text}\n\n---\n\n"
        f"Now judge the round, applying your decision procedure."
    )
