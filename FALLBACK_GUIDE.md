# Automatic API Fallback Guide

## What Is It?

When you configure **both** Anthropic and OpenAI API keys, JudgeAI automatically switches between them when rate limits are hit. Zero downtime, seamless switching.

## How to Enable

**Just set both API keys:**

```bash
export ANTHROPIC_API_KEY='sk-ant-...'
export OPENAI_API_KEY='sk-...'
```

That's it! Auto-fallback is now active.

## How It Works

### Fallback Chain

```
Anthropic API → OpenAI API
```

**When a rate limit is hit:**
1. Immediately switches to next provider (no retry delay)
2. Continues judging without interruption
3. Shows current provider in status badge

**For other errors:**
- Retries with same provider first
- Falls back to next provider if retries fail

### Status Badge

**Single Provider:**
```
● Anthropic API        (green badge)
```

**Auto-Fallback Enabled:**
```
● Auto-Fallback: Anthropic API    (blue badge)
```

**Hover over badge to see:**
```
Auto-switching enabled
Fallback chain: Anthropic API → OpenAI API
Switches automatically on rate limits
```

## Example Scenarios

### Scenario 1: Heavy Usage Day

You're judging many rounds in a row:

1. **Rounds 1-20:** Uses Anthropic API ✓
2. **Round 21:** Anthropic hits rate limit
3. **Auto-switch:** → OpenAI API ✓
4. **Rounds 22-40:** Uses OpenAI API ✓
5. **Later:** Anthropic available again
6. **Auto-switch back:** → Anthropic API ✓

**Result:** No interruption, all 40 rounds completed!

### Scenario 2: API Outage

One provider has an outage:

1. **Primary:** Anthropic API down
2. **Auto-switch:** → OpenAI API ✓
3. **Judging continues** with backup provider

### Scenario 3: Cost Optimization

Want to prefer cheaper provider?

Set cheaper provider first in fallback chain by controlling API key order. The system tries providers in this order:
1. Anthropic (if key present)
2. OpenAI (if key present)

## Detected Rate Limit Errors

Auto-switches on these error patterns:

- `rate limit`
- `rate_limit_exceeded`
- `ratelimit`
- `too many requests`
- `HTTP 429`
- `quota exceeded`
- `overloaded`

## Logging

Provider switches are logged to `judgeai.log`:

```
2026-09-12 21:45:12 INFO judgeai.fallback: Attempting call with provider: Anthropic API
2026-09-12 21:45:15 WARNING judgeai.fallback: Rate limit hit on Anthropic API, trying next provider
2026-09-12 21:45:16 INFO judgeai.fallback: Switched to provider: OpenAI API
```

## Configuration Options

### Enable/Disable

**Auto-enabled when:**
- Both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are set
- No specific `LLM_PROVIDER` is set

**Force specific provider:**
```bash
export LLM_PROVIDER=anthropic  # Only use Anthropic (no fallback)
```

### Single Provider Mode

**Use only one provider:**
```bash
# Set only one API key
export ANTHROPIC_API_KEY='sk-ant-...'
# Don't set OPENAI_API_KEY

# Or force a specific provider
export LLM_PROVIDER=anthropic
```

## Benefits

### 1. Zero Downtime
Never get stopped mid-judging by rate limits

### 2. Continuous Operation
Judge as many rounds as you need

### 3. Cost Optimization
- Primary: Anthropic (cheaper: $3/$15 per 1M tokens)
- Backup: OpenAI (more expensive: $10/$30)
- Use cheaper when available, fall back when needed

### 4. API Outage Protection
If one provider is down, automatically use another

### 5. Seamless Experience
- No manual intervention needed
- Transparent switching
- Status badge shows current provider

## Best Practices

### For Heavy Usage

```bash
# Set both keys for maximum reliability
export ANTHROPIC_API_KEY='...'
export OPENAI_API_KEY='...'
```

### For Cost Control

1. Monitor which provider is being used (check status badge)
2. If using expensive provider too much, wait for rate limits to reset
3. Consider higher tier API plans if needed

### For Testing

```bash
# Test with both providers
export ANTHROPIC_API_KEY='...'
export OPENAI_API_KEY='...'

# Watch status badge change colors:
# Green → Single provider
# Blue → Auto-fallback active
```

## FAQ

**Q: Does it cost more?**
A: No extra cost. You only pay for the API calls actually made.

**Q: Which provider does it prefer?**
A: Tries Anthropic first (cheaper), then OpenAI.

**Q: Can I change the order?**
A: The order is fixed: Anthropic → OpenAI. To use only one, set only that API key.

**Q: Does it switch back?**
A: Yes! Next round tries the primary provider again.

**Q: How fast is the switch?**
A: Immediate - no retry delay on rate limit errors.

**Q: Do I need both keys?**
A: No - but having both enables auto-fallback. One key works fine (single provider mode).

**Q: Will my rounds cost different amounts?**
A: Yes - Anthropic costs $0.75/round, OpenAI costs $2-3/round (N=3 runs, 4 paradigms).

## Technical Details

### Error Detection

Rate limits detected by checking error messages for keywords:
- "rate limit" / "rate_limit" / "ratelimit"
- "too many requests"
- "429" (HTTP status code)
- "quota exceeded"
- "overloaded"

### Retry Logic

**Rate limit errors:**
- No retry
- Immediate fallback to next provider

**Other errors:**
- Retry with same provider (default: 1 retry, 5s backoff)
- Fall back to next provider if all retries fail

### Provider Chain

Built automatically based on available credentials:

```python
if ANTHROPIC_API_KEY:
    add AnthropicAPIClient
if OPENAI_API_KEY:
    add OpenAIClient

if multiple providers:
    return FallbackClient(all_providers)
else:
    return single_provider
```

---

**Automatic fallback makes JudgeAI more reliable and ensures continuous operation even during heavy usage!**
