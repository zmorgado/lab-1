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
