import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import StatusLine from '@/components/StatusLine'

afterEach(cleanup)

// La linea de estado dice la familia con el tono de la regla, pero el color solo
// no alcanza: el tipo y el code van escritos. `data-severity` deja el tono a la
// vista de los tests sin leer clases
function tone(code: string | null) {
  const { container } = render(<StatusLine code={code}>The copy.</StatusLine>)
  return container.querySelector('[data-severity]') as HTMLElement
}

describe('the status line', () => {
  it.each([
    ['query_invalid', 'correctable', 'border-signal'],
    ['rate_limited', 'transient', 'border-pencil'],
    ['unauthenticated', 'setup', 'border-alert'],
    // La nota del modelo usa la misma linea: una clave que falta es setup rojo,
    // no un transitorio gris, aunque la busqueda siga con los tags del AST
    ['llm_not_configured', 'setup', 'border-alert'],
    ['llm_quota_exhausted', 'transient', 'border-pencil'],
  ])('tones %s as %s', (code, severity, rule) => {
    const line = tone(code)

    expect(line.getAttribute('data-severity')).toBe(severity)
    expect(line.className).toContain(rule)
    // El tipo y el code van escritos: el color solo no alcanza (WCAG 1.4.1)
    expect(screen.getByText(code)).toBeTruthy()
  })

  it('prints a type and a code for a failure', () => {
    tone('query_invalid')
    expect(screen.getByText('Invalid query')).toBeTruthy()
  })

  it('keeps an unknown code in the setup family, with a generic type', () => {
    const line = tone('a code from the future')

    expect(line.getAttribute('data-severity')).toBe('setup')
    expect(screen.getByText('Something went wrong')).toBeTruthy()
  })
})
