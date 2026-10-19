import { API_URL } from '@/constants/api'
import { ApiError } from '@/services/common'

// La taxonomia de errores del frontend (#9): un code estable por falla, y cada
// code le dice al usuario que hacer. El texto nunca sale del `message` del
// backend ni de la prosa del proveedor (GitHub, Gemini): esa cambia cuando
// quieren, el code no.
//
// Familias, para que se vea de un vistazo que no falta ninguna:
// - transporte: `service_unreachable` lo sintetiza el frontend cuando no hubo
//   respuesta; el backend nunca lo manda.
// - proxy y GitHub (#3, #9): `unauthenticated`, `rate_limited`, `query_invalid`,
//   `upstream_unavailable`, `content_unusable`.
// - pipeline (#8): `nothing_to_search`, `unsupported_language`, `invalid_tag`.
// - modelo (#7): `empty_source` y los `llm_*`.
//
// Un problema de *configuracion* (`unauthenticated`, `llm_not_configured`,
// `llm_auth`) dice que lo arregle quien corre el servicio; una caida pasajera
// (`rate_limited`, `llm_quota_exhausted`, `llm_unavailable`) dice que espere.
const COPY: Record<string, string> = {
  // --- transporte -----------------------------------------------------------

  // Sin respuesta: o el servicio esta caido, o no arranco por falta de token
  service_unreachable: `The search service isn't answering at ${API_URL}. It may be down, or it may be missing its GITHUB_TOKEN; if you run it, check BACKEND.md. Otherwise, try again in a while.`,

  // --- proxy y GitHub -------------------------------------------------------

  unauthenticated:
    "This app's GitHub credential is missing or was rejected. That is a setup problem on the service's side, not your snippet: tell whoever runs it to check GITHUB_TOKEN.",
  rate_limited:
    "GitHub's shared search budget is used up for now. Nothing is broken: wait a minute and try again.",
  query_invalid:
    'GitHub rejected this search query. Change a tag or the snippet and try again.',
  upstream_unavailable: "GitHub isn't answering right now. Try again in a while.",
  content_unusable:
    "That file can't be read as source, so it can't be compared with your snippet.",

  // --- pipeline -------------------------------------------------------------

  nothing_to_search:
    'There is nothing distinctive enough in this snippet to search for. Paste a function or a class with names of its own.',
  unsupported_language: 'Only Python can be searched for now.',
  invalid_tag: "One of the tags can't go into a search. Go back to the snippet and propose the tags again.",

  // --- modelo ---------------------------------------------------------------

  empty_source: 'There is nothing in the snippet for the model to read tags from. Paste a function or a class.',
  llm_not_configured:
    "This app's model key is missing. That is a setup problem on the service's side, not your snippet: tell whoever runs it to check GEMINI_API_KEY. The search still runs without model tags.",
  llm_auth:
    "This app's model key was rejected. That is a setup problem on the service's side, not your snippet: tell whoever runs it to check GEMINI_API_KEY.",
  llm_quota_exhausted:
    "The model's free quota is used up for now. Nothing is broken: wait a bit and try again.",
  llm_unavailable: "The model isn't answering right now. Try again in a while.",
  llm_malformed_response:
    "The model answered in a way this app couldn't read. Try again; if it keeps happening, tell whoever runs it.",
  llm_request_failed: "The model request didn't go through. Try again in a while.",
}

// Un code que no conocemos tambien tiene copy: nunca en blanco ni el payload crudo
const GENERIC =
  'Something went wrong on the way. Try again in a while; the GitHub budget is shared by everyone, so waiting a minute often helps.'

export function copyForCode(code: string | null): string {
  return (code !== null && COPY[code]) || GENERIC
}

export function errorCopy(error: unknown): string {
  // Un backend al que no llegamos no es un codigo: es nuestro servicio caido
  if (error instanceof ApiError && error.status === null) {
    return COPY.service_unreachable
  }
  const code = error instanceof ApiError ? error.code : null
  return copyForCode(code)
}

// El modelo es un complemento (#1): cuando falla, la busqueda sigue con los tags
// del AST y el paso 2 explica por que. Mismo code estable, otro encuadre: aca no
// es una falla de la pagina, es de donde salieron los tags
const AST_ONLY = 'so these tags come from the syntax tree alone, in one query instead of three.'

export function modelFallbackCopy(code: string | null): string {
  switch (code) {
    case null:
      return 'The model found nothing worth searching for, so these tags come from the syntax tree alone.'
    case 'empty_source':
      return `There was nothing in the snippet for the model to read, ${AST_ONLY}`
    case 'llm_not_configured':
      return `The model isn't configured on this service (no GEMINI_API_KEY), ${AST_ONLY}`
    case 'llm_auth':
      return `The model rejected this service's API key, ${AST_ONLY}`
    case 'llm_quota_exhausted':
      return `The model's free quota is used up for now, ${AST_ONLY}`
    default:
      return `The model was unavailable, ${AST_ONLY}`
  }
}
