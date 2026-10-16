import { useId, type ReactNode } from 'react'
import CodeBlock from '@/components/CodeBlock'
import StepHeading from '@/components/StepHeading'
import type { SearchOutcome, SubtreeMatch } from '@/types/SearchOutcome'

type ResultsProps = { outcome: SearchOutcome; actions: ReactNode }

export default function Results({ outcome, actions }: ResultsProps) {
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
      <div className="mt-4 flex flex-wrap items-center gap-2">{actions}</div>

      {outcome.repositories.map(repository => (
        <div key={repository.repo} className="mt-8 border-t border-rule pt-6">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4">
            <h3 className="font-mono text-base font-medium break-all">{repository.repo}</h3>
            <p className="font-mono text-sm text-pencil">best cosine {repository.best.toFixed(3)}</p>
          </div>
          {repository.files.map(file => (
            <div key={file.path} className="mt-4">
              <h4 className="font-mono text-sm text-pencil break-all">{file.path}</h4>
              {file.subtrees.map(subtree => (
                <Subtree key={`${subtree.startLine}-${subtree.name}`} subtree={subtree} />
              ))}
            </div>
          ))}
        </div>
      ))}
    </section>
  )
}

function Subtree({ subtree }: { subtree: SubtreeMatch }) {
  const id = useId()
  const lines = `lines ${subtree.startLine}–${subtree.endLine}`

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
      <CodeBlock code={subtree.code} startLine={subtree.startLine} label={`Code of ${subtree.name}, ${lines}`} />
    </article>
  )
}
