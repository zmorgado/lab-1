import Button from '@/components/Button'
import StepHeading from '@/components/StepHeading'
import type { TagPreview } from '@/types/TagPreview'

const KIND_LABELS: Record<string, string> = {
  syntactic: 'Syntactic',
  conceptual: 'Conceptual',
  paradigm: 'Paradigm',
  tiers: 'From the syntax tree',
}

const KIND_NOTES: Record<string, string> = {
  syntactic: 'The names a near-literal copy would share.',
  conceptual: 'What the code is for, in the words programmers use.',
  paradigm: 'Other ways to write the same thing.',
  tiers: 'APIs first, then names, then docstring words.',
}

const SOURCE_LABELS = { ast: 'AST', model: 'model' } as const

type TagConfirmationProps = {
  preview: TagPreview
  onConfirm: () => void
  onBack: () => void
  // Mientras corre la busqueda los botones se ven pero no responden
  locked: boolean
  showActions: boolean
}

export default function TagConfirmation({ preview, onConfirm, onBack, locked, showActions }: TagConfirmationProps) {
  const astOnly = preview.queries.every(query => query.kind === 'tiers')

  return (
    <section aria-labelledby="tags-heading" className="mt-16">
      <StepHeading id="tags-heading" step={2}>
        Tags
      </StepHeading>
      <p className="max-w-prose text-base text-pencil">
        The search runs one query per group, on exactly these tags. Each one says whether it came from
        the snippet's syntax tree (AST) or from the model.
      </p>
      {astOnly && (
        <p className="mt-3 max-w-prose text-base text-pencil">
          {preview.modelError
            ? 'The model was unavailable, so these tags come from the syntax tree alone, in one query instead of three.'
            : 'The model found nothing worth searching for, so these tags come from the syntax tree alone.'}
        </p>
      )}

      <div className="mt-6 grid gap-6">
        {preview.queries.map(query => (
          <div key={query.kind}>
            <h3 id={`kind-${query.kind}`} className="font-mono text-sm font-medium">
              {KIND_LABELS[query.kind] ?? query.kind}
            </h3>
            {KIND_NOTES[query.kind] && <p className="text-base text-pencil">{KIND_NOTES[query.kind]}</p>}
            <ul aria-labelledby={`kind-${query.kind}`} className="mt-2 flex flex-wrap gap-2">
              {query.tags.map(tag => (
                <li key={tag.text} className="rounded-xs border border-rule px-2 py-1 font-mono text-sm break-all">
                  {tag.text} <span className="text-xs text-pencil">{SOURCE_LABELS[tag.source]}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {showActions && (
        <div className="mt-6 flex flex-wrap items-center gap-2">
          <Button primary onClick={onConfirm} disabled={locked}>
            Search with these tags <span aria-hidden="true">▸</span>
          </Button>
          <Button onClick={onBack} disabled={locked}>
            <span aria-hidden="true">◂</span> Change the snippet
          </Button>
        </div>
      )}
    </section>
  )
}
