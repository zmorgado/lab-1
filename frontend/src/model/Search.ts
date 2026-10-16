import type { PreviewResponse } from '@/jsons/PreviewResponse'
import type { ConfirmedTagBody } from '@/jsons/SearchRequest'
import type { SearchResponse } from '@/jsons/SearchResponse'
import type { RepositoryMatches, SearchOutcome, SubtreeMatch } from '@/types/SearchOutcome'
import type { TagPreview } from '@/types/TagPreview'

// La frontera entre las formas crudas del backend (jsons/) y las del dominio (types/)

export const toTagPreview = (raw: PreviewResponse): TagPreview => ({
  queries: raw.queries.map(query => ({
    kind: query.kind,
    tags: query.tags.map(tag => ({ text: tag.tag, source: tag.source === 'llm' ? 'model' : 'ast' })),
  })),
  modelError: raw.llm.error,
})

// La busqueda corre con exactamente los tags que se mostraron
export const toConfirmedTags = (preview: TagPreview): ConfirmedTagBody[] =>
  preview.queries.flatMap(query => query.tags.map(tag => ({ tag: tag.text, kind: query.kind })))

// Cada resultado es un subarbol que puede estar en varios repos (mismo blob). Va
// una sola vez, bajo el primero de sus `locations`, y nombra a los demas: asi un
// fork no repite grupos enteros
export function toSearchOutcome(raw: SearchResponse): SearchOutcome {
  const byRepo = new Map<string, Map<string, SubtreeMatch[]>>()
  for (const result of raw.results) {
    const [home, ...others] = result.locations
    if (!home) continue
    const files = byRepo.get(home.repo) ?? new Map<string, SubtreeMatch[]>()
    byRepo.set(home.repo, files)
    const subtrees = files.get(home.path) ?? []
    files.set(home.path, subtrees)
    subtrees.push({
      name: result.parent ? `${result.parent}.${result.name}` : result.name,
      startLine: result.start_line,
      endLine: result.end_line,
      cosine: result.score,
      url: home.html_url && `${home.html_url}#L${result.start_line}-L${result.end_line}`,
      code: result.code,
      alsoIn: [...new Set(others.map(location => location.repo))].filter(repo => repo !== home.repo),
    })
  }

  const repositories: RepositoryMatches[] = [...byRepo].map(([repo, files]) => {
    const ordered = [...files]
      .map(([path, subtrees]) => {
        const sorted = subtrees.toSorted(
          (a, b) => b.cosine - a.cosine || byText(a.name, b.name) || a.startLine - b.startLine,
        )
        return { path, best: sorted[0].cosine, subtrees: sorted }
      })
      .sort((a, b) => b.best - a.best || byText(a.path, b.path))
    return { repo, best: ordered[0].best, files: ordered }
  })
  return { repositories: repositories.sort((a, b) => b.best - a.best || byText(a.repo, b.repo)) }
}

// A igualdad de coseno, por nombre: el orden no depende del que llego primero
const byText = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)
