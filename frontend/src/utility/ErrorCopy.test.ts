import { describe, expect, it } from 'vitest'
import { API_URL } from '@/constants/api'
import { ApiError } from '@/services/common'
import { copyForCode, errorCopy, modelFallbackCopy } from '@/utility/ErrorCopy'

// Todo code estable del backend tiene que tener copy propia: si uno se agrega
// alla y no aca, cae al generico y el usuario no se entera de que puede hacer.
const CODES = [
  // proxy y GitHub (#9)
  'unauthenticated',
  'rate_limited',
  'query_invalid',
  'upstream_unavailable',
  'content_unusable',
  // pipeline (#8)
  'nothing_to_search',
  'unsupported_language',
  'invalid_tag',
  // modelo (#7)
  'empty_source',
  'llm_not_configured',
  'llm_auth',
  'llm_quota_exhausted',
  'llm_unavailable',
  'llm_malformed_response',
  'llm_request_failed',
]

const GENERIC = copyForCode('a code from the future')

describe('the frontend error taxonomy', () => {
  it.each(CODES)('has its own copy for %s', code => {
    const copy = copyForCode(code)
    expect(copy).not.toBe(GENERIC)
    expect(copy.length).toBeGreaterThan(0)
  })

  it('falls back to a generic line for an unknown code', () => {
    expect(copyForCode('not_a_code')).toBe(GENERIC)
  })

  it('reports a missing or rejected credential as a setup problem', () => {
    expect(copyForCode('unauthenticated')).toMatch(/GITHUB_TOKEN/)
    expect(copyForCode('llm_not_configured')).toMatch(/GEMINI_API_KEY/)
    expect(copyForCode('llm_auth')).toMatch(/GEMINI_API_KEY/)
  })

  it('tells the user to wait for a transient failure', () => {
    expect(copyForCode('rate_limited')).toMatch(/wait/i)
    expect(copyForCode('llm_quota_exhausted')).toMatch(/wait/i)
    expect(copyForCode('llm_unavailable')).toMatch(/try again in a while/i)
  })

  it('has its own copy for a backend that never answered', () => {
    const copy = errorCopy(new ApiError(null, null))
    expect(copy).toContain(API_URL)
    // Un servicio sin GITHUB_TOKEN muere al arrancar: el usuario solo lo ve aca
    expect(copy).toMatch(/GITHUB_TOKEN/)
  })

  it('reads the stable code off an ApiError', () => {
    expect(errorCopy(new ApiError('rate_limited', 403))).toBe(copyForCode('rate_limited'))
  })
})

describe('the model fallback note', () => {
  it('keys the explanation off the stable code', () => {
    expect(modelFallbackCopy(null)).toMatch(/found nothing/i)
    expect(modelFallbackCopy('llm_not_configured')).toMatch(/GEMINI_API_KEY/)
    expect(modelFallbackCopy('llm_auth')).toMatch(/rejected/i)
    expect(modelFallbackCopy('llm_quota_exhausted')).toMatch(/quota/i)
    expect(modelFallbackCopy('llm_unavailable')).toMatch(/unavailable/i)
  })
})
