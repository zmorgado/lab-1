// POST /api/search, solo los campos que se leen (ver /openapi.json)
export type SearchResponse = {
  results: {
    score: number
    // Todos los repos publicos con el mismo contenido (sha)
    locations: { repo: string; path: string; html_url: string | null }[]
    name: string
    parent: string | null
    start_line: number
    end_line: number
    code: string
  }[]
}
