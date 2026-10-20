import { useRef, useState } from 'react'
import Button from '@/components/Button'
import Elapsed from '@/components/Elapsed'
import Failure from '@/components/Failure'
import Results from '@/components/Results'
import SnippetForm from '@/components/SnippetForm'
import TagConfirmation from '@/components/TagConfirmation'
import {
  toConfirmedTags,
  toExplainItems,
  toExplanations,
  toSearchOutcome,
  toTagPreview,
  withDropped,
} from '@/model/Search'
import { searchService } from '@/services/SearchService'
import type { Explanations } from '@/types/Explanations'
import type { SearchOutcome } from '@/types/SearchOutcome'
import type { Step } from '@/types/Step'
import type { TagPreview } from '@/types/TagPreview'
import { addTag, toggleTag } from '@/utility/TagEdits'

export default function Search() {
  const [snippet, setSnippet] = useState('')
  const [state, setState] = useState<Step>({ step: 'editing' })
  // Solo cuenta la respuesta del ultimo rearmado: una vieja pisaria la edicion
  const lastPlan = useRef(0)

  async function proposeTags() {
    setState({ step: 'loadingTags' })
    try {
      const preview = toTagPreview(await searchService.preview(snippet))
      setState({ step: 'confirming', preview })
    } catch (error) {
      setState({ step: 'failed', at: 'tags', error })
    }
  }

  // Cada edicion le pregunta al backend que entra en cada query, sin el modelo
  async function editTags(preview: TagPreview) {
    setState({ step: 'confirming', preview })
    const plan = ++lastPlan.current
    const tags = toConfirmedTags(preview)
    if (tags.length === 0) return
    try {
      const raw = await searchService.plan(snippet, tags)
      if (plan !== lastPlan.current) return
      setState(current =>
        current.step === 'confirming' ? { ...current, preview: withDropped(current.preview, raw) } : current,
      )
    } catch {
      // Sin el rearmado, las marcas de lo que no entra quedan como estaban
    }
  }

  async function runSearch(preview: TagPreview) {
    setState({ step: 'searching', preview })
    try {
      const outcome = toSearchOutcome(await searchService.search(snippet, toConfirmedTags(preview)))
      setState({ step: 'done', preview, outcome, explanations: { status: 'idle' } })
      void explainResults(outcome)
    } catch (error) {
      setState({ step: 'failed', at: 'search', error, preview })
    }
  }

  // Las explicaciones van despues de los resultados, que ya se ven (#43)
  async function explainResults(outcome: SearchOutcome) {
    const items = toExplainItems(outcome)
    if (items.length === 0) return
    // Solo cuenta si la pagina sigue mostrando estos resultados
    const update = (explanations: Explanations) =>
      setState(current =>
        current.step === 'done' && current.outcome === outcome ? { ...current, explanations } : current,
      )
    update({ status: 'loading' })
    try {
      update({ status: 'ready', byRank: toExplanations(await searchService.explain(snippet, items)) })
    } catch (error) {
      update({ status: 'failed', error })
    }
  }

  // Una busqueda nueva arranca editando, con el snippet de antes
  const editSnippet = () => setState({ step: 'editing' })
  const backToSnippet = (
    <Button onClick={editSnippet}>
      <span aria-hidden="true">◂</span> Change the snippet
    </Button>
  )

  const editing = state.step === 'editing'
  const preview = 'preview' in state ? state.preview : null

  return (
    <main className="mx-auto max-w-page px-5 pb-16 sm:px-9 sm:pb-24">
      <header className="pt-16 pb-12">
        <p className="font-mono text-[11px] tracking-[0.06em] text-pencil uppercase">LAB #1</p>
        <h1 className="mt-1 text-3xl leading-tight font-semibold tracking-[-0.015em] sm:text-4xl">
          Snippet search
        </h1>
        <p className="mt-4 max-w-prose text-xl leading-normal">
          Paste a Python snippet, and this page looks for code on GitHub conceptually and functionally
          similar regardless of syntax deviation from the original code. Conceptual and functional
          similarity is computed by vector embeddings and cosine similarity on{' '}
          <a
            href="https://arxiv.org/html/2203.03850v1#S3"
            target="_blank"
            rel="noreferrer"
            className="text-alert border-alert hover:border-alert"
          >
            UnixCoder
          </a>.
        </p>
        <p className="mt-4 max-w-prose text-pencil">
          First it proposes the tags it will search with: you can add, edit, and finally confirm them.
          Lastly it ranks what it
          finds by how close each piece of code is to yours. Python only. A search takes tens of
          seconds, and its GitHub budget is shared by everyone using the page: about three searches a
          minute between all of you.
        </p>
      </header>

      <SnippetForm
        snippet={snippet}
        onChange={setSnippet}
        onSubmit={proposeTags}
        locked={!editing}
        showActions={editing || state.step === 'loadingTags'}
      />

      {state.step === 'loadingTags' && <Elapsed>Reading the snippet and proposing tags</Elapsed>}
      {state.step === 'failed' && state.at === 'tags' && <Failure error={state.error}>{backToSnippet}</Failure>}

      {preview && (
        <TagConfirmation
          preview={preview}
          onToggle={(kind, text) => editTags(toggleTag(preview, kind, text))}
          onAdd={(kind, text) => editTags(addTag(preview, kind, text))}
          onConfirm={() => runSearch(preview)}
          onBack={editSnippet}
          locked={state.step === 'searching'}
          showActions={state.step === 'confirming' || state.step === 'searching'}
        />
      )}

      {state.step === 'searching' && (
        <>
          <Elapsed>Searching GitHub and ranking the code it finds</Elapsed>
          <p className="mt-2 max-w-prose text-base text-pencil">
            The first search after the service starts also loads the ranking model, so it takes longer.
          </p>
        </>
      )}
      {state.step === 'failed' && state.at === 'search' && (
        <Failure error={state.error}>
          <Button primary onClick={() => setState({ step: 'confirming', preview: state.preview })}>
            <span aria-hidden="true">◂</span> Back to the tags
          </Button>
          {backToSnippet}
        </Failure>
      )}

      {state.step === 'done' && (
        <Results
          outcome={state.outcome}
          explanations={state.explanations}
          actions={
            <Button primary onClick={editSnippet}>
              New search <span aria-hidden="true">▸</span>
            </Button>
          }
        />
      )}
    </main>
  )
}
