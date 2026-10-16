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

// --- resultados por repositorio ----------------------------------------------

const RANKER_RANK = [
  'def rank(self, items):',
  '    """Order the items by score."""',
  '    scored = [(self.score(i), i) for i in items]',
  '    # highest first',
  '    scored.sort(reverse=True)',
  '    return [i for _, i in scored]',
].join('\n')

type Location = { repo: string; path: string; html_url: string | null }

const at = (repo: string, path: string, linked = true): Location => ({
  repo,
  path,
  html_url: linked ? `https://github.com/${repo}/blob/abc123/${path}` : null,
})

function result(score: number, name: string, lines: [number, number], locations: Location[], parent: string | null = null) {
  return {
    rank: 0,
    score,
    sha: `sha-${name}-${lines[0]}`,
    locations,
    queries: [{ kind: 'syntactic', q: 'sorted items language:python' }],
    name,
    node: 'function_definition',
    parent,
    start_line: lines[0],
    end_line: lines[1],
    code: parent ? RANKER_RANK : `def ${name}(items):\n    return sorted(items)\n`,
  }
}

// Desordenados a proposito: el orden lo decide la pagina, no el que llegue
const RESULTS = {
  results: [
    result(0.8, 'top', [1, 2], [at('b-org/fast', 'src/zz.py', false)]),
    result(0.85, 'pick', [3, 4], [at('c-org/tie', 'x.py')]),
    result(0.85, 'sort_items', [3, 4], [at('a-org/slow', 'lib/sort.py')]),
    result(0.88, 'rank', [20, 25], [at('b-org/fast', 'src/rank.py')], 'Ranker'),
    result(0.91, 'rank', [10, 11], [at('b-org/fast', 'src/rank.py'), at('d-org/fork', 'src/rank.py'), at('e-org/copy', 'rank.py')]),
  ],
}

const resultsRegion = () => screen.getByRole('region', { name: /results/i })
const headings = (level: number) =>
  within(resultsRegion())
    .getAllByRole('heading', { level })
    .map(heading => heading.textContent)

async function searchWithTags(user: UserEvent) {
  await proposeTags(user)
  await user.click(await screen.findByRole('button', { name: /search with these tags/i }))
}

function stubSearch(body: JsonBodyType) {
  server.use(
    http.post(`${API}/api/search/preview`, () => HttpResponse.json(PREVIEW)),
    http.post(`${API}/api/search`, () => HttpResponse.json(body)),
  )
}

describe('reading the results', () => {
  it('searches with exactly the confirmed tags and orders repositories, files and subtrees by cosine', async () => {
    let sent: unknown
    server.use(
      http.post(`${API}/api/search/preview`, () => HttpResponse.json(PREVIEW)),
      http.post(`${API}/api/search`, async ({ request }) => {
        sent = await request.json()
        return HttpResponse.json(RESULTS)
      }),
    )
    const user = userEvent.setup()
    render(<Search />)

    await searchWithTags(user)

    expect(await screen.findByRole('region', { name: /results/i })).toBeTruthy()
    expect(sent).toEqual({
      source: METHOD,
      language: 'python',
      tags: [
        { tag: 'sorted', kind: 'syntactic' },
        { tag: 'items', kind: 'syntactic' },
        { tag: 'sort_by_value', kind: 'conceptual' },
        { tag: 'ranking', kind: 'conceptual' },
        { tag: 'itemgetter', kind: 'paradigm' },
      ],
    })
    // Repos por su mejor coseno; a igualdad (0.85), por nombre
    expect(headings(3)).toEqual(['b-org/fast', 'a-org/slow', 'c-org/tie'])
    expect(headings(4)).toEqual(['src/rank.py', 'src/zz.py', 'lib/sort.py', 'x.py'])
    expect(headings(5)).toEqual(['rank', 'Ranker.rank', 'top', 'sort_items', 'pick'])
  })
})

