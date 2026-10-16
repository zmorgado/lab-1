export type TagSource = 'ast' | 'model' | 'you'

export type DraftTag = { text: string; source: TagSource; selected: boolean }

// Un grupo es una query: syntactic, conceptual, paradigm, o tiers sin el modelo.
// `dropped` son los seleccionados que no entran por el tope de tags o de largo
export type TagGroup = { kind: string; tags: DraftTag[]; dropped: string[] }

export type TagPreview = {
  groups: TagGroup[]
  // El code del modelo si fallo: los tags salen entonces solo del AST
  modelError: string | null
}
