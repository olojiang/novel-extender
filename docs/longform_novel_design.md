# Longform Novel Rewrite and Continuation Design

## Goal

Build a local-first tool for long novels that can:

- split source text by chapters;
- store chapter-level memory in Chroma;
- retrieve relevant prior chapters for rewrite or continuation;
- assemble auditable prompts for planning, rewriting, and continuation;
- log each processing step with enough detail to debug failures.

## Architecture

```
source novel
  -> chapter splitter
  -> chapter metadata
  -> embedding model
  -> Chroma collection
  -> retrieval
  -> source-path isolation
  -> context assembler
  -> outline prompt
  -> rewrite / continuation prompt
  -> post-generation checks and memory update
```

## Chapter Segmentation

The first segmentation unit is the chapter, not fixed-size chunks. A chapter keeps:

- `chapter_id`;
- chapter index;
- title;
- text;
- character count;
- source path.

Later versions can add scene/chunk segmentation inside chapters, but chapter identity remains the stable parent key.

## Memory Model

MVP Chroma documents are chapter records:

- document: full chapter text;
- id: stable chapter id;
- metadata: title, index, source path, char count.

Retrieval must filter by `source_path` when a source novel is known. This prevents records from another
novel in the same collection from entering the prompt. The recommended operational model is still one
database directory and collection per novel.

Future layers:

- chapter summaries;
- volume and whole-book summaries;
- character/location/foreshadowing tables;
- rewrite alignment records mapping source chapter/paragraph to rewritten output.

## Retrieval Strategy

Continuation and rewrite context combines:

- latest N chapters by index;
- top K semantically related chapters from Chroma;
- user task requirements;
- global style/rules;
- mode-specific constraints.

The design intentionally does not rely only on vector similarity. Recency is injected explicitly so continuity is preserved.

## Generation Strategy

Continuation is a two-step workflow:

1. Generate a chapter outline with scene goals, conflicts, information changes, and ending hook.
2. Generate prose from the outline and retrieved memory.

Rewrite is a three-step workflow:

1. Extract required facts from the source segment.
2. Rewrite while preserving facts, relationships, timeline, and foreshadowing.
3. Compare source and rewrite for omissions, meaning changes, and premature reveals.

The implemented post-generation layer currently performs baseline validation and can write generated
chapters back to the same Chroma collection. Deeper semantic checks such as contradiction detection and
paragraph-level rewrite alignment remain future layers.

## Web Workbench

The web surface is a local operator console, not a hosted service. It uses:

- Python stdlib HTTP API in `novel_extender.web_api`;
- Vue + TypeScript + Vite frontend under `web/`;
- Vitest for frontend helper coverage;
- ESLint for frontend static checks.

The browser cannot reliably pass local absolute file paths to the backend. The UI therefore uploads the
selected text to `.novel_extender/web_inputs/`, receives isolated paths from the API, and then runs the
same ingest/retrieve/context/generate workflow as the CLI.

## Logging

All workflows use structured JSONL logs under `logs/` by default. Each event includes:

- timestamp;
- run id;
- stage;
- event name;
- input/output identifiers;
- counts;
- success/failure status;
- diagnostic details.

The logs are designed for iteration: when an ingest, retrieval, or generation step fails, the next debugging step should be visible without re-running blindly.

## TDD Acceptance Criteria

- chapter splitter recognizes common Chinese chapter headings;
- Chroma store can upsert chapter documents with supplied embeddings;
- retrieval returns chapter records and metadata;
- context assembly includes recent chapters and retrieved chapters;
- CLI emits logs for successful workflows;
- existing OpenAI compatibility validation keeps passing.
