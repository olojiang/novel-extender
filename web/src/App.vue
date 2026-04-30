<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  apiGet,
  apiPost,
  buildWorkflowPayload,
  outputFileName,
  type ContextResult,
  type AppendResult,
  type GenerateResult,
  type GenerateSeriesResult,
  type Mode,
  type PreparedFile,
  type RetrievedItem,
  type Settings,
  type ValidateResult,
} from './api'

type RunState = 'idle' | 'running' | 'success' | 'error'
type Theme = 'light' | 'dark'

interface Step {
  id: string
  label: string
  state: RunState
  detail: string
}

const settings = reactive<Settings>({
  baseUrl: 'http://127.0.0.1:1234/v1',
  apiKey: 'not-needed',
  chatModel: '',
  embeddingModel: '',
  novelPath: '',
  dbPath: '',
  collection: '',
  outputDir: '',
  logDir: '',
  topK: 5,
  recentCount: 3,
  promptCharBudget: 12000,
  temperature: 0.7,
  maxTokens: 4096,
  chapterBatchSize: 2,
})

const steps = reactive<Step[]>([
  { id: 'prepare', label: '文件', state: 'idle', detail: '等待选择' },
  { id: 'validate', label: '模型', state: 'idle', detail: '未验证' },
  { id: 'ingest', label: '入库', state: 'idle', detail: '未开始' },
  { id: 'retrieve', label: '检索', state: 'idle', detail: '未测试' },
  { id: 'context', label: '提示词', state: 'idle', detail: '未构建' },
  { id: 'generate', label: '生成', state: 'idle', detail: '未开始' },
])

const mode = ref<Mode>('continuation')
const request = ref('续写下一章，重点写北楼档案和旧徽章的联系。')
const updateMemory = ref(false)
const appendToNovel = ref(true)
const saveServerOutput = ref(true)
const savePrompt = ref(true)
const selectedDirectory = ref<FileSystemDirectoryHandle | null>(null)
const prepared = ref<PreparedFile | null>(null)
const validateReport = ref<ValidateResult | null>(null)
const retrieved = ref<RetrievedItem[]>([])
const context = ref<ContextResult | null>(null)
const generated = ref<GenerateResult | null>(null)
const appendResult = ref<AppendResult | null>(null)
const promptText = ref('')
const outputText = ref('')
const errorMessage = ref('')
const busy = ref(false)
const activeStepId = ref<string | null>(null)
const activeTab = ref<'retrieve' | 'prompt' | 'output'>('retrieve')
const theme = ref<Theme>('light')

const canUseDirectoryPicker = computed(() => typeof window.showDirectoryPicker === 'function')
const outputPath = computed(() => `${settings.outputDir}/${outputFileName(mode.value)}`)
const promptOutputPath = computed(() => `${settings.outputDir}/prompt_${outputFileName(mode.value)}`)
const workflowPayload = computed(() => buildWorkflowPayload(settings, request.value, mode.value))
const activeStep = computed(() => steps.find((step) => step.id === activeStepId.value) ?? null)
const isRunning = (id: string) => activeStepId.value === id && busy.value

onMounted(async () => {
  const storedTheme = window.localStorage.getItem('novel-extender-theme')
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
  applyTheme(storedTheme === 'dark' || (!storedTheme && prefersDark) ? 'dark' : 'light')

  const result = await apiGet<Settings>('/api/defaults')
  if (result.ok) {
    Object.assign(settings, result.data)
  }
})

function applyTheme(nextTheme: Theme) {
  theme.value = nextTheme
  window.document.documentElement.dataset.theme = nextTheme
  window.localStorage.setItem('novel-extender-theme', nextTheme)
}

function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

async function prepareFromFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  await runStep('prepare', async () => {
    const text = await file.text()
    const result = await apiPost<PreparedFile>('/api/prepare-file', {
      filename: file.name,
      text,
    })
    if (!result.ok) throw new Error(result.error)
    prepared.value = result.data
    Object.assign(settings, {
      novelPath: result.data.novelPath,
      dbPath: result.data.dbPath,
      collection: result.data.collection,
      outputDir: result.data.outputDir,
      logDir: result.data.logDir,
    })
    return `${result.data.chapterCount} 章`
  })
}

async function validateModels() {
  await runStep('validate', async () => {
    const result = await apiPost<ValidateResult>('/api/validate-openai', settings)
    if (!result.ok) throw new Error(result.error)
    validateReport.value = result.data
    return result.data.valid ? '可用' : '失败'
  })
}

