import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen, within } from '@testing-library/react'
import userEvent, { type UserEvent } from '@testing-library/user-event'
import { http, HttpResponse, type JsonBodyType } from 'msw'
import { setupServer } from 'msw/node'
import Search from '@/pages/Search'

// El backend se stubea en el borde HTTP: la pagina no sabe que hay MSW
const server = setupServer()

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  vi.useRealTimers()
})
afterAll(() => server.close())

const snippetBox = () => screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Snippet' })

const METHOD = '    def rank(self, items):\n        return sorted(items, key=self.score)\n'

describe('attaching a snippet', () => {
  it('fills the snippet from an attached .py file', async () => {
    const user = userEvent.setup()
    render(<Search />)

    await user.upload(
      screen.getByLabelText(/attach a \.py file/i),
      new File([METHOD], 'ranking.py', { type: 'text/x-python' }),
    )

    expect(await screen.findByDisplayValue(/def rank/)).toHaveProperty('value', METHOD)
  })

  it('refuses a file that is not Python', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<Search />)

    await user.upload(
      screen.getByLabelText(/attach a \.py file/i),
      new File(['const a = 1'], 'notes.js', { type: 'text/javascript' }),
    )

    expect(await screen.findByText(/only \.py files/i)).toBeTruthy()
    expect(snippetBox().value).toBe('')
  })

  it("can't submit an empty snippet", async () => {
    const user = userEvent.setup()
    render(<Search />)
    const submit = screen.getByRole('button', { name: /propose tags/i })

    expect(submit).toHaveProperty('disabled', true)
    await user.type(snippetBox(), '   ')
    expect(submit).toHaveProperty('disabled', true)
  })
})

// --- confirmar los tags ------------------------------------------------------

const API = 'http://127.0.0.1:8000'

const PREVIEW = {
  queries: [
    {
      kind: 'syntactic',
      tags: [
        { tag: 'sorted', source: 'seed' },
        { tag: 'items', source: 'seed' },
      ],
      q: 'sorted items language:python',
    },
    {
      kind: 'conceptual',
      tags: [
        { tag: 'sort_by_value', source: 'llm' },
        { tag: 'ranking', source: 'llm' },
      ],
      q: 'sort_by_value ranking language:python',
    },
    {
      kind: 'paradigm',
      tags: [{ tag: 'itemgetter', source: 'llm' }],
      q: 'itemgetter language:python',
    },
  ],
  llm: { error: null },
}

// Una respuesta que llega recien cuando el test la suelta
function held(body: JsonBodyType) {
  let release = () => {}
  const gate = new Promise<void>(resolve => {
    release = resolve
  })
  const respond = async () => {
    await gate
    return HttpResponse.json(body)
  }
  return { respond, release: () => release() }
}

const tagsOf = (kind: RegExp) =>
  within(screen.getByRole('list', { name: kind }))
    .getAllByRole('listitem')
    .map(item => item.textContent)

async function proposeTags(user: UserEvent, snippet = METHOD) {
  await user.click(snippetBox())
  await user.paste(snippet)
  await user.click(screen.getByRole('button', { name: /propose tags/i }))
}

describe('confirming the tags', () => {
  it('sends the snippet as written and shows the tags by query, each with its source', async () => {
    let sent: unknown
    server.use(
      http.post(`${API}/api/search/preview`, async ({ request }) => {
        sent = await request.json()
        return HttpResponse.json(PREVIEW)
      }),
    )
    const user = userEvent.setup()
    render(<Search />)

    await proposeTags(user)

    expect(await screen.findByRole('list', { name: /syntactic/i })).toBeTruthy()
    // Sin trim: la sangria de la primera linea es parte de un metodo pegado
    expect(sent).toEqual({ source: METHOD, language: 'python' })
    expect(tagsOf(/syntactic/i)).toEqual(['sorted AST', 'items AST'])
    expect(tagsOf(/conceptual/i)).toEqual(['sort_by_value model', 'ranking model'])
    expect(tagsOf(/paradigm/i)).toEqual(['itemgetter model'])
  })

  it('falls back to the AST tags, says the model was unavailable, and carries on', async () => {
    server.use(
      http.post(`${API}/api/search/preview`, () =>
        HttpResponse.json({
          queries: [
            {
              kind: 'tiers',
              tags: [
                { tag: 'sorted', source: 'seed' },
                { tag: 'rank', source: 'seed' },
              ],
              q: 'sorted rank language:python',
            },
          ],
          llm: { error: 'llm_unavailable' },
        }),
      ),
    )
    const user = userEvent.setup()
    render(<Search />)

    await proposeTags(user)

    expect(await screen.findByText(/model was unavailable/i)).toBeTruthy()
    expect(tagsOf(/syntax tree/i)).toEqual(['sorted AST', 'rank AST'])
    expect(screen.getByRole('button', { name: /search with these tags/i })).toHaveProperty('disabled', false)
  })

  it('goes back to the snippet, kept for editing', async () => {
    server.use(http.post(`${API}/api/search/preview`, () => HttpResponse.json(PREVIEW)))
    const user = userEvent.setup()
    render(<Search />)
    await proposeTags(user)
    expect(snippetBox().readOnly).toBe(true)

    await user.click(await screen.findByRole('button', { name: /change the snippet/i }))

    expect(snippetBox().value).toBe(METHOD)
    expect(snippetBox().readOnly).toBe(false)
    expect(screen.queryByRole('list', { name: /syntactic/i })).toBeNull()
  })

  it.each([
    ['nothing_to_search', /nothing distinctive/i],
    ['unsupported_language', /only python/i],
  ])('explains %s before any search runs', async (code, copy) => {
    let searched = false
    server.use(
      http.post(`${API}/api/search/preview`, () =>
        HttpResponse.json({ code, message: 'Backend wording that may change.' }, { status: 422 }),
      ),
      http.post(`${API}/api/search`, () => {
        searched = true
        return HttpResponse.json({}, { status: 500 })
      }),
    )
    const user = userEvent.setup()
    render(<Search />)

    await proposeTags(user)

    expect((await screen.findByRole('alert')).textContent).toMatch(copy)
    expect(screen.queryByText(/backend wording/i)).toBeNull()
    expect(searched).toBe(false)
  })

  it('counts the seconds while the tags load, with the controls locked', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const preview = held(PREVIEW)
    server.use(http.post(`${API}/api/search/preview`, preview.respond))
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<Search />)

    await proposeTags(user)
    const waiting = await screen.findByRole('status')
    expect(waiting.textContent).toMatch(/\b0 s/)
    await act(() => vi.advanceTimersByTimeAsync(3000))

    expect(waiting.textContent).toMatch(/\b3 s/)
    expect(snippetBox().readOnly).toBe(true)
    expect(screen.getByRole('button', { name: /propose tags/i })).toHaveProperty('disabled', true)
    expect(screen.getByLabelText(/attach a \.py file/i)).toHaveProperty('disabled', true)

    preview.release()
    expect(await screen.findByRole('list', { name: /syntactic/i })).toBeTruthy()
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('reports an unreachable backend as such', async () => {
    server.use(http.post(`${API}/api/search/preview`, () => HttpResponse.error()))
    const user = userEvent.setup()
    render(<Search />)

    await proposeTags(user)

    expect((await screen.findByRole('alert')).textContent).toMatch(/isn't answering at http:\/\/127\.0\.0\.1:8000/)
  })
})
