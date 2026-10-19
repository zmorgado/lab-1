import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
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

type SentTag = { tag: string; kind: string }

const pooled = (kind: string, source: 'seed' | 'llm', ...tags: string[]) =>
  tags.map(tag => ({ tag, kind, source, selected: true }))

const PREVIEW = {
  pool: [
    ...pooled('syntactic', 'seed', 'sorted', 'items'),
    ...pooled('conceptual', 'llm', 'sort_by_value', 'ranking'),
    ...pooled('paradigm', 'llm', 'itemgetter'),
  ],
  queries: [
    { kind: 'syntactic', tags: ['sorted', 'items'], dropped: [], q: 'sorted items language:python' },
    { kind: 'conceptual', tags: ['sort_by_value', 'ranking'], dropped: [], q: 'sort_by_value ranking language:python' },
    { kind: 'paradigm', tags: ['itemgetter'], dropped: [], q: 'itemgetter language:python' },
  ],
  llm: { error: null },
  is_fallback: false,
}

// El rearmado sin el modelo: cada tag entra en su query, salvo los que diga el test
function replanned(tags: SentTag[], dropped: string[]) {
  const kinds = [...new Set(tags.map(tag => tag.kind))]
  return {
    pool: [],
    queries: kinds.map(kind => {
      const texts = tags.filter(tag => tag.kind === kind).map(tag => tag.tag)
      return {
        kind,
        tags: texts.filter(text => !dropped.includes(text)),
        dropped: texts.filter(text => dropped.includes(text)),
        q: `${texts.join(' ')} language:python`,
      }
    }),
    llm: { error: null },
    is_fallback: false,
  }
}