describe('a result', () => {
  it('shows its name, line range, cosine, a link to those lines and its code with the original numbers', async () => {
    stubSearch(RESULTS)
    const user = userEvent.setup()
    render(<Search />)
    await searchWithTags(user)

    const method = await screen.findByRole('article', { name: 'Ranker.rank' })

    expect(within(method).getByText('0.880').parentElement?.textContent).toBe('cosine 0.880')
    expect(within(method).getByRole('link', { name: /lines 20–25/ }).getAttribute('href')).toBe(
      'https://github.com/b-org/fast/blob/abc123/src/rank.py#L20-L25',
    )
    const code = within(method).getByLabelText(/code of Ranker\.rank/i)
    expect(code.textContent).toContain('scored.sort(reverse=True)')
    expect(within(code).getAllByText(/^\d+$/).map(number => number.textContent)).toEqual([
      '20',
      '21',
      '22',
      '23',
      '24',
      '25',
    ])
  })

  it('shows the line range as plain text when GitHub gave no link', async () => {
    stubSearch(RESULTS)
    const user = userEvent.setup()
    render(<Search />)
    await searchWithTags(user)

    const top = await screen.findByRole('article', { name: 'top' })

    expect(within(top).getByText('lines 1–2')).toBeTruthy()
    expect(within(top).queryByRole('link')).toBeNull()
  })
})

describe('a subtree in several repositories', () => {
  it('appears once, under the first, and lists the others', async () => {
    stubSearch(RESULTS)
    const user = userEvent.setup()
    render(<Search />)
    await searchWithTags(user)

    const rank = await screen.findByRole('article', { name: 'rank' })

    expect(screen.getAllByRole('article', { name: 'rank' })).toHaveLength(1)
    expect(within(rank).getByText(/also in/).textContent).toBe('also in d-org/fork, e-org/copy')
    expect(headings(3)).not.toContain('d-org/fork')
  })
})

describe('the end of a search', () => {
  it('says plainly when nothing was found, not as an error', async () => {
    stubSearch({ results: [] })
    const user = userEvent.setup()
    render(<Search />)
    await searchWithTags(user)

    expect(await within(await screen.findByRole('region', { name: /results/i })).findByText(/nothing on github/i)).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('counts the seconds while searching, with the controls locked', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const search = held(RESULTS)
    server.use(
      http.post(`${API}/api/search/preview`, () => HttpResponse.json(PREVIEW)),
      http.post(`${API}/api/search`, search.respond),
    )
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<Search />)

    await searchWithTags(user)
    const waiting = await screen.findByRole('status')
    await act(() => vi.advanceTimersByTimeAsync(2000))

    expect(waiting.textContent).toMatch(/searching github.*\b2 s/i)
    expect(screen.getByRole('button', { name: /search with these tags/i })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: /change the snippet/i })).toHaveProperty('disabled', true)
    expect(snippetBox().readOnly).toBe(true)

    search.release()
    expect(await screen.findByRole('region', { name: /results/i })).toBeTruthy()
  })

  it("never shows GitHub's own text when the search fails, and can go back to the tags", async () => {
    server.use(
      http.post(`${API}/api/search/preview`, () => HttpResponse.json(PREVIEW)),
      // Un error de GitHub viaja con su status y su body, sin code nuestro
      http.post(`${API}/api/search`, () =>
        HttpResponse.json(
          { message: 'API rate limit exceeded for installation ID 4242.', documentation_url: 'https://docs.github.com' },
          { status: 403 },
        ),
      ),
    )
    const user = userEvent.setup()
    render(<Search />)
    await searchWithTags(user)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/went wrong.*HTTP 403/)
    expect(screen.queryByText(/rate limit exceeded/i)).toBeNull()

    await user.click(screen.getByRole('button', { name: /back to the tags/i }))
    expect(screen.getByRole('button', { name: /search with these tags/i })).toHaveProperty('disabled', false)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('starts a new search from the snippet, kept for editing', async () => {
    stubSearch(RESULTS)
    const user = userEvent.setup()
    render(<Search />)
    await searchWithTags(user)

    await user.click(await screen.findByRole('button', { name: /new search/i }))

    expect(snippetBox().value).toBe(METHOD)
    expect(snippetBox().readOnly).toBe(false)
    expect(screen.queryByRole('region', { name: /results/i })).toBeNull()
  })
})
