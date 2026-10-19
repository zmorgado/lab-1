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

// === Como se imprime la falla =================================================
//
// La taxonomia no decide solo *que dice* la copy, tambien *como se ve*. Tres
// familias, por quien tiene que actuar:
//
//   correctable  lo cambia el usuario (snippet o tags)     -> --signal
//   transient    nadie: se espera (presupuesto/proveedor)  -> --pencil
//   setup        lo arregla quien corre el servicio        -> --alert
//
// Un code desconocido cae en `setup` a proposito: ante la duda conviene que lo
// mire un humano, y no mandarlo a "espera un rato" cuando nunca se arregla solo.
export type Severity = 'correctable' | 'transient' | 'setup'

const SEVERITY: Record<string, Severity> = {
  // El usuario cambia algo y vuelve a probar
  query_invalid: 'correctable',
  invalid_tag: 'correctable',
  unsupported_language: 'correctable',
  nothing_to_search: 'correctable',
  empty_source: 'correctable',
  // Nada que arreglar: el presupuesto compartido o el proveedor estan ocupados
  rate_limited: 'transient',
  llm_quota_exhausted: 'transient',
  llm_unavailable: 'transient',
  llm_request_failed: 'transient',
  llm_malformed_response: 'transient',
  upstream_unavailable: 'transient',
  content_unusable: 'transient',
  // Configuracion: lo arregla quien corre el servicio, no el usuario
  unauthenticated: 'setup',
  llm_not_configured: 'setup',
  llm_auth: 'setup',
  service_unreachable: 'setup',
}

export function severityFor(code: string | null): Severity {
  return (code !== null && SEVERITY[code]) || 'setup'
}

// El nombre corto de cada code: la etiqueta mono de la linea de estado y el
// titulo del popup. La oracion larga va abajo, como copy
const TYPE_LABEL: Record<string, string> = {
  service_unreachable: 'Service unreachable',
  unauthenticated: 'Setup · GitHub token',
  rate_limited: 'Rate limited',
  query_invalid: 'Invalid query',
  upstream_unavailable: 'GitHub unavailable',
  content_unusable: 'File unreadable',
  nothing_to_search: 'Nothing to search',
  unsupported_language: 'Unsupported language',
  invalid_tag: 'Invalid tag',
  empty_source: 'Empty snippet',
  llm_not_configured: 'Model · not configured',
  llm_auth: 'Model · key rejected',
  llm_quota_exhausted: 'Model · quota spent',
  llm_unavailable: 'Model unavailable',
  llm_malformed_response: 'Model · bad answer',
  llm_request_failed: 'Model · request failed',
}

export function typeLabel(code: string | null): string {
  return (code !== null && TYPE_LABEL[code]) || 'Something went wrong'
}

// Que significa la familia, para el popup: la copy dice que hacer, esto por que
const SEVERITY_NOTE: Record<Severity, string> = {
  correctable: 'Something in the snippet or the tags has to change before this can run again.',
  transient: 'Nothing here is broken: the shared budget or the provider is busy. Waiting clears it.',
  setup: 'A credential or the service itself has to be fixed before this step can run.',
}

export function severityNote(severity: Severity): string {
  return SEVERITY_NOTE[severity]
}

// El code estable del error. Un backend al que no llegamos no manda code: lo
// sintetizamos como `service_unreachable`, el mismo que ya usa la copy. Devuelve
// null solo para lo que no es un error de un llamado (un bug de JS, por ejemplo)
export function errorCode(error: unknown): string | null {
  if (error instanceof ApiError && error.status === null) return 'service_unreachable'
  return error instanceof ApiError ? error.code : null
}

export function errorCopy(error: unknown): string {
  return copyForCode(errorCode(error))
}

export function copyForCode(code: string | null): string {
  return (code !== null && COPY[code]) || GENERIC
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
