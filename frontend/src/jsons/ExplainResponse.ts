// POST /api/search/explain (#43), solo los campos que se leen (ver /openapi.json)
export type ExplainResponse = {
  explanations: {
    rank: number
    value: string
    // Vacia si el modelo no vio nada que traer al snippet
    suggestion: string
    // Lineas del archivo, inclusivas
    highlights: { start: number; end: number }[]
  }[]
}
