Use after writing a plan to file and ready for user approval. Reads the plan file and presents it to the user for review.

Only use for implementation tasks that need planning, not for research.

If your plan has multiple approaches, pass them via `options`:
- Provide 2–3 options max (the system adds "Reject" automatically).
- Each needs a concise label and brief trade-off description.
- Append "(Recommended)" to your preferred option.
- Do NOT use "Reject", "Revise", or "Approve" as labels.

Before using, resolve open questions. If you have multiple un-narrowed approaches, let the user choose via `AskUserQuestion` first. Do NOT use `AskUserQuestion` to ask "Is this plan OK?". If rejected, revise and call `ExitPlanMode` again.
