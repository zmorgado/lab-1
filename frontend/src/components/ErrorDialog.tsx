import { useEffect, useRef } from 'react'
import Button from '@/components/Button'
import { severityFor, severityNote, typeLabel } from '@/utility/ErrorCopy'

type ErrorDialogProps = {
  open: boolean
  onClose: () => void
  code: string | null
  copy: string
}

// El popup del tipo de error: que fallo, el code estable y a que familia
// pertenece. Es un <dialog> nativo: el foco, el backdrop y el Esc los maneja el
// browser, no nosotros
export default function ErrorDialog({ open, onClose, code, copy }: ErrorDialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const severity = severityFor(code)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    // `showModal` trae el backdrop y atrapa el foco, pero jsdom (los tests) no lo
    // implementa: ahi alcanza con el atributo `open`, que refleja `.open`
    if (open && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.open = true
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.open = false
    }
  }, [open])

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="error-type-title"
      className="w-[calc(100%-2rem)] max-w-md rounded-xs border border-rule bg-ground p-6 text-ink backdrop:bg-ink/30"
    >
      <p className="font-mono text-[11px] tracking-[0.06em] text-pencil uppercase">Error type</p>
      <h2 id="error-type-title" className="mt-1 text-2xl font-semibold tracking-[-0.015em]">
        {typeLabel(code)}
      </h2>
      <p className="mt-2 font-mono text-xs text-pencil">
        code <span className="text-ink">{code ?? 'none'}</span> · {severity}
      </p>
      <p className="mt-4 max-w-prose">{copy}</p>
      <p className="mt-3 max-w-prose text-base text-pencil">{severityNote(severity)}</p>
      <div className="mt-6 flex justify-end">
        <Button primary onClick={onClose}>
          Close
        </Button>
      </div>
    </dialog>
  )
}
