import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setupServer } from 'msw/node'
import Search from '@/pages/Search'

// El backend se stubea en el borde HTTP: la pagina no sabe que hay MSW
const server = setupServer()

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
})
afterAll(() => server.close())

const snippetBox = () => screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Snippet' })

const METHOD = '    def rank(self, items):\n        return sorted(items, key=self.score)\n'

describe('attaching a snippet', () => {
  it('fills the snippet from an attached .py file', async () => {
    const user = userEvent.setup()
    render(<Search />)

    await user.upload(
      screen.getByLabelText(/attach a \.py file/i),
      new File([METHOD], 'ranking.py', { type: 'text/x-python' }),
    )

    expect(await screen.findByDisplayValue(/def rank/)).toHaveProperty('value', METHOD)
  })

  it('refuses a file that is not Python', async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<Search />)

    await user.upload(
      screen.getByLabelText(/attach a \.py file/i),
      new File(['const a = 1'], 'notes.js', { type: 'text/javascript' }),
    )

    expect(await screen.findByText(/only \.py files/i)).toBeTruthy()
    expect(snippetBox().value).toBe('')
  })

  it("can't submit an empty snippet", async () => {
    const user = userEvent.setup()
    render(<Search />)
    const submit = screen.getByRole('button', { name: /propose tags/i })

    expect(submit).toHaveProperty('disabled', true)
    await user.type(snippetBox(), '   ')
    expect(submit).toHaveProperty('disabled', true)
  })
})
