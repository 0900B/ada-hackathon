# CLAUDE.md — Permanent project rules

## Design rules

- Minimal, professional operations-software look. Must not look AI-generated.
- No emojis, gradients, shadows, glow, decorative icons, or animations.
- No chat interface of any kind: no message bubbles, no avatars, no typing indicators,
  no "AI assistant" labels, no sparkle icons, no "Ask AI" buttons.
- AI output is shown as a plain structured block (e.g. "RECOMMENDATION" label, short
  factual text, Approve button), like a line in an operations report.
- No rounded cards, no pill-shaped badges, no large rounded buttons. Corners max 2px.
- Light theme: white/neutral greys, black text, thin 1px borders (#e5e5e5).
- Colour only for meaning, muted:
  - free        #2f7d4f
  - on mission  #b26b00
  - high priority #b3261e
  - medium priority #8a7a00
  - hospital    #1f3a5f
- Typography: Inter or system sans-serif; small uppercase labels with letter spacing;
  monospace for IDs and times.
- When in doubt, remove rather than add.

## Project rules

- Frontend in `client/`, backend in `server/`.
  (The `frontend/` and `backend/` directories are the original prototype; don't touch them
  unless asked.)
- Never commit secrets (.env). Commit and push after each working step.
- Keep code simple and commented; explain briefly what was done in each response.
