import { AST_KIND, MODEL_KINDS } from '@/constants/tags'
import type { ExplainItemBody } from '@/jsons/ExplainRequest'
import type { ExplainResponse } from '@/jsons/ExplainResponse'
import type { PreviewResponse } from '@/jsons/PreviewResponse'
import type { ConfirmedTagBody } from '@/jsons/SearchRequest'
import type { SearchResponse } from '@/jsons/SearchResponse'
import type { Explanation } from '@/types/Explanations'
import type { FoundBy, RepositoryMatches, SearchOutcome, SubtreeMatch } from '@/types/SearchOutcome'
import type { TagPreview } from '@/types/TagPreview'

// La frontera entre las formas crudas del backend (jsons/) y las del dominio (types/)

export function toTagPreview(raw: PreviewResponse): TagPreview {
  // Sin el modelo hay una sola query, la del AST; con el, las tres aunque esten vacias
  const kinds = raw.pool.some(tag => tag.kind === AST_KIND) ? [AST_KIND] : MODEL_KINDS
  const preview = {
    groups: kinds.map(kind => ({
      kind,
      tags: raw.pool
        .filter(tag => tag.kind === kind)
        .map(tag => ({
          text: tag.tag,
          source: tag.source === 'llm' ? ('model' as const) : ('ast' as const),
          selected: tag.selected,
        })),
      dropped: [],
    })),
    modelError: raw.llm.error,
    textScan: raw.is_fallback,
  }
  return withDropped(preview, raw)
}

// Lo que no entra en cada query, segun el ultimo rearmado del backend
export const withDropped = (preview: TagPreview, raw: PreviewResponse): TagPreview => ({
  ...preview,
  groups: preview.groups.map(group => ({
    ...group,
    dropped: raw.queries.find(query => query.kind === group.kind)?.dropped ?? [],
  })),
})

// La busqueda corre con exactamente los tags seleccionados
export const toConfirmedTags = (preview: TagPreview): ConfirmedTagBody[] =>
  preview.groups.flatMap(group =>
    group.tags.filter(tag => tag.selected).map(tag => ({ tag: tag.text, kind: group.kind })),
  )

// Cada resultado es un subarbol que puede estar en varios repos (mismo blob). Va
// una sola vez, bajo el primero de sus `locations`, y nombra a los demas: asi un
// fork no repite grupos enteros
export function toSearchOutcome(raw: SearchResponse): SearchOutcome {
  type FileGroup = { foundBy: FoundBy[]; subtrees: SubtreeMatch[] }
  const byRepo = new Map<string, Map<string, FileGroup>>()
  for (const result of raw.results) {
    const [home, ...others] = result.locations
    if (!home) continue
    const files = byRepo.get(home.repo) ?? new Map<string, FileGroup>()
    byRepo.set(home.repo, files)
    // Las queries son del archivo (mismo sha), asi que todos sus subarboles traen las mismas
    const file = files.get(home.path) ?? { foundBy: result.queries, subtrees: [] }
    files.set(home.path, file)
    file.subtrees.push({
      rank: result.rank,
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
      .map(([path, { foundBy, subtrees }]) => {
        const sorted = subtrees.toSorted(
          (a, b) => b.cosine - a.cosine || byText(a.name, b.name) || a.startLine - b.startLine,
        )
        return { path, bestCosine: sorted[0].cosine, foundBy, subtrees: sorted }
      })
      .sort((a, b) => b.bestCosine - a.bestCosine || byText(a.path, b.path))
    return { repo, bestCosine: ordered[0].bestCosine, files: ordered }
  })
  return {
    repositories: repositories.sort((a, b) => b.bestCosine - a.bestCosine || byText(a.repo, b.repo)),
  }
}

// Los resultados como los explica el backend (#43), bajo el repo y el path
// donde los ve el usuario
export const toExplainItems = (outcome: SearchOutcome): ExplainItemBody[] =>
  outcome.repositories.flatMap(({ repo, files }) =>
    files.flatMap(({ path, subtrees }) =>
      subtrees.map(({ rank, name, startLine, code }) => ({ rank, repo, path, name, start_line: startLine, code })),
    ),
  )

export const toExplanations = (raw: ExplainResponse): Map<number, Explanation> =>
  new Map(
    raw.explanations.map(({ rank, value, suggestion, highlights }) => [
      rank,
      { value, suggestion: suggestion.trim() || null, highlights },
    ]),
  )

// A igualdad de coseno, por nombre: el orden no depende del que llego primero
const byText = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)
