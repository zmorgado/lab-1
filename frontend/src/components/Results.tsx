import { useId, type ReactNode } from 'react'
import CodeBlock from '@/components/CodeBlock'
import Elapsed from '@/components/Elapsed'
import StepHeading from '@/components/StepHeading'
import type { Explanation, Explanations } from '@/types/Explanations'
import type { SearchOutcome, SubtreeMatch } from '@/types/SearchOutcome'
import { explanationCopy } from '@/utility/ErrorCopy'

type ResultsProps = { outcome: SearchOutcome; explanations: Explanations; actions: ReactNode }

export default function Results({ outcome, explanations, actions }: ResultsProps) {
  const notes = explanations.status === 'ready' ? explanations.byRank : null
  return (
    <section aria-labelledby="results-heading" className="mt-16">
      <StepHeading id="results-heading" step={3}>
        Results
      </StepHeading>
      {outcome.repositories.length === 0 ? (
        // Una oracion comun: no encontrar nada no es un error
        <p className="max-w-prose">
          Nothing on GitHub came close enough to this snippet with these tags. A snippet with more names of
          its own usually finds more.
        </p>
      ) : (
        <p className="max-w-prose text-base text-pencil">
          Repositories in order of their closest match. The cosine compares each piece of code with yours
          in UniXcoder's embedding space: the closer to 1, the more alike they are.
        </p>
      )}
      {/* Las explicaciones llegan despues, sin frenar la lista (#43) */}
      {explanations.status === 'loading' && <Elapsed>Reading each match against your snippet</Elapsed>}
      {notes && (
        <p className="mt-2 max-w-prose text-base text-pencil">
          The notes under each match are a language model's reading of the code, not a check: the cosine
          still sets the order. The lines it found most interesting are underlined.
        </p>
      )}
      {/* Una oracion comun, como no encontrar nada: fallo el modelo, no el paso */}
      {explanations.status === 'failed' && (
        <p className="mt-2 max-w-prose text-base text-pencil">{explanationCopy(explanations.error)}</p>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-2">{actions}</div>

      {outcome.repositories.map(repository => (
        <div key={repository.repo} className="mt-8 border-t border-rule pt-6">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4">
            <h3 className="font-mono text-base font-medium break-all">{repository.repo}</h3>
            <p className="font-mono text-sm text-pencil">best cosine {repository.bestCosine.toFixed(3)}</p>
          </div>
          {repository.files.map(file => (
            <div key={file.path} className="mt-4">
              <h4 className="font-mono text-sm text-pencil break-all">{file.path}</h4>
              {file.subtrees.map(subtree => (
                <Subtree
                  key={`${subtree.startLine}-${subtree.name}`}
                  subtree={subtree}
                  explanation={notes?.get(subtree.rank)}
                />
              ))}
            </div>
          ))}
        </div>
      ))}
    </section>
  )
}

function Subtree({ subtree, explanation }: { subtree: SubtreeMatch; explanation?: Explanation }) {
  const id = useId()
  const lines = `lines ${subtree.startLine}–${subtree.endLine}`
  // El subrayado tambien se dice en el label: el color solo no alcanza
  const underlined = explanation?.highlights
    .map(({ start, end }) => (start === end ? `line ${start}` : `lines ${start}–${end}`))
    .join(', ')

  return (
    <article aria-labelledby={id} className="mt-5">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-sm">
        <h5 id={id} className="font-medium break-all">
          {subtree.name}
        </h5>
        {subtree.url ? (
          <a href={subtree.url} target="_blank" rel="noreferrer">
            {lines} <span aria-hidden="true">↗</span>
          </a>
        ) : (
          <span className="text-pencil">{lines}</span>
        )}
        <span className="text-pencil">
          cosine <span className="text-ink">{subtree.cosine.toFixed(3)}</span>
        </span>
      </div>
      {subtree.alsoIn.length > 0 && (
        <p className="mt-1 font-mono text-xs text-pencil break-all">also in {subtree.alsoIn.join(', ')}</p>
      )}
      {explanation && (
        <dl className="mt-2 max-w-prose space-y-1 text-base">
          <div>
            <dt className={NOTE_LABEL}>Value</dt> <dd className="inline">{withCode(explanation.value)}</dd>
          </div>
          {explanation.suggestion && (
            <div>
              <dt className={NOTE_LABEL}>For your snippet</dt>{' '}
              <dd className="inline">{withCode(explanation.suggestion)}</dd>
            </div>
          )}
        </dl>
      )}
      <CodeBlock
        code={subtree.code}
        startLine={subtree.startLine}
        highlights={explanation?.highlights}
        label={`Code of ${subtree.name}, ${lines}${underlined ? `, underlined ${underlined}` : ''}`}
      />
    </article>
  )
}

// La misma etiqueta que "Step 1": mono chica, en pencil
const NOTE_LABEL = 'inline font-mono text-[11px] tracking-[0.06em] text-pencil uppercase'

// El modelo pone los nombres de codigo entre backticks: van en mono, como todo dato
const withCode = (text: string) =>
  text.split('`').map((part, i) =>
    i % 2 === 1 ? (
      <code key={i} className="font-mono text-sm">
        {part}
      </code>
    ) : (
      part
    ),
  )
