// POST /api/search/preview, solo los campos que se leen (ver /openapi.json)
export type PreviewResponse = {
  // Vacio cuando se mandaron tags: el pool ya lo tiene la pagina
  pool: { tag: string; kind: string; source: 'seed' | 'llm'; selected: boolean }[]
  queries: { kind: string; dropped: string[] }[]
  llm: { error: string | null }
}
