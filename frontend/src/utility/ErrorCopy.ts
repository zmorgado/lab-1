import { API_URL } from '@/constants/api'
import { ApiError } from '@/services/common'

// El texto sale del code estable, nunca del message del backend ni del texto de
// GitHub. La taxonomia completa es de #9
const COPY = new Map<string, string>([
  [
    'nothing_to_search',
    'There is nothing distinctive enough in this snippet to search for. Paste a function or a class with names of its own.',
  ],
  ['unsupported_language', 'Only Python can be searched for now.'],
  ['invalid_tag', "One of the tags can't go into a search. Go back to the snippet and propose the tags again."],
])

export function errorCopy(error: unknown): string {
  if (error instanceof ApiError && error.status === null) {
    return `The search service isn't answering at ${API_URL}. It may be down; try again in a while.`
  }
  const code = error instanceof ApiError ? error.code : null
  const copy = code === null ? undefined : COPY.get(code)
  if (copy) return copy

  const status = error instanceof ApiError ? ` (HTTP ${error.status})` : ''
  return `Something went wrong on the way${status}. The GitHub budget is shared by everyone, so waiting a minute often helps.`
}

// Las explicaciones de los resultados (#43): fallo el modelo, no la busqueda
const EXPLANATION_COPY = new Map<string, string>([
  ['llm_quota_exhausted', 'The model has used up its quota for now, so these matches go unexplained.'],
  ['llm_unavailable', "The model isn't available, so these matches go unexplained."],
])

export function explanationCopy(error: unknown): string {
  const code = error instanceof ApiError ? error.code : null
  const reason =
    (code !== null && EXPLANATION_COPY.get(code)) || "The model couldn't explain these matches this time."
  return `${reason} The ranking doesn't depend on it.`
}
