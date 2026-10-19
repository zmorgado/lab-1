import { API_URL } from '@/constants/api'
import { ApiError } from '@/services/common'

// El texto sale del code estable, nunca del message del backend ni del texto de
// GitHub: la taxonomia es de #9, y cada code le dice al usuario que hacer.
const COPY = new Map<string, string>([
  [
    'unauthenticated',
    "This app's GitHub credential is missing or was rejected. That is a setup problem on the service's side, not your snippet: tell whoever runs it to check GITHUB_TOKEN.",
  ],
  [
    'rate_limited',
    "GitHub's shared search budget is used up for now. Nothing is broken: wait a minute and try again.",
  ],
  [
    'query_invalid',
    'GitHub rejected this search query. Change a tag or the snippet and try again.',
  ],
  [
    'upstream_unavailable',
    "GitHub isn't answering right now. Try again in a while.",
  ],
  [
    'content_unusable',
    "That file can't be read as source, so it can't be compared with your snippet.",
  ],
  [
    'nothing_to_search',
    'There is nothing distinctive enough in this snippet to search for. Paste a function or a class with names of its own.',
  ],
  ['unsupported_language', 'Only Python can be searched for now.'],
  ['invalid_tag', "One of the tags can't go into a search. Go back to the snippet and propose the tags again."],
])

export function errorCopy(error: unknown): string {
  // Un backend al que no llegamos no es un codigo: es nuestro servicio caido
  if (error instanceof ApiError && error.status === null) {
    return `The search service isn't answering at ${API_URL}. It may be down; try again in a while.`
  }
  const code = error instanceof ApiError ? error.code : null
  const copy = code === null ? undefined : COPY.get(code)
  if (copy) return copy

  // Un code que no conocemos tambien tiene copy: nunca en blanco ni el payload crudo
  return 'Something went wrong on the way. Try again in a while; the GitHub budget is shared by everyone, so waiting a minute often helps.'
}
