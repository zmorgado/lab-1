export type TagSource = 'ast' | 'model'

export type Tag = { text: string; source: TagSource }

// Una query de la busqueda: syntactic, conceptual, paradigm, o tiers sin el modelo
export type TagQuery = { kind: string; tags: Tag[] }

export type TagPreview = {
  queries: TagQuery[]
  // El code del modelo si fallo: los tags salen entonces solo del AST
  modelError: string | null
}
