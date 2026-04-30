import { describe, expect, it } from 'vitest'
import { buildWorkflowPayload, outputFileName, type Settings } from './api'

const settings: Settings = {
  baseUrl: 'http://127.0.0.1:1234/v1',
  apiKey: 'not-needed',
  chatModel: 'chat-model',
  embeddingModel: 'embedding-model',
  novelPath: '/tmp/novel.txt',
  dbPath: '/tmp/chroma',
  collection: 'novel_chapters',
  outputDir: '/tmp/out',
  logDir: '/tmp/out/logs',
  topK: 5,
  recentCount: 3,
  promptCharBudget: 12000,
  temperature: 0.7,
  maxTokens: 4096,
  chapterBatchSize: 2,
}

describe('workflow payload helpers', () => {
  it('maps one request into retrieve, context, and generate payload fields', () => {
    const payload = buildWorkflowPayload(settings, '续写下一章。', 'continuation')

    expect(payload.request).toBe('续写下一章。')
    expect(payload.mode).toBe('continuation')
    expect(payload.collection).toBe('novel_chapters')
    expect(payload).not.toHaveProperty('query')
  })

  it('uses stable output names per mode', () => {
    expect(outputFileName('analysis')).toBe('analysis.md')
    expect(outputFileName('continuation')).toBe('next_chapter.md')
    expect(outputFileName('rewrite')).toBe('rewrite.md')
  })
})
