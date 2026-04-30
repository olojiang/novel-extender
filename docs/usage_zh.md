# novel-extender 从零开始使用指南

这份文档按“什么都不知道”的起点写。目标是让你能把一部长篇小说放进本地数据库，然后围绕它做检索分析、续写和章节改写。

如果你想先直接复制命令跑一遍完整流程，先看 [tutorial_zh.md](tutorial_zh.md)。

## 这个工具做什么

它现在做六件事：

- 把小说文本按章节切开；
- 用本地 embedding 模型把章节写入本地 Chroma 向量库；
- 根据你的任务，取最近章节和相关章节，组装一段可交给本地大语言模型的提示词；
- 直接调用本地 chat 模型生成分析、续写或改写结果；
- 对生成结果做基础后置检查，拒绝空输出；
- 可选把生成章节写回当前小说的 Chroma collection，供后续检索使用。

`build-context` 只输出“准备好的提示词”，方便你审查上下文。`generate` 会执行完整流程：检索上下文、组装提示词、调用本地 chat 模型，并输出生成结果。

## Web 工作台

如果你不想手动拼命令，可以使用本地 Web 工作台。它由 Python API 和 `web/` 里的 Vue + TypeScript + Vite 前端组成。

第一次使用先安装前端依赖：

```bash
cd web
pnpm install
cd ..
```

启动 API：

```bash
uv run novel-extender-web
```

另开一个终端启动前端：

```bash
cd web
pnpm dev
```

界面中可以完成这些步骤：

- 选择 `.txt` 或 `.md` 小说文件，后端会保存到 `.novel_extender/web_inputs/`；
- 自动生成隔离的 Chroma 目录、collection、输出目录和日志目录；
- 验证本地模型；
- 点击 `Ingest` 导入章节；
- 点击 `搜索` 测试检索；
- 点击 `提示词` 查看本次上下文；
- 选择 `续写`、`改写` 或 `分析` 后点击 `生成`；
- 勾选 `生成后入库` 时，生成章节会写回当前 collection；
- 勾选 `写入后端目录` 时，结果会写到界面里的输出目录。

浏览器出于安全限制，通常不会把你选择的文件绝对路径暴露给网页。工作台采用“上传文本到本地 API 管理目录”的方式保证流程可运行；支持 File System Access API 的浏览器还可以选择浏览器侧保存目录。

## 本地调用边界

默认模型服务地址是：

```bash
http://127.0.0.1:1234/v1
```

代码只接受本机或内网 OpenAI-compatible 地址，例如：

- `127.0.0.1`
- `localhost`
- `192.168.x.x`
- `10.x.x.x`
- `172.16.x.x` 到 `172.31.x.x`
- `*.local`
- `host.docker.internal`

公网地址会被拒绝，例如：

```bash
https://api.openai.com/v1
```

Chroma 使用本地持久化目录，并显式关闭匿名遥测。

## 准备本地模型

你需要本地启动一个 OpenAI-compatible 服务，例如 LM Studio、LocalAI、Ollama 的 OpenAI-compatible 端口，或其他兼容 `/v1/models`、`/v1/chat/completions`、`/v1/embeddings` 的服务。

至少准备两个模型：

- chat 模型：用于之后阅读提示词并生成分析、续写或改写；
- embedding 模型：用于把章节和你的查询转成向量，做相关章节检索。

项目默认模型名是：

```bash
chat: qwen3.5-9b-uncensored-hauhaucs-aggressive-mlx
embedding: text-embedding-bge-large-zh-v1.5
```

如果你的本地服务里模型名不同，命令里用 `--chat-model` 和 `--embedding-model` 改掉。

## 1. 验证本地模型可用

先确认本地服务能列出模型，并且 chat 和 embedding 都能正常响应：

```bash
uv run novel-extender validate-openai
```

如果你的服务地址或模型名不同：

```bash
uv run novel-extender validate-openai \
  --base-url http://127.0.0.1:1234/v1 \
  --chat-model your-local-chat-model \
  --embedding-model your-local-embedding-model
```

这一步会做两次本地探测：

- 调一次本地 chat completion，让模型回复 `ok`；
- 调一次本地 embeddings，确认能返回向量。

## 2. 准备一部新小说

把小说保存成 UTF-8 文本文件。推荐章节标题类似：

```text
第1章 开端
正文……

第2章 线索
正文……
```

也可以参考项目里的样例：

```bash
examples/novel.txt
```

如果没有明显章节标题，工具会把整篇文本当成一个章节。

## 3. 导入小说到本地 Chroma

先为这部小说设置一组隔离变量。之后所有命令都只使用这些变量：

```bash
export NOVEL="my_novel"
export NOVEL_FILE="$HOME/Novels/my_novel.txt"
export NOVEL_COLLECTION="${NOVEL}_chapters"
export NOVEL_DB_PATH=".novel_extender/${NOVEL}_chroma"
export NOVEL_OUT_DIR=".novel_extender/${NOVEL}_outputs"
export NOVEL_LOG_DIR="${NOVEL_OUT_DIR}/logs"

mkdir -p "$NOVEL_OUT_DIR" "$NOVEL_LOG_DIR"
```

