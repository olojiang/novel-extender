#!/usr/bin/env bash
set -euo pipefail

# Copy-paste tutorial commands for novel-extender.
# Run from the project root:
#   cd /Users/hunter/Workspace/novel-extender
#   bash examples/tutorial_commands.sh
#
# The model endpoint must be local or private-network. Public endpoints are
# rejected by the application.

export NOVEL_BASE_URL="${NOVEL_BASE_URL:-http://127.0.0.1:1234/v1}"
export NOVEL_CHAT_MODEL="${NOVEL_CHAT_MODEL:-qwen3.5-9b-uncensored-hauhaucs-aggressive-mlx}"
export NOVEL_EMBEDDING_MODEL="${NOVEL_EMBEDDING_MODEL:-text-embedding-bge-large-zh-v1.5}"

export NOVEL="${NOVEL:-tutorial}"
export NOVEL_FILE="${NOVEL_FILE:-examples/novel.txt}"
export NOVEL_COLLECTION="${NOVEL_COLLECTION:-${NOVEL}_chapters}"
export NOVEL_DB_PATH="${NOVEL_DB_PATH:-.novel_extender/${NOVEL}_chroma}"
export NOVEL_OUT_DIR="${NOVEL_OUT_DIR:-.novel_extender/${NOVEL}_outputs}"
export NOVEL_LOG_DIR="${NOVEL_LOG_DIR:-${NOVEL_OUT_DIR}/logs}"

echo "== Sample novel =="
sed -n '1,120p' "$NOVEL_FILE"

echo
echo "== Validate local models =="
uv run novel-extender validate-openai \
  --base-url "$NOVEL_BASE_URL" \
  --chat-model "$NOVEL_CHAT_MODEL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL"

echo
echo "== Reset tutorial workspace =="
rm -rf "$NOVEL_DB_PATH" "$NOVEL_OUT_DIR"
mkdir -p "$NOVEL_OUT_DIR" "$NOVEL_LOG_DIR"

echo
echo "== Ingest sample novel =="
uv run novel-extender ingest "$NOVEL_FILE" \
  --base-url "$NOVEL_BASE_URL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --log-dir "$NOVEL_LOG_DIR"

echo
echo "== Retrieve relevant chapters =="
uv run novel-extender retrieve "旧徽章 北楼 档案" \
  --base-url "$NOVEL_BASE_URL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 3

echo
echo "== Build analysis prompt =="
uv run novel-extender build-context "$NOVEL_FILE" \
  "分析旧徽章、北楼、失踪学生档案三条线索之间的关系，指出已有伏笔和下一步可推进方向。" \
  --base-url "$NOVEL_BASE_URL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 3 \
  --recent-count 3 \
  --mode analysis \
  > "$NOVEL_OUT_DIR/analysis_prompt.txt"

echo "Wrote $NOVEL_OUT_DIR/analysis_prompt.txt"

echo
echo "== Generate continuation =="
uv run novel-extender generate "$NOVEL_FILE" \
  "续写下一章：林澈进入北楼第三层，发现旧徽章会回应档案里的名字。保持悬疑节奏，不要提前揭示幕后人。" \
  --base-url "$NOVEL_BASE_URL" \
  --chat-model "$NOVEL_CHAT_MODEL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 3 \
  --recent-count 3 \
  --mode continuation \
  --log-dir "$NOVEL_LOG_DIR" \
  --prompt-output "$NOVEL_OUT_DIR/continuation_prompt.txt" \
  --output "$NOVEL_OUT_DIR/continuation.md"

echo "Wrote $NOVEL_OUT_DIR/continuation.md"

echo
echo "== Generate rewrite =="
uv run novel-extender generate "$NOVEL_FILE" \
  "改写第2章：让沈月的提醒更有压迫感，减少说明性文字，保留星纹、北楼和十年前档案三项信息。" \
  --base-url "$NOVEL_BASE_URL" \
  --chat-model "$NOVEL_CHAT_MODEL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 3 \
  --recent-count 3 \
  --mode rewrite \
  --log-dir "$NOVEL_LOG_DIR" \
  --prompt-output "$NOVEL_OUT_DIR/rewrite_prompt.txt" \
  --output "$NOVEL_OUT_DIR/rewrite.md"

echo "Wrote $NOVEL_OUT_DIR/rewrite.md"

echo
echo "== Output files =="
ls -1 "$NOVEL_OUT_DIR"

echo
echo "Generated text is in $NOVEL_OUT_DIR/continuation.md and $NOVEL_OUT_DIR/rewrite.md"