async function ingestNovel() {
  await runStep('ingest', async () => {
    const result = await apiPost<{ chapterCount: number; storedCount: number; logPath: string }>(
      '/api/ingest',
      settings,
    )
    if (!result.ok) throw new Error(result.error)
    return `${result.data.storedCount}/${result.data.chapterCount} 章`
  })
}

async function retrieveChapters() {
  await runStep('retrieve', async () => {
    const result = await apiPost<{ items: RetrievedItem[] }>('/api/retrieve', workflowPayload.value)
    if (!result.ok) throw new Error(result.error)
    retrieved.value = result.data.items
    activeTab.value = 'retrieve'
    return `${result.data.items.length} 条`
  })
}

async function buildContext() {
  await runStep('context', async () => {
    const result = await apiPost<ContextResult>('/api/build-context', workflowPayload.value)
    if (!result.ok) throw new Error(result.error)
    context.value = result.data
    promptText.value = result.data.prompt
    activeTab.value = 'prompt'
    return result.data.truncated ? '已截断' : `${result.data.prompt.length} 字`
  })
}

async function generateText() {
  await runStep('generate', async () => {
    const payload = {
      ...workflowPayload.value,
      updateMemory: updateMemory.value,
      outputPath: saveServerOutput.value ? outputPath.value : '',
      promptOutputPath: savePrompt.value ? promptOutputPath.value : '',
    }
    const result = await apiPost<GenerateResult>('/api/generate', payload)
    if (!result.ok) throw new Error(result.error)
    generated.value = result.data
    appendResult.value = null
    context.value = result.data
    promptText.value = result.data.prompt
    outputText.value = result.data.text
    activeTab.value = 'output'
    if (selectedDirectory.value) {
      await writeToSelectedDirectory(outputFileName(mode.value), result.data.text)
      if (savePrompt.value) {
        await writeToSelectedDirectory(`prompt_${outputFileName(mode.value)}`, result.data.prompt)
      }
    }
    return result.data.memoryUpdated ? '已生成并入库' : '已生成'
  })
}

async function appendGeneratedOutput() {
  await runStep('generate', async () => {
    const text = outputText.value.trim()
    if (!text) throw new Error('没有可保存的输出')
    const result = await apiPost<AppendResult>('/api/append-output', {
      ...workflowPayload.value,
      text,
      updateMemory: updateMemory.value,
    })
    if (!result.ok) throw new Error(result.error)
    appendResult.value = result.data
    if (prepared.value) {
      prepared.value.chapterCount = result.data.chapterCount
      prepared.value.chapters = [...prepared.value.chapters, result.data.appendedChapter]
    }
    return `已保存 ${result.data.appendedChapter.title}`
  })
}

async function generateSeries() {
  await runStep('generate', async () => {
    const payload = {
      ...workflowPayload.value,
      chapterBatchSize: settings.chapterBatchSize,
      appendToNovel: appendToNovel.value,
      updateMemory: updateMemory.value || appendToNovel.value,
      outputPath: saveServerOutput.value ? outputPath.value : '',
      promptOutputPath: savePrompt.value ? promptOutputPath.value : '',
    }
    const result = await apiPost<GenerateSeriesResult>('/api/generate-series', payload)
    if (!result.ok) throw new Error(result.error)
    generated.value = result.data
    context.value = result.data
    promptText.value = result.data.prompt
    outputText.value = result.data.text
    appendResult.value = result.data.chapters.at(-1)?.append ?? null
    activeTab.value = 'output'
    if (selectedDirectory.value) {
      await writeToSelectedDirectory(outputFileName(mode.value), result.data.text)
      if (savePrompt.value) {
        await writeToSelectedDirectory(`prompt_${outputFileName(mode.value)}`, result.data.prompt)
      }
    }
    if (prepared.value && appendToNovel.value) {
      prepared.value.chapterCount += result.data.appendedCount
      prepared.value.chapters = [
        ...prepared.value.chapters,
        ...result.data.chapters
          .map((chapter) => chapter.append?.appendedChapter)
          .filter((chapter): chapter is AppendResult['appendedChapter'] => Boolean(chapter)),
      ]
    }
    return appendToNovel.value
      ? `已生成并保存 ${result.data.appendedCount} 章`
      : `已生成 ${result.data.chapters.length} 章`
  })
}

async function runAll() {
  await ingestNovel()
  if (errorMessage.value) return
  await retrieveChapters()
  if (errorMessage.value) return
  await buildContext()
  if (errorMessage.value) return
  await generateText()
}

async function chooseBrowserDirectory() {
  if (!window.showDirectoryPicker) return
  try {
    selectedDirectory.value = await window.showDirectoryPicker()
  } catch {
    /* user cancelled the dialog */
  }
}