`NOVEL=my_novel` 会把向量库、输出文件和运行日志分别放到 `.novel_extender/my_novel_chroma` 和 `.novel_extender/my_novel_outputs` 这一套目录里。处理另一部小说时，换一个 `NOVEL` 值即可隔离。

检索和生成现在会按当前 `NOVEL_FILE` 的 `source_path` 过滤 Chroma 结果，避免同一个 collection 中的其他小说污染上下文。仍然建议每部小说使用独立的 `NOVEL_COLLECTION` 和 `NOVEL_DB_PATH`，这样删除、重建和备份都更清楚。

导入小说：

```bash
uv run novel-extender ingest "$NOVEL_FILE" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --log-dir "$NOVEL_LOG_DIR"
```

这一步会：

- 读取小说文本；
- 按章节切分；
- 调用本地 embedding 模型；
- 写入本地 Chroma 数据库；
- 在 `$NOVEL_LOG_DIR` 里写一份 JSONL 运行日志。

如果 embedding 模型名不同：

```bash
uv run novel-extender ingest "$NOVEL_FILE" \
  --base-url http://127.0.0.1:1234/v1 \
  --embedding-model your-local-embedding-model \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --log-dir "$NOVEL_LOG_DIR"
```

## 4. 检索相关章节

想知道某个线索和哪些章节相关：

```bash
uv run novel-extender retrieve "旧徽章 北楼 档案" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 5
```

输出会列出相关章节 id、标题和向量距离。距离通常越小越相关。

## 5. 分析小说

分析任务用 `generate --mode analysis`：

```bash
uv run novel-extender generate "$NOVEL_FILE" \
  "分析主角、北楼、旧徽章三条线索之间的关系，指出已有伏笔和后续可延展方向。" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 5 \
  --recent-count 3 \
  --mode analysis \
  --log-dir "$NOVEL_LOG_DIR" \
  --output "$NOVEL_OUT_DIR/analysis.md"
```

命令会调用本地 chat 模型，生成一份分析结果。内部使用的提示词包含：

- 你的分析要求；
- 最近几章；
- 从向量库检索出的相关章节；
- 分析流程要求。

如果你只想看提示词，不调用 chat 模型，把 `generate` 换成 `build-context`，并去掉 `--output`。

## 6. 续写下一章

续写任务用 `generate --mode continuation`：

```bash
uv run novel-extender generate "$NOVEL_FILE" \
  "续写下一章：主角夜探北楼，发现旧徽章和档案室失踪名单有关。保持悬疑节奏，不要提前揭示幕后人。" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 5 \
  --recent-count 3 \
  --mode continuation \
  --log-dir "$NOVEL_LOG_DIR" \
  --output "$NOVEL_OUT_DIR/next_chapter.md"
```

生成流程会要求本地模型：

- 先给下一章大纲；
- 再写正文；
- 保持人物关系、时间线和伏笔一致。

## 7. 修改或改写章节

改写任务用 `generate --mode rewrite`：

```bash
uv run novel-extender generate "$NOVEL_FILE" \
  "改写第2章：压缩开头铺垫，增强主角发现旧徽章时的紧张感，保留档案线索和人物关系。" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 5 \
  --recent-count 3 \
  --mode rewrite \
  --log-dir "$NOVEL_LOG_DIR" \
  --output "$NOVEL_OUT_DIR/rewrite_chapter_2.md"
```

生成流程会要求本地模型：

- 先提取必须保留的事实；
- 再说明改写方案；
- 最后输出改写后的章节正文。

## 8. 推荐工作流

第一次处理一部新小说：

```bash
uv run novel-extender validate-openai

uv run novel-extender ingest "$NOVEL_FILE" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --log-dir "$NOVEL_LOG_DIR"

uv run novel-extender retrieve "主角 核心线索 关键地点" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --top-k 5
```

之后按任务直接生成结果：

```bash
uv run novel-extender generate "$NOVEL_FILE" "你的任务描述" \
  --db-path "$NOVEL_DB_PATH" \
  --collection "$NOVEL_COLLECTION" \
  --mode analysis \
  --log-dir "$NOVEL_LOG_DIR" \
  --output "$NOVEL_OUT_DIR/result.md"
```

把 `--mode analysis` 换成 `continuation` 或 `rewrite`，就能切换到分析、续写、改写章节。

## 9. 常见问题

### 会不会调用在线模型？

默认不会。默认地址是 `127.0.0.1`，公网模型地址会被代码拒绝。你仍然应该确认本地模型服务本身没有配置上游代理。

### 为什么需要先 ingest？

`ingest` 会把每一章变成向量并写入 Chroma。后续 `retrieve`、`build-context` 和 `generate` 才能找出与任务相关的旧章节。

### 修改章节后要不要重新 ingest？

要。如果你改了原小说文本，重新运行 `ingest`，让 Chroma 里的章节内容和新文本一致。

### collection 是什么？

`collection` 是 Chroma 里的集合名。建议一部小说一个 collection，例如 `my_novel`、`book_a`。

### db-path 是什么？

`db-path` 是本地向量库目录。推荐用 `.novel_extender/${NOVEL}_chroma` 这种由小说隔离名派生的目录。
