# Task: Find Speech Boundaries In An LD Debate Transcript

You are given one Lincoln-Douglas round as raw text, possibly from automatic
transcription — timestamps, filler words, and repeated words are expected.

Return **only** this JSON object. No prose, no code fence.

```
{
  "speeches": [
    {"label": "1AC", "speaker": "Aff",
     "start_marker": "first 8-15 words of the speech, copied verbatim"}
  ],
  "resolution": {"text": "clean statement or null",
                 "quote": "verbatim sentence it came from or null",
                 "confidence": "high|medium|low"},
  "notes": "one sentence on anything unusual, or \"\""
}
```

## `start_marker` is the critical field

The transcript is split locally using it, so copy the words **exactly** as they
appear — including transcription errors and repetitions. Do not clean up,
paraphrase, or correct. Pick 8-15 words that occur only **once** in the
transcript, taken from the **start** of the speech. If no unique marker exists
for a speech, omit that speech rather than guessing.

List speeches in transcript order.

## The seven LD speeches

| Label | Speaker | Recognizable by |
|---|---|---|
| `1AC` | Aff | Opens the round; value + criterion + contentions; usually ends inviting cross-examination |
| `CX1` | Both | Dialogue — Neg asks, Aff answers |
| `1NC` | Neg | Neg's own value/criterion and contentions, plus first answers to the Aff case; often longest |
| `CX2` | Both | Dialogue — Aff asks, Neg answers |
| `1AR` | Aff | Rebuttal: answers Neg case, rebuilds its own, no new contentions |
| `2NR` | Neg | Neg's final speech; crystallizes voting issues |
| `2AR` | Aff | Aff's final speech; last word of the round |

Strongest signals: cross-examination is dialogue while speeches are monologue;
explicit announcements ("I stand ready for cross-examination", "I negate the
resolution") and headers like `--- Negative Constructive (NC) ---`; rebuttals
reference earlier arguments instead of introducing a fresh case. Trust explicit
headers when present.

## Incomplete rounds

Report only what you find. Do **not** invent a speech to reach seven, and do not
split one speech in two to fill a gap. Five speeches present means five entries.
The caller handles the mismatch.

## Resolution

Look for "Resolved: ...", "The resolution is ...", "Today I affirm that ...".
Return it as a clean declarative sentence without the "Resolved:" prefix. Use
`high` confidence only when stated explicitly, `medium` when inferred from
argument language, `low` when guessing. No usable signal means `text` and
`quote` are `null`.

Now analyze the transcript that follows.