async function writeToSelectedDirectory(name: string, text: string) {
  if (!selectedDirectory.value) return
  try {
    const file = await selectedDirectory.value.getFileHandle(name, { create: true })
    const writable = await file.createWritable()
    await writable.write(text)
    await writable.close()
  } catch (error) {
    console.warn('Failed to write to selected directory:', error)
  }
}

async function runStep(id: string, action: () => Promise<string>) {
  const step = steps.find((item) => item.id === id)
  if (!step || busy.value) return
  busy.value = true
  activeStepId.value = id
  errorMessage.value = ''
  step.state = 'running'
  step.detail = '运行中'
  try {
    step.detail = await action()
    step.state = 'success'
  } catch (error) {
    step.state = 'error'
    step.detail = '失败'
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    busy.value = false
    activeStepId.value = null
  }
}
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">novel-extender</p>
        <h1>长篇小说本地工作台</h1>
      </div>
      <div class="topbar-right">
        <button class="theme-toggle" type="button" :aria-pressed="theme === 'dark'" @click="toggleTheme">
          <span class="theme-toggle-track">
            <span class="theme-toggle-thumb"></span>
          </span>
          {{ theme === 'dark' ? '深色' : '浅色' }}
        </button>
        <div class="status-strip" aria-label="工作流状态">
          <span v-for="step in steps" :key="step.id" class="status-pill" :class="step.state">
            <span class="status-dot"></span>
            {{ step.label }} · {{ step.detail }}
          </span>
        </div>
      </div>
    </header>

    <section class="workspace">
      <aside class="sidebar" aria-label="项目配置">
        <section class="panel">
          <div class="panel-title">
            <h2>小说与路径</h2>
            <label class="file-button">
              <input type="file" accept=".txt,.md,text/plain,text/markdown" @change="prepareFromFile" />
              <span>
                <span v-if="isRunning('prepare')" class="spinner" aria-hidden="true"></span>
                选择文件
              </span>
            </label>
          </div>
          <label>
            小说文件
            <input v-model="settings.novelPath" type="text" />
          </label>
          <label>
            Chroma 目录
            <input v-model="settings.dbPath" type="text" />
          </label>
          <label>
            Collection
            <input v-model="settings.collection" type="text" />
          </label>
          <label>
            后端输出目录
            <input v-model="settings.outputDir" type="text" />
          </label>
          <label>
            日志目录
            <input v-model="settings.logDir" type="text" />
          </label>
          <button class="secondary" type="button" :disabled="!canUseDirectoryPicker" @click="chooseBrowserDirectory">
            浏览器保存目录
          </button>
          <div v-if="prepared" class="chapter-list">
            <strong>{{ prepared.chapterCount }} 章</strong>
            <span v-for="chapter in prepared.chapters.slice(0, 5)" :key="chapter.id">
              {{ chapter.title }} · {{ chapter.chars }} 字
            </span>
          </div>
        </section>

        <section class="panel">
          <h2>模型配置</h2>
          <label>
            Base URL
            <input v-model="settings.baseUrl" type="text" />
          </label>
          <label>
            API Key
            <input v-model="settings.apiKey" type="password" />
          </label>
          <label>
            Chat model
            <input v-model="settings.chatModel" type="text" />
          </label>
          <label>
            Embedding model
            <input v-model="settings.embeddingModel" type="text" />
          </label>
          <button class="secondary" type="button" :disabled="busy" @click="validateModels">
            <span v-if="isRunning('validate')" class="spinner" aria-hidden="true"></span>
            验证模型
          </button>
          <p v-if="validateReport" class="model-report">
            Chat: {{ validateReport.chat.ok ? 'OK' : 'FAIL' }} · Embedding:
            {{ validateReport.embedding.ok ? 'OK' : 'FAIL' }}
          </p>
        </section>
      </aside>

      <section class="main-panel" aria-label="工作流">
        <div class="toolbar">
          <div class="segmented" aria-label="模式">
            <button :class="{ active: mode === 'continuation' }" type="button" @click="mode = 'continuation'">
              续写
            </button>
            <button :class="{ active: mode === 'rewrite' }" type="button" @click="mode = 'rewrite'">改写</button>
            <button :class="{ active: mode === 'analysis' }" type="button" @click="mode = 'analysis'">分析</button>
          </div>
          <div class="toolbar-actions">
            <button type="button" :disabled="busy" @click="ingestNovel">
              <span v-if="isRunning('ingest')" class="spinner" aria-hidden="true"></span>
              Ingest
            </button>
            <button type="button" :disabled="busy" @click="retrieveChapters">
              <span v-if="isRunning('retrieve')" class="spinner" aria-hidden="true"></span>
              搜索
            </button>
            <button type="button" :disabled="busy" @click="buildContext">
              <span v-if="isRunning('context')" class="spinner" aria-hidden="true"></span>
              提示词
            </button>
            <button class="primary" type="button" :disabled="busy" @click="generateText">
              <span v-if="isRunning('generate')" class="spinner" aria-hidden="true"></span>
              生成
            </button>
          </div>
        </div>

        <div v-if="busy && activeStep" class="process-banner" aria-live="polite">
          <span class="process-orbit" aria-hidden="true"></span>
          <span>{{ activeStep.label }}处理中</span>
          <strong>{{ activeStep.detail }}</strong>
        </div>

        <textarea v-model="request" class="request-box" rows="5"></textarea>

        <div class="controls-grid">
          <label>
            Top K
            <input v-model.number="settings.topK" type="number" min="1" />
          </label>
          <label>
            最近章节
            <input v-model.number="settings.recentCount" type="number" min="0" />
          </label>
          <label>
            Prompt 字符
            <input v-model.number="settings.promptCharBudget" type="number" min="1" />
          </label>
          <label>
            Temperature
            <input v-model.number="settings.temperature" type="number" min="0" max="2" step="0.1" />
          </label>
          <label>
            Max tokens
            <input v-model.number="settings.maxTokens" type="number" min="1" />
          </label>
          <label>
            连续章节
            <input v-model.number="settings.chapterBatchSize" type="number" min="1" max="20" />
          </label>
        </div>

        <div class="toggles">
          <label><input v-model="updateMemory" type="checkbox" /> 生成后入库</label>
          <label><input v-model="appendToNovel" type="checkbox" /> 追加到小说文件</label>
          <label><input v-model="saveServerOutput" type="checkbox" /> 写入后端目录</label>
          <label><input v-model="savePrompt" type="checkbox" /> 保存提示词</label>
        </div>

        <div class="run-row">
          <button class="primary wide" type="button" :disabled="busy" @click="runAll">
            <span v-if="busy && activeStepId !== 'generate'" class="spinner" aria-hidden="true"></span>
            从入库到生成
          </button>
          <button type="button" :disabled="busy || !outputText.trim()" @click="appendGeneratedOutput">
            <span v-if="isRunning('generate')" class="spinner" aria-hidden="true"></span>
            保存为下一章
          </button>
          <button class="primary" type="button" :disabled="busy" @click="generateSeries">
            <span v-if="isRunning('generate')" class="spinner" aria-hidden="true"></span>
            连续生成
          </button>
          <span class="path-preview">{{ saveServerOutput ? outputPath : '不写入后端输出文件' }}</span>
        </div>

        <p v-if="errorMessage" class="error-box">{{ errorMessage }}</p>
      </section>

      <aside class="result-panel" aria-label="结果">
        <nav class="tabs">
          <button :class="{ active: activeTab === 'retrieve' }" type="button" @click="activeTab = 'retrieve'">
            检索
          </button>
          <button :class="{ active: activeTab === 'prompt' }" type="button" @click="activeTab = 'prompt'">
            提示词
          </button>
          <button :class="{ active: activeTab === 'output' }" type="button" @click="activeTab = 'output'">
            输出
          </button>
        </nav>

        <section v-if="activeTab === 'retrieve'" class="result-list">
          <article v-for="item in retrieved" :key="item.chapterId" class="result-item">
            <header>
              <strong>{{ item.title }}</strong>
              <span>{{ item.distance?.toFixed(4) ?? 'n/a' }}</span>
            </header>
            <p>{{ item.text.slice(0, 240) }}</p>
          </article>
          <p v-if="retrieved.length === 0" class="empty">暂无检索结果</p>
        </section>

        <section v-if="activeTab === 'prompt'" class="text-pane">
          <textarea v-model="promptText" rows="26"></textarea>
          <footer v-if="context">
            最近：{{ context.recentChapterIds.join(', ') || 'none' }} · 检索：{{
              context.retrievedChapterIds.join(', ') || 'none'
            }}
          </footer>
        </section>

        <section v-if="activeTab === 'output'" class="text-pane">
          <textarea v-model="outputText" rows="26"></textarea>
          <footer v-if="generated">
            Post-check: {{ generated.postCheck.ok ? 'OK' : generated.postCheck.issues.join(', ') }} · Log:
            {{ generated.logPath }}
            <template v-if="appendResult">
              · 已保存：{{ appendResult.appendedChapter.title }} · 共 {{ appendResult.chapterCount }} 章
            </template>
          </footer>
        </section>
      </aside>
    </section>
  </main>
</template>
