export type Mode = 'analysis' | 'continuation' | 'rewrite'

export interface Settings {
  baseUrl: string
  apiKey: string
  chatModel: string
  embeddingModel: string
  novelPath: string
  dbPath: string
  collection: string
  outputDir: string
  logDir: string
  topK: number
  recentCount: number
  promptCharBudget: number
  temperature: number
  maxTokens: number
  chapterBatchSize: number
}

export interface PreparedFile {
  novelPath: string
  dbPath: string
  collection: string
  outputDir: string
  logDir: string
  chapterCount: number
  chapters: ChapterSummary[]
}

export interface ChapterSummary {
  id: string
  title: string
  chars: number
}

export interface RetrievedItem {
  chapterId: string
  title: string
  index: number
  text: string
  distance: number | null
}

export interface ContextResult {
  prompt: string
  recentChapterIds: string[]
  retrievedChapterIds: string[]
  truncated: boolean
}

export interface GenerateResult extends ContextResult {
  text: string
  postCheck: {
    ok: boolean
    issues: string[]
  }
  memoryUpdated: boolean
  outputPath: string
  promptOutputPath: string
  logPath: string
}

export interface AppendResult {
  novelPath: string
  chapterCount: number
  appendedChapter: ChapterSummary & {
    index: number
  }
  memoryUpdated: boolean
  logPath: string
}

export interface GenerateSeriesResult extends GenerateResult {
  chapters: Array<
    Pick<GenerateResult, 'text' | 'prompt' | 'recentChapterIds' | 'retrievedChapterIds' | 'postCheck' | 'memoryUpdated'> & {
      index: number
      append: AppendResult | null
    }
  >
  appendedCount: number
}

export interface ValidateResult {
  valid: boolean
  baseUrl: string
  availableModels: string[]
  chat: ModelCheck
  embedding: ModelCheck
}

export interface ModelCheck {
  name: string
  model: string
  ok: boolean
  reason: string
}

export interface ApiOk<T> {
  ok: true
  data: T
}

export interface ApiFail {
  ok: false
  error: string
}

export type ApiResult<T> = ApiOk<T> | ApiFail

type RawApiResponse<T> = T & {
  ok: boolean
  error?: string
}

export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  try {
    const response = await fetch(path)
    const payload = (await response.json()) as RawApiResponse<T>
    if (!response.ok || payload.ok === false) {
      return { ok: false, error: payload.error || response.statusText }
    }
    const data = { ...payload } as Record<string, unknown>
    delete data.ok
    delete data.error
    return { ok: true, data: data as T }
  } catch (error) {
    return { ok: false, error: formatError(error) }
  }
}

export async function apiPost<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  try {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    const payload = (await response.json()) as RawApiResponse<T>
    if (!response.ok || payload.ok === false) {
      return { ok: false, error: payload.error || response.statusText }
    }
    const data = { ...payload } as Record<string, unknown>
    delete data.ok
    delete data.error
    return { ok: true, data: data as T }
  } catch (error) {
    return { ok: false, error: formatError(error) }
  }
}

export function buildWorkflowPayload(settings: Settings, request: string, mode: Mode) {
  return {
    ...settings,
    request,
    mode,
  }
}

export function outputFileName(mode: Mode): string {
  if (mode === 'analysis') return 'analysis.md'
  if (mode === 'rewrite') return 'rewrite.md'
  return 'next_chapter.md'
}

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
