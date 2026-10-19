import { useState, type FormEvent } from 'react'
import Button from '@/components/Button'
import StepHeading from '@/components/StepHeading'
import { AST_KIND, MAX_TAG_LENGTH } from '@/constants/tags'
import type { TagGroup, TagPreview } from '@/types/TagPreview'
import { modelFallbackCopy } from '@/utility/ErrorCopy'

const KINDS = new Map([
  ['syntactic', { label: 'Syntactic', note: 'The names a near-literal copy would share.' }],
  ['conceptual', { label: 'Conceptual', note: 'What the code is for, in the words programmers use.' }],
  ['paradigm', { label: 'Paradigm', note: 'Other ways to write the same thing.' }],
  [AST_KIND, { label: 'From the syntax tree', note: 'Its own names and words first, then calls, then imports.' }],
])

const SOURCE_LABELS = { ast: 'AST', model: 'model', you: 'you' } as const

type TagConfirmationProps = {
  preview: TagPreview
  onToggle: (kind: string, text: string) => void
  onAdd: (kind: string, text: string) => void
  onConfirm: () => void
  onBack: () => void
  locked: boolean
  showActions: boolean
}

export default function TagConfirmation({
  preview,
  onToggle,
  onAdd,
  onConfirm,
  onBack,
  locked,
  showActions,
}: TagConfirmationProps) {
  const astOnly = preview.groups.every(group => group.kind === AST_KIND)
  const nothingSelected = preview.groups.every(group => group.tags.every(tag => !tag.selected))

  return (
    <section aria-labelledby="tags-heading" className="mt-16">
      <StepHeading id="tags-heading" step={2}>
        Tags
      </StepHeading>
      <p className="max-w-prose text-base text-pencil">
        Each group runs as one query of up to 6 tags, and a file has to contain every tag in it: more
        tags find fewer, closer files. Select the ones to search with and add your own. Each says
        whether it came from the snippet's syntax tree (AST), the model, or you.
      </p>
      {astOnly && (
        <p className="mt-3 max-w-prose text-base text-pencil">{modelFallbackCopy(preview.modelError)}</p>
      )}
      {preview.textScan && (
        <p className="mt-3 max-w-prose text-base text-pencil">
          The snippet didn't parse as Python, so its AST tags come from a scan of the text instead.
        </p>
      )}

      <div className="mt-6 grid gap-8">
        {preview.groups.map(group => (
          <Group key={group.kind} group={group} onToggle={onToggle} onAdd={onAdd} locked={locked} editable={showActions} />
        ))}
      </div>

      {showActions && (
        <>
          <div className="mt-8 flex flex-wrap items-center gap-2">
            <Button primary onClick={onConfirm} disabled={locked || nothingSelected}>
              Search with these tags <span aria-hidden="true">▸</span>
            </Button>
            <Button onClick={onBack} disabled={locked}>
              <span aria-hidden="true">◂</span> Change the snippet
            </Button>
          </div>
          {nothingSelected && <p className="mt-3 text-base text-pencil">Select at least one tag to search with.</p>}
        </>
      )}
    </section>
  )
}

type GroupProps = {
  group: TagGroup
  onToggle: (kind: string, text: string) => void
  onAdd: (kind: string, text: string) => void
  locked: boolean
  editable: boolean
}

function Group({ group, onToggle, onAdd, locked, editable }: GroupProps) {
  const [draft, setDraft] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const kind = KINDS.get(group.kind)
  const label = kind?.label ?? group.kind
  const headingId = `kind-${group.kind}`

  function add(event: FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!text) return
    // Las comillas ya delimitan las frases en la query: adentro de un tag la romperian
    if (text.includes('"')) {
      setNote("Double quotes can't go into a tag.")
      return
    }
    onAdd(group.kind, text)
    setDraft('')
    setNote(null)
  }

  return (
    <div>
      <h3 id={headingId} className="font-mono text-sm font-medium">
        {label}
      </h3>
      <p className="text-base text-pencil">{kind?.note}</p>
      {group.tags.length > 0 && (
        <ul aria-labelledby={headingId} className="mt-2 flex flex-wrap gap-2">
          {group.tags.map(tag => (
            <li key={tag.text}>
              <button
                type="button"
                aria-pressed={tag.selected}
                disabled={locked || !editable}
                onClick={() => onToggle(group.kind, tag.text)}
                className={`min-h-11 rounded-xs border px-2 py-1 text-left font-mono text-sm break-all transition-colors
                  enabled:cursor-pointer enabled:hover:border-pencil
                  ${tag.selected ? 'border-pencil text-ink' : 'border-rule text-pencil'}`}
              >
                {tag.text} <span className="text-xs text-pencil">{SOURCE_LABELS[tag.source]}</span>
                {tag.selected && group.dropped.includes(tag.text) && (
                  <span className="text-xs text-pencil"> · won't fit</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      {editable && (
        <form onSubmit={add} className="mt-2 flex flex-wrap items-center gap-2">
          <input
            aria-label={`Add a tag to ${label}`}
            value={draft}
            onChange={event => setDraft(event.target.value)}
            disabled={locked}
            maxLength={MAX_TAG_LENGTH}
            spellCheck={false}
            autoCapitalize="off"
            placeholder="Add a tag"
            className="min-h-11 w-56 max-w-full rounded-xs border border-rule bg-transparent px-2 font-mono text-sm
                       text-ink transition-colors placeholder:text-pencil focus:border-pencil focus:outline-none"
          />
          <Button type="submit" disabled={locked || !draft.trim()}>
            Add
          </Button>
        </form>
      )}
      {note && <p className="mt-2 text-base text-pencil">{note}</p>}
    </div>
  )
}
