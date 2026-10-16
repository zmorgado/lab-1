import type { PreviewResponse } from '@/jsons/PreviewResponse'
import type { TagPreview } from '@/types/TagPreview'

// La frontera entre las formas crudas del backend (jsons/) y las del dominio (types/)

export const toTagPreview = (raw: PreviewResponse): TagPreview => ({
  queries: raw.queries.map(query => ({
    kind: query.kind,
    tags: query.tags.map(tag => ({ text: tag.tag, source: tag.source === 'llm' ? 'model' : 'ast' })),
  })),
  modelError: raw.llm.error,
})
