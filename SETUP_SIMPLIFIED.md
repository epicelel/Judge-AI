# JudgeAI Quick Setup Guide

## 3 Simple Steps

### 1. Get an API Key

**Option A: Anthropic (Recommended)**
- Go to: https://console.anthropic.com/
- Sign up and get API key
- Cost: $3/$15 per 1M tokens (~$0.75 per round)

**Option B: OpenAI**
- Go to: https://platform.openai.com/api-keys
- Sign up and get API key  
- Cost: $10/$30 per 1M tokens (~$2-3 per round)

**💡 Pro Tip:** Get BOTH for automatic fallback!

### 2. Enter in App

1. Double-click **JudgeAI.app** on Desktop
2. Click **⚙️ Settings**
3. Enter your API key(s)
4. Click **Save**

**That's it!** Keys are saved permanently.

### 3. Judge Rounds

1. Drag transcript file onto app
2. Wait 2-4 minutes
3. View results!

---

## Automatic Fallback

**Set BOTH API keys for zero downtime:**

When Anthropic hits rate limits → Automatically switches to OpenAI → Keeps judging!

**Status badge shows:**
- **Green:** Single provider ready
- **Blue:** Auto-fallback active (both keys configured)

---

## Cost Comparison

**Typical round (N=3, 4 paradigms):**
- Anthropic: $0.75-0.80
- OpenAI: $2.00-3.00

**Heavy usage (20 rounds/day):**
- Anthropic: $15-16/day
- OpenAI: $40-60/day

---

## FAQ

**Q: Do I need both providers?**
A: No - one works fine. Two enables automatic fallback.

**Q: Which is better?**
A: Anthropic is cheaper and recommended. OpenAI is good backup.

**Q: What about AWS Bedrock?**
A: Removed - too complex. Use Anthropic or OpenAI.

**Q: Are my keys secure?**
A: Yes - saved locally in ~/.judgeai/config.json (never sent elsewhere)

**Q: Rate limits?**
A: Anthropic: ~50 requests/min. OpenAI: varies by tier.

**Q: What if I hit rate limits?**
A: With auto-fallback, it switches automatically. Otherwise, wait 1-5 minutes.

---

**That's it! Simple, fast, and reliable.** 🎉
