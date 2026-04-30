# 10 分钟复制执行教程

这是一条“先跑起来，再理解”的路线。你会用项目自带的 `examples/novel.txt`，完整体验：

- 验证本地模型；
- 导入小说；
- 检索相关章节；
- 生成分析提示词；
- 直接生成续写；
- 直接生成改写章节；
- 确认不会使用公网模型地址。

下面的命令都在项目根目录执行：

```bash
cd /Users/hunter/Workspace/novel-extender
```

## 0. 前置条件

先启动你的本地 OpenAI-compatible 模型服务。默认教程假设：

```text
服务地址: http://127.0.0.1:1234/v1
chat 模型: qwen3.5-9b-uncensored-hauhaucs-aggressive-mlx
embedding 模型: text-embedding-bge-large-zh-v1.5
```

如果你的模型名、小说文件或隔离名不同，只改这一段。后面的命令可以直接复制执行，不需要再改路径：

```bash
export NOVEL_BASE_URL="http://127.0.0.1:1234/v1"
export NOVEL_CHAT_MODEL="qwen3.5-9b-uncensored-hauhaucs-aggressive-mlx"
export NOVEL_EMBEDDING_MODEL="text-embedding-bge-large-zh-v1.5"

export NOVEL="tutorial"
export NOVEL_FILE="examples/novel.txt"
export NOVEL_COLLECTION="${NOVEL}_chapters"
export NOVEL_DB_PATH=".novel_extender/${NOVEL}_chroma"
export NOVEL_OUT_DIR=".novel_extender/${NOVEL}_outputs"
export NOVEL_LOG_DIR="${NOVEL_OUT_DIR}/logs"
```

隔离规则是：同一个 `NOVEL` 名对应一套独立的 Chroma 目录、输出目录、日志目录和 collection。比如 `NOVEL=book_a` 会使用 `.novel_extender/book_a_chroma` 和 `.novel_extender/book_a_outputs`。

## 1. 看一眼样例小说

```bash
sed -n '1,120p' "$NOVEL_FILE"
```

你会看到 3 章短小说，包含这些线索：

- 星城学院；
- 父亲留下的旧徽章；
- 北楼；
- 十年前失踪学生的档案。

## 2. 验证本地模型

```bash
uv run novel-extender validate-openai \
  --base-url "$NOVEL_BASE_URL" \
  --chat-model "$NOVEL_CHAT_MODEL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL"
```

成功时你会看到类似结果：

```text
Base URL: http://127.0.0.1:1234/v1
Available models:
  - ...

Chat model: ...
  Status: OK
  Reason: listed and chat completion probe succeeded
Embedding model: ...
  Status: OK
  Reason: listed and embedding probe succeeded
```

如果这里失败，先处理本地模型服务或模型名。后面的导入和检索依赖 embedding 模型。

## 3. 准备教程专用目录

这一步只清理教程自己的数据库和输出文件，不影响你的正式小说库：

```bash
rm -rf "$NOVEL_DB_PATH" "$NOVEL_OUT_DIR"
mkdir -p "$NOVEL_OUT_DIR" "$NOVEL_LOG_DIR"
```

## 4. 导入样例小说

```bash
uv run novel-extender ingest "$NOVEL_FILE" \
  --base-url "$NOVEL_BASE_URL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --log-dir "$NOVEL_LOG_DIR"
```

成功时你会看到：

```text
Ingested 3 chapters into Chroma.
Log: $NOVEL_LOG_DIR/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.jsonl
```

这说明工具已经：

- 按章节切开 `$NOVEL_FILE`；
- 调用本地 embedding 模型；
- 把章节写入 `$NOVEL_DB_PATH`；
- 记录运行日志。

## 5. 检索相关章节

```bash
uv run novel-extender retrieve "旧徽章 北楼 档案" \
  --base-url "$NOVEL_BASE_URL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 3
```

你会看到类似输出：

```text
novel-ch002    第2章 旧日线索    distance=...
novel-ch003    第3章 北楼灯火    distance=...
novel-ch001    第1章 初入星城    distance=...
```

不同 embedding 模型的排序和 distance 数值可能不同；重点是它会返回与查询相关的章节。

## 6. 生成“分析小说”的提示词

```bash
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
```

查看生成的提示词：

```bash
sed -n '1,220p' "$NOVEL_OUT_DIR/analysis_prompt.txt"
```

你会看到它包含：

- `【模式】analysis`
- `【分析要求】`
- `【最近章节】`
- `【相关检索章节】`
- `【分析流程】`

这个命令只生成提示词，方便你检查上下文。真正调用本地 chat 模型生成内容用下一节的 `generate` 命令。

## 7. 生成“续写下一章”

```bash
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
```

查看生成结果：

```bash
sed -n '1,260p' "$NOVEL_OUT_DIR/continuation.md"
```

这一步会实际调用本地 chat 模型，并要求模型：

- 先给下一章大纲；
- 再生成正文；
- 不改写既有人物关系；
- 不提前揭示未揭示伏笔。

## 8. 生成“改写章节”

```bash
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
```

查看生成结果：

```bash
sed -n '1,260p' "$NOVEL_OUT_DIR/rewrite.md"
```

这一步会实际调用本地 chat 模型，并要求模型：

- 先提取必须保留的事实；
- 再说明改写方案；
- 最后输出改写后的章节正文。

## 9. 确认公网模型地址会被拒绝

这一步不会真的访问公网，因为参数解析阶段就会拒绝：

```bash
uv run novel-extender validate-openai \
  --base-url https://api.openai.com/v1 \
  --chat-model "$NOVEL_CHAT_MODEL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL"
```

你应该看到类似错误：

```text
argument --base-url: invalid ensure_local_base_url value: 'https://api.openai.com/v1'
```

这表示 CLI 不接受公网模型端点。

## 10. 换成你自己的小说

教程跑通后，换成你自己的小说只需要重设开头那组变量。比如：

```bash
export NOVEL="my_novel"
export NOVEL_FILE="$HOME/Novels/my_novel.txt"
export NOVEL_COLLECTION="${NOVEL}_chapters"
export NOVEL_DB_PATH=".novel_extender/${NOVEL}_chroma"
export NOVEL_OUT_DIR=".novel_extender/${NOVEL}_outputs"
export NOVEL_LOG_DIR="${NOVEL_OUT_DIR}/logs"

rm -rf "$NOVEL_DB_PATH" "$NOVEL_OUT_DIR"
mkdir -p "$NOVEL_OUT_DIR" "$NOVEL_LOG_DIR"

uv run novel-extender ingest "$NOVEL_FILE" \
  --base-url "$NOVEL_BASE_URL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --log-dir "$NOVEL_LOG_DIR"

uv run novel-extender generate "$NOVEL_FILE" \
  "分析主角当前目标、关键冲突、未解释伏笔，并给出下一章推进建议。" \
  --base-url "$NOVEL_BASE_URL" \
  --chat-model "$NOVEL_CHAT_MODEL" \
  --embedding-model "$NOVEL_EMBEDDING_MODEL" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 5 \
  --recent-count 3 \
  --mode analysis \
  --log-dir "$NOVEL_LOG_DIR" \
  --output "$NOVEL_OUT_DIR/analysis.md"
```

常用替换：

- 分析：`--mode analysis`
- 续写：`--mode continuation`
- 改写：`--mode rewrite`

## 一次性命令参考

同样的流程也放在脚本里：

```bash
sed -n '1,240p' examples/tutorial_commands.sh
```

你可以逐段复制执行。脚本默认仍然只使用本地模型地址。
