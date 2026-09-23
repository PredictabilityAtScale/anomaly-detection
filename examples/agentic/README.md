# Agentic evidence examples

Run all four examples from the repository root:

```powershell
.venv/Scripts/python examples/run_agentic_demo.py
```

Each example has a human-readable CSV and a canonical schema-1.1 JSON request.
`expected.json` checks only stable semantic output; run IDs and timings are
intentionally excluded.

| Example | Evidence | Bounded conclusion | Not established |
| --- | --- | --- | --- |
| `conversion` | `orders / qualified_visits` triggers at sample 14 while neither source series triggers | The declared conversion relationship met the calibrated departure criterion; inspect checkout errors, traffic mix, and experiments | A checkout failure or any other cause |
| `lagged-response` | `orders[t] - 2 * qualified_leads[t-2]` triggers at sample 11 | The reviewed lag/coefficient expectation failed; inspect source mix, processing delay, and ingestion | That leads cause orders or that the lag is universally stable |
| `unit-cost` | `infrastructure_cost / successful_requests` crosses the explicit 0.13 rule at sample 3 | The exact rule was violated and policy permits investigation | Financial materiality, incident status, or cause |
| `incomplete-usage` | The final completeness input is explicitly incomplete, so joint evidence is unavailable | Check ingestion before interpreting the apparent usage drop | Normal health or a genuine customer usage collapse |

The prompts an agent should act on are the investigation questions above, not
instructions to declare incidents. Source and relationship evidence may be
correlated and must not be counted as independent confirmation.
