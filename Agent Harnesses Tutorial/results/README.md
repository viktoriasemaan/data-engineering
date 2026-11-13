# Results from the video

15 graded runs, measured through Unity Gateway (`system.ai_gateway.usage`) and priced at Databricks list prices.
Every run passed all 7 hidden tests.

## Same model for all three: Kimi K3 (3 runs each)

| Harness | Avg time | Avg model calls | Avg prompt tokens | Read from cache | Avg cost per task | Range |
|---|---|---|---|---|---|---|
| Claude Code | 43 s | 7.7 | 112,549 | 82% | $0.144 | $0.117 to $0.175 |
| Codex | 65 s | 12.0 | 161,647 | 91% | $0.172 | $0.122 to $0.200 |
| Hermes Agent | 72 s | 10.7 | 162,945 | 84% | $0.187 | $0.127 to $0.246 |

## Each harness on its own model (2 runs each)

| Harness | Model | Avg time | Avg model calls | Read from cache | Avg cost per task |
|---|---|---|---|---|---|
| Claude Code | Claude Opus 5.5 | 27 s | 3.5 | 57% | $0.204 |
| Codex | GPT-6.1 Sol | 35 s | 5.5 | 78% | $0.068 |
| Hermes Agent | Claude Opus 5.5 | 36 s | 6.0 | 0% | $0.486 |

## The cost of hello (one prompt: "Reply with exactly: ok", Kimi K3)

| Harness | Prompt tokens |
|---|---|
| Codex | 7,849 |
| Claude Code | 10,567 |
| Hermes Agent | 11,748 |

## Read these numbers as a method

One task, 2 or 3 runs per pair, list prices. Ranges overlap on Kimi K3, so Claude Code was a little cheaper there,
not a clear winner. Anthropic doesn't officially support non-Claude models in Claude Code.
Run `scripts/run_all.sh` on your own repo and compare cost per solved task, not price per token.
