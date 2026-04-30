# novel-extender

Python tools for validating local OpenAI-compatible models and running novel extension workflows.

This project is local-first. By default it only connects to a local OpenAI-compatible endpoint at
`http://127.0.0.1:1234/v1`, uses a local embedding model for retrieval, and stores vectors in a local
Chroma database. Public model endpoints such as `https://api.openai.com/v1` are rejected by the code.

For a copy-paste tutorial, see [docs/tutorial_zh.md](docs/tutorial_zh.md). For the broader Chinese guide,
see [docs/usage_zh.md](docs/usage_zh.md). For task wording examples, see
[examples/request_samples.md](examples/request_samples.md).

## Web Workbench

The local web workbench wraps the same Python workflow in a Vue + TypeScript + Vite UI.

Install the frontend once:

```bash
cd web
pnpm install
```

Run the API and Vite dev server in two terminals:

```bash
uv run novel-extender-web
```

```bash
cd web
pnpm dev
```

Open the Vite URL printed by `pnpm dev`. The UI supports selecting a text/Markdown novel,
preparing an isolated Chroma path and collection, ingesting, testing retrieval, building the prompt,
and generating analysis, continuation, or rewrite output. Browser directory saving is available when
the browser supports the File System Access API; otherwise use the backend output directory field.

To serve the built frontend from the Python process:

```bash
cd web
pnpm build
cd ..
uv run novel-extender-web
```

## Validate Local Models

Default endpoint:

```bash
uv run novel-extender validate-openai
```

Override models:

```bash
uv run novel-extender validate-openai \
  --base-url http://127.0.0.1:1234/v1 \
  --chat-model qwen3.5-9b-uncensored-hauhaucs-aggressive-mlx \
  --embedding-model text-embedding-bge-large-zh-v1.5
```

## Ingest A Novel Into Chroma

```bash
export NOVEL="tutorial"
export NOVEL_FILE="examples/novel.txt"
export NOVEL_COLLECTION="${NOVEL}_chapters"
export NOVEL_DB_PATH=".novel_extender/${NOVEL}_chroma"
export NOVEL_OUT_DIR=".novel_extender/${NOVEL}_outputs"
export NOVEL_LOG_DIR="${NOVEL_OUT_DIR}/logs"
mkdir -p "$NOVEL_OUT_DIR" "$NOVEL_LOG_DIR"

uv run novel-extender ingest "$NOVEL_FILE" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --log-dir "$NOVEL_LOG_DIR"
```

## Retrieve Relevant Chapters

```bash
uv run novel-extender retrieve "旧徽章 北楼 线索" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 2
```

## Build Continuation Context

```bash
uv run novel-extender build-context "$NOVEL_FILE" "续写下一章，重点写北楼档案和旧徽章的联系。" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 2 \
  --mode continuation
```

Other prompt modes:

```bash
uv run novel-extender build-context "$NOVEL_FILE" "分析主角、北楼、旧徽章三条线索之间的关系。" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --mode analysis

uv run novel-extender build-context "$NOVEL_FILE" "改写第2章，让节奏更紧，但保留旧徽章和档案线索。" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --mode rewrite
```

## Generate Text

`build-context` prints the assembled prompt for inspection. `generate` runs the same retrieval and prompt
assembly, calls the local chat model, and writes the generated text:

```bash
uv run novel-extender generate "$NOVEL_FILE" "续写下一章，重点写北楼档案和旧徽章的联系。" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --mode continuation \
  --log-dir "$NOVEL_LOG_DIR" \
  --update-memory \
  --output "$NOVEL_OUT_DIR/next_chapter.md"

uv run novel-extender generate "$NOVEL_FILE" "改写第2章，让节奏更紧，但保留旧徽章和档案线索。" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --mode rewrite \
  --log-dir "$NOVEL_LOG_DIR" \
  --output "$NOVEL_OUT_DIR/rewrite_chapter_2.md"
```
