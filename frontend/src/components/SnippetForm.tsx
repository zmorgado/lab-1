import { useState, type ChangeEvent, type FormEvent } from 'react'
import Button, { BUTTON } from '@/components/Button'
import StepHeading from '@/components/StepHeading'

type SnippetFormProps = {
  snippet: string
  onChange: (snippet: string) => void
  onSubmit: () => void
  locked: boolean
  showActions: boolean
}

export default function SnippetForm({ snippet, onChange, onSubmit, locked, showActions }: SnippetFormProps) {
  const [attachNote, setAttachNote] = useState<string | null>(null)

  async function attach(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0]
    event.currentTarget.value = ''
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.py')) {
      setAttachNote(`Only .py files can be attached, and ${file.name} isn't one.`)
      return
    }
    setAttachNote(null)
    // El texto tal cual: la sangria de la primera linea es parte del snippet
    onChange(await file.text())
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (snippet.trim()) onSubmit()
  }

  return (
    <form aria-labelledby="snippet-heading" onSubmit={submit}>
      <StepHeading id="snippet-heading" step={1}>
        Snippet
      </StepHeading>
      <textarea
        aria-labelledby="snippet-heading"
        value={snippet}
        onChange={event => onChange(event.target.value)}
        readOnly={locked}
        rows={12}
        wrap="off"
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        placeholder="Paste a Python function or class"
        className="block w-full resize-y rounded-xs border border-rule bg-transparent p-3 font-mono text-sm
                   leading-relaxed text-ink transition-colors placeholder:text-pencil read-only:text-pencil
                   focus:border-pencil focus:outline-none"
      />
      {showActions && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button primary type="submit" disabled={locked || !snippet.trim()}>
            Propose tags <span aria-hidden="true">▸</span>
          </Button>
          <label
            className={`${BUTTON} border-rule text-pencil has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-signal
                        has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60`}
          >
            Attach a .py file
            <input type="file" accept=".py" className="sr-only" onChange={attach} disabled={locked} />
          </label>
        </div>
      )}
      {attachNote && <p className="mt-3 text-base text-pencil">{attachNote}</p>}
    </form>
  )
}
