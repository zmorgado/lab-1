import { useState } from 'react'
import Button from '@/components/Button'
import Elapsed from '@/components/Elapsed'
import Failure from '@/components/Failure'
import SnippetForm from '@/components/SnippetForm'
import TagConfirmation from '@/components/TagConfirmation'
import { toTagPreview } from '@/model/Search'
import { searchService } from '@/services/SearchService'
import type { Step } from '@/types/Step'

export default function Search() {
  const [snippet, setSnippet] = useState('')
  const [state, setState] = useState<Step>({ step: 'editing' })

  async function proposeTags() {
    setState({ step: 'loadingTags' })
    try {
      const preview = toTagPreview(await searchService.preview(snippet))
      setState({ step: 'confirming', preview })
    } catch (error) {
      setState({ step: 'failed', at: 'tags', error })
    }
  }

  const editing = state.step === 'editing'

  return (
    <main className="mx-auto max-w-page px-5 pb-16 sm:px-9 sm:pb-24">
      <header className="pt-16 pb-12">
        <p className="font-mono text-[11px] tracking-[0.06em] text-pencil uppercase">LAB #1</p>
        <h1 className="mt-1 text-3xl leading-tight font-semibold tracking-[-0.015em] sm:text-4xl">
          Snippet search
        </h1>
        <p className="mt-4 max-w-prose text-xl leading-normal">
          Paste a Python function or class, and this page looks for code on GitHub that does the same
          thing, even when it is written differently.
        </p>
        <p className="mt-4 max-w-prose text-pencil">
          First it proposes the tags it will search with, and you confirm them. Then it ranks what it
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

      {state.step === 'confirming' && (
        <TagConfirmation
          preview={state.preview}
          onConfirm={() => {}}
          onBack={() => setState({ step: 'editing' })}
          locked={false}
          showActions
        />
      )}

      {state.step === 'failed' && (
        <Failure error={state.error}>
          <Button onClick={() => setState({ step: 'editing' })}>
            <span aria-hidden="true">◂</span> Change the snippet
          </Button>
        </Failure>
      )}
    </main>
  )
}
