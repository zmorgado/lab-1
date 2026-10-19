import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Highlight } from 'prism-react-renderer'
import Button, { BUTTON } from '@/components/Button'
import StepHeading from '@/components/StepHeading'
import { CODE_THEME } from '@/utility/CodeTheme'

type SnippetFormProps = {
  snippet: string
  onChange: (snippet: string) => void
  onSubmit: () => void
  locked: boolean
  showActions: boolean
}

export default function SnippetForm({ snippet, onChange, onSubmit, locked, showActions }: SnippetFormProps) {
  const [attachNote, setAttachNote] = useState<string | null>(null)
  // El textarea es el que tiene el texto y el scroll; el color es una capa
  // detras con la misma tipografia, y se mueve con el
  const boxRef = useRef<HTMLTextAreaElement>(null)
  const colorRef = useRef<HTMLPreElement>(null)

  function syncScroll() {
    const box = boxRef.current
    const color = colorRef.current
    if (box && color) {
      color.scrollTop = box.scrollTop
      color.scrollLeft = box.scrollLeft
    }
  }

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
      <div className="relative">
        {/* La capa de color: el mismo texto, tokenizado con el Om Theme. Va
            aria-hidden y sin punteros porque el que manda es el textarea */}
        <pre
          ref={colorRef}
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 m-0 overflow-hidden rounded-xs border border-transparent p-3
                     font-mono text-sm leading-relaxed"
        >
          <Highlight theme={CODE_THEME} code={snippet.replace(/\n$/, '')} language="python">
            {({ tokens, getTokenProps }) => (
              <code className="block min-w-max whitespace-pre">
                {tokens.map((line, index) => (
                  <div key={index}>
                    {line.map((token, key) => (
                      <span key={key} {...getTokenProps({ token })} />
                    ))}
                  </div>
                ))}
              </code>
            )}
          </Highlight>
        </pre>
        <textarea
          ref={boxRef}
          aria-labelledby="snippet-heading"
          value={snippet}
          onChange={event => onChange(event.target.value)}
          onScroll={syncScroll}
          readOnly={locked}
          rows={12}
          wrap="off"
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          placeholder="Paste a Python function or class"
          // El texto va transparente: el color lo pone la capa de atras
          className="relative block w-full resize-y rounded-xs border border-rule bg-transparent p-3 font-mono text-sm
                     leading-relaxed text-transparent caret-signal transition-colors selection:bg-signal/30
                     placeholder:text-pencil focus:border-pencil focus:outline-none"
        />
      </div>
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
