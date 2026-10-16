// POST /api/search/preview, solo los campos que se leen (ver /openapi.json)
export type PreviewResponse = {
  queries: {
    kind: string
    tags: { tag: string; source: 'seed' | 'llm' }[]
  }[]
  llm: { error: string | null }
}