// El preview del backend: sin tags propone el pool, con tags rearma las queries
function previewRoute(initial: JsonBodyType, dropped: string[] = []) {
  return http.post(`${API}/api/search/preview`, async ({ request }) => {
    const body = (await request.json()) as { tags?: SentTag[] }
    return HttpResponse.json(body.tags ? replanned(body.tags, dropped) : initial)
  })
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
          pool: pooled('tiers', 'seed', 'sorted', 'rank'),
          queries: [{ kind: 'tiers', tags: ['sorted', 'rank'], dropped: [], q: 'sorted rank language:python' }],
          llm: { error: 'llm_unavailable' },
          is_fallback: false,
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
    server.use(previewRoute(PREVIEW))
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

function result(
  rank: number,
  score: number,
  name: string,
  lines: [number, number],
  locations: Location[],
  parent: string | null = null,
) {
  return {
    rank,
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
    result(5, 0.8, 'top', [1, 2], [at('b-org/fast', 'src/zz.py', false)]),
    result(4, 0.85, 'pick', [3, 4], [at('c-org/tie', 'x.py')]),
    result(3, 0.85, 'sort_items', [3, 4], [at('a-org/slow', 'lib/sort.py')]),
    result(2, 0.88, 'rank', [20, 25], [at('b-org/fast', 'src/rank.py')], 'Ranker'),
    result(1, 0.91, 'rank', [10, 11], [at('b-org/fast', 'src/rank.py'), at('d-org/fork', 'src/rank.py'), at('e-org/copy', 'rank.py')]),
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

// Despues de los resultados la pagina pide las explicaciones (#43)
const noExplanations = () =>
  http.post(`${API}/api/search/explain`, () => HttpResponse.json({ explanations: [] }))

function stubSearch(body: JsonBodyType) {
  server.use(
    previewRoute(PREVIEW),
    http.post(`${API}/api/search`, () => HttpResponse.json(body)),
    noExplanations(),
  )
}

describe('reading the results', () => {
  it('searches with exactly the confirmed tags and orders repositories, files and subtrees by cosine', async () => {
    let sent: unknown
    server.use(
      previewRoute(PREVIEW),
      http.post(`${API}/api/search`, async ({ request }) => {
        sent = await request.json()
        return HttpResponse.json(RESULTS)
      }),
      noExplanations(),
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
      previewRoute(PREVIEW),
      http.post(`${API}/api/search`, search.respond),
      noExplanations(),
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
      previewRoute(PREVIEW),
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
    await proposeTags(user)
    await user.click(await screen.findByRole('button', { name: /^items/ }))
    await user.click(screen.getByRole('button', { name: /search with these tags/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/went wrong.*HTTP 403/)
    expect(screen.queryByText(/rate limit exceeded/i)).toBeNull()

    await user.click(screen.getByRole('button', { name: /back to the tags/i }))
    expect(screen.getByRole('button', { name: /search with these tags/i })).toHaveProperty('disabled', false)
    expect(screen.queryByRole('alert')).toBeNull()
    // Volver a los tags no pierde lo que se edito
    expect(screen.getByRole('button', { name: /^items/ }).getAttribute('aria-pressed')).toBe('false')
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

// --- editar los tags (#22) ----------------------------------------------------

// Una busqueda que guarda lo que se le mando y no encuentra nada
function recordSearch() {
  const sent: { tags?: SentTag[] } = {}
  server.use(
    http.post(`${API}/api/search`, async ({ request }) => {
      Object.assign(sent, await request.json())
      return HttpResponse.json({ results: [] })
    }),
  )
  return sent
}

async function runSearch(user: UserEvent) {
  await user.click(screen.getByRole('button', { name: /search with these tags/i }))
  await screen.findByRole('region', { name: /results/i })
}

const addBox = (group: string) => screen.getByRole('textbox', { name: `Add a tag to ${group}` })

describe('editing the tags', () => {
  it('leaves a deselected tag out of the search', async () => {
    server.use(previewRoute(PREVIEW))
    const sent = recordSearch()
    const user = userEvent.setup()
    render(<Search />)
    await proposeTags(user)

    const items = await screen.findByRole('button', { name: /^items/ })
    await user.click(items)

    expect(items.getAttribute('aria-pressed')).toBe('false')
    await runSearch(user)
    expect(sent.tags).toEqual([
      { tag: 'sorted', kind: 'syntactic' },
      { tag: 'sort_by_value', kind: 'conceptual' },
      { tag: 'ranking', kind: 'conceptual' },
      { tag: 'itemgetter', kind: 'paradigm' },
    ])
  })

  it("adds a tag of the user's own to its group's query, even a group the model left empty", async () => {
    const withoutParadigm = {
      ...PREVIEW,
      pool: PREVIEW.pool.filter(tag => tag.kind !== 'paradigm'),
      queries: PREVIEW.queries.filter(query => query.kind !== 'paradigm'),
    }
    server.use(previewRoute(withoutParadigm))
    const sent = recordSearch()
    const user = userEvent.setup()
    render(<Search />)
    await proposeTags(user)

    await user.type(await screen.findByRole('textbox', { name: 'Add a tag to Paradigm' }), 'heapq{Enter}')

    expect(tagsOf(/paradigm/i)).toEqual(['heapq you'])
    await runSearch(user)
    expect(sent.tags).toContainEqual({ tag: 'heapq', kind: 'paradigm' })
  })

  it("marks a selected tag that won't fit its query", async () => {
    server.use(previewRoute(PREVIEW, ['top k']))
    const user = userEvent.setup()
    render(<Search />)
    await proposeTags(user)

    await user.type(await screen.findByRole('textbox', { name: 'Add a tag to Conceptual' }), 'top k{Enter}')

    expect(await within(screen.getByRole('list', { name: /conceptual/i })).findByText(/won't fit/)).toBeTruthy()
    expect(tagsOf(/conceptual/i)).toEqual(['sort_by_value model', 'ranking model', "top k you · won't fit"])
  })

  it("can't search with no tag selected", async () => {
    server.use(previewRoute(PREVIEW))
    const user = userEvent.setup()
    render(<Search />)
    await proposeTags(user)
    await screen.findByRole('list', { name: /syntactic/i })

    for (const tag of ['sorted', 'items', 'sort_by_value', 'ranking', 'itemgetter']) {
      await user.click(screen.getByRole('button', { name: new RegExp(`^${tag}`) }))
    }

    expect(screen.getByRole('button', { name: /search with these tags/i })).toHaveProperty('disabled', true)
    expect(screen.getByText(/select at least one tag/i)).toBeTruthy()
  })

  it('refuses a tag with a double quote', async () => {
    server.use(previewRoute(PREVIEW))
    const user = userEvent.setup()
    render(<Search />)
    await proposeTags(user)

    await user.type(await screen.findByRole('textbox', { name: 'Add a tag to Conceptual' }), 'say "hi"{Enter}')

    expect(screen.getByText(/double quotes/i)).toBeTruthy()
    expect(tagsOf(/conceptual/i)).toEqual(['sort_by_value model', 'ranking model'])
    expect(addBox('Conceptual')).toHaveProperty('value', 'say "hi"')
  })
})

describe('the pool', () => {
  it('offers the tags the model left out, switched off, and searches with one once picked', async () => {
    const withLeftOut = {
      ...PREVIEW,
      pool: [...PREVIEW.pool, { tag: 'rank_by_score', kind: 'syntactic', source: 'seed', selected: false }],
    }
    server.use(previewRoute(withLeftOut))
    const sent = recordSearch()
    const user = userEvent.setup()
    render(<Search />)
    await proposeTags(user)

    const offered = await screen.findByRole('button', { name: /^rank_by_score/ })
    expect(offered.getAttribute('aria-pressed')).toBe('false')
    await user.click(offered)

    await runSearch(user)
    expect(sent.tags).toContainEqual({ tag: 'rank_by_score', kind: 'syntactic' })
  })

  it("says when the snippet didn't parse and the tags come from a text scan", async () => {
    server.use(previewRoute({ ...PREVIEW, is_fallback: true }))
    const user = userEvent.setup()
    render(<Search />)

    await proposeTags(user)

    expect(await screen.findByText(/didn't parse/i)).toBeTruthy()
  })
})

// --- explicaciones (#43) -----------------------------------------------------

const RANKER_NOTE = {
  rank: 2,
  value: 'Scores each item once with `self.score`, then sorts the pairs.',
  suggestion: 'Sort with `key=self.score` instead of building pairs.',
  highlights: [
    { start: 22, end: 22 },
    { start: 24, end: 25 },
  ],
}

function stubExplained(explain: Parameters<typeof http.post>[1]) {
  server.use(
    previewRoute(PREVIEW),
    http.post(`${API}/api/search`, () => HttpResponse.json(RESULTS)),
    http.post(`${API}/api/search/explain`, explain),
  )
}

describe('explaining the results', () => {
  it('shows the results first, then what each match offers, a suggestion and the lines that matter', async () => {
    let sent: { source: string; results: unknown[] } | undefined
    const explain = held({ explanations: [RANKER_NOTE, { rank: 1, value: 'Same sort, no scoring.', suggestion: '', highlights: [] }] })
    stubExplained(async ({ request }) => {
      sent = (await request.json()) as typeof sent
      return explain.respond()
    })
    const user = userEvent.setup()
    render(<Search />)
    await searchWithTags(user)

    // Los resultados no esperan al modelo
    const method = await screen.findByRole('article', { name: 'Ranker.rank' })
    expect((await screen.findByRole('status')).textContent).toMatch(/reading each match/i)
    expect(within(method).queryByText('Value')).toBeNull()

    explain.release()

    expect(await within(method).findByText('Value')).toBeTruthy()
    expect(within(method).getByText(/scores each item once/i).textContent).toBe(RANKER_NOTE.value.replaceAll('`', ''))
    // Los nombres de codigo van en mono
    expect(within(method).getByText('self.score').tagName).toBe('CODE')
    expect(within(method).getByText('For your snippet')).toBeTruthy()
    // El subrayado tambien se dice, no solo se ve
    expect(within(method).getByLabelText(/underlined line 22, lines 24–25$/)).toBeTruthy()

    // Sin sugerencia no hay etiqueta; lo que el modelo no explico queda como estaba
    const rank = screen.getByRole('article', { name: 'rank' })
    expect(within(rank).getByText('Same sort, no scoring.')).toBeTruthy()
    expect(within(rank).queryByText('For your snippet')).toBeNull()
    expect(within(screen.getByRole('article', { name: 'top' })).queryByText('Value')).toBeNull()

    // El snippet viaja sin trim, y cada resultado con su puesto, donde se ve y su primera linea
    expect(sent?.source).toBe(METHOD)
    expect(sent?.results).toHaveLength(5)
    expect(sent?.results).toContainEqual({
      rank: 2,
      repo: 'b-org/fast',
      path: 'src/rank.py',
      name: 'Ranker.rank',
      start_line: 20,
      code: RANKER_RANK,
    })
  })

  it.each([
    ['llm_quota_exhausted', 429, /used up its quota/],
    ['llm_unavailable', 503, /isn't available/],
    ['llm_malformed_response', 502, /couldn't explain these matches this time/],
  ])('says plainly when the model fails with %s, and keeps the results', async (code, status, copy) => {
    stubExplained(() => HttpResponse.json({ code, message: 'Gemini answered something' }, { status }))
    const user = userEvent.setup()
    render(<Search />)
    await searchWithTags(user)

    expect(await within(resultsRegion()).findByText(copy)).toBeTruthy()
    expect(screen.queryByText(/gemini answered/i)).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getAllByRole('article')).toHaveLength(5)
  })

  it("doesn't call the model when nothing was found", async () => {
    let calls = 0
    server.use(
      previewRoute(PREVIEW),
      http.post(`${API}/api/search`, () => HttpResponse.json({ results: [] })),
      http.post(`${API}/api/search/explain`, () => {
        calls++
        return HttpResponse.json({ explanations: [] })
      }),
    )
    const user = userEvent.setup()
    render(<Search />)
    await searchWithTags(user)

    expect(await within(resultsRegion()).findByText(/nothing on github/i)).toBeTruthy()
    expect(calls).toBe(0)
  })

  it('drops a late explanation once a new search has started', async () => {
    const late = held({ explanations: [RANKER_NOTE] })
    let calls = 0
    stubExplained(() => (++calls === 1 ? late.respond() : HttpResponse.json({ explanations: [] })))
    const user = userEvent.setup()
    render(<Search />)
    await searchWithTags(user)
    await screen.findByRole('article', { name: 'Ranker.rank' })

    await user.click(screen.getByRole('button', { name: /new search/i }))
    await user.click(screen.getByRole('button', { name: /propose tags/i }))
    await user.click(await screen.findByRole('button', { name: /search with these tags/i }))
    const method = await screen.findByRole('article', { name: 'Ranker.rank' })
    await waitFor(() => expect(calls).toBe(2))

    late.release()
    await act(() => new Promise(resolve => setTimeout(resolve, 50)))

    expect(within(method).queryByText('Value')).toBeNull()
  })
})
