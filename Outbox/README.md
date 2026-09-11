# Outbox — authored artifacts

Original work produced in this knowledge repository (drafts, proposals, exports) — as opposed to
imported source material, which lives in `../Literature/`.

## Contents

- `knowledge-garden/` — design proposal for a cloud-hosted, MCP-accessible version of this
  knowledge repository at Celonis:
  - `design-proposal.md`
- `pql-sql-text2sql-improvements/` — findings from garden search + Slack
  (`query_perspective` / human-parity PQL errors) mapped to Text-to-SQL
  literature; annotated `sources.md` of held papers and internal PQL/Prisma:
  - `findings.md` — eight skill/eval/language-service changes
  - `sources.md` — annotated collection (external + internal + Slack)
  - `papers/` / `papers.zip` — 29 external paper copies (no internal files)
- `agentic-sql-reliability/` — enterprise Text-to-SQL / PQL agent failure modes
  and Studio MCP tool gates (Stonebraker/Wenz, Bauplan, SQL HCI, internal Prisma):
  - `synthesis.md` — evidence → concrete gates (schema-before-query,
    probe-before-generate, 403≠generation, pipeline vs transformation)
  - `README.md` — acquisition map (`gap-agentic-sql.py`, `stonebraker-cacm`,
    `bauplan-papers.py`, gap topic `agentic-sql-reliability`)
- `thesis/` — agent-in-the-loop thesis proposals and drafts:
  - `agent-in-the-loop-oer-discovery-thesis-proposal.md`
  - `agent-in-the-loop-process-discovery-thesis-draft.md`
  - `agent-in-the-loop-process-discovery-related-work.md`
  - `related-work-section-for-original-proposal.md`
- `thesis-agent-in-the-loop-discovery/` — curated external source collection for the
  *Agent in the Loop Process Discovery* proposal, drawn from the search index rather than
  harvested, with Celonis-internal material excluded by construction:
  - `sources.md` — 144 annotated works in eight themes, plus the recorded gaps
  - `manifest.json` / `build.py` — the editorial input and the renderer
  - `external-sources.zip` — the same works as files, renamed from indexed metadata
