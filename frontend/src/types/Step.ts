import type { Explanations } from '@/types/Explanations'
import type { SearchOutcome } from '@/types/SearchOutcome'
import type { TagPreview } from '@/types/TagPreview'

// Un estado por paso de la pagina. El snippet vive aparte: sobrevive a todos
export type Step =
  | { step: 'editing' }
  | { step: 'loadingTags' }
  | { step: 'confirming'; preview: TagPreview }
  | { step: 'searching'; preview: TagPreview }
  | { step: 'done'; preview: TagPreview; outcome: SearchOutcome; explanations: Explanations }
  | { step: 'failed'; at: 'tags'; error: unknown }
  | { step: 'failed'; at: 'search'; error: unknown; preview: TagPreview }
