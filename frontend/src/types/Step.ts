import type { TagPreview } from '@/types/TagPreview'

// Un estado por paso de la pagina. El snippet vive aparte: sobrevive a todos
export type Step =
  | { step: 'editing' }
  | { step: 'loadingTags' }
  | { step: 'confirming'; preview: TagPreview }
  | { step: 'failed'; at: 'tags'; error: unknown }
