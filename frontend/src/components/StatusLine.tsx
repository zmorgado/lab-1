import type { ReactNode } from 'react'
import { severityFor, typeLabel, type Severity } from '@/utility/ErrorCopy'

// El tono va en la regla y la etiqueta, no en la prosa: la oracion larga se lee
// mejor en --ink. `correctable` usa --signal (el sistema pidiendo una accion),
// `setup` --alert (lo mas fuerte, necesita a un humano) y `transient` --pencil
// (lo mas callado: se espera)
const RULE: Record<Severity, string> = {
  correctable: 'border-signal',
  transient: 'border-pencil',
  setup: 'border-alert',
}

const TONE: Record<Severity, string> = {
  correctable: 'text-signal',
  transient: 'text-pencil',
  setup: 'text-alert',
}

// La misma etiqueta que "Step 1": mono chica, en mayusculas
const LABEL = 'font-mono text-[11px] tracking-[0.06em] uppercase'

type StatusLineProps = {
  code: string | null
  children: ReactNode
  className?: string
  // Con popup, la etiqueta entera es el boton que lo abre; sin el, es texto
  onExplain?: () => void
}

// Una falla impresa como linea: tono por familia, tipo y code estables arriba,
// la copy abajo. El color solo no alcanza (WCAG 1.4.1), por eso el tipo y el
// code van escritos y ademas en `data-*` para los tests. La misma linea sirve
// para una falla que frena un paso y para la nota del modelo: el tono lo pone
// el code, asi que `llm_not_configured` es un `setup` rojo aunque la busqueda
// siga, y `llm_quota_exhausted` un `transient` callado
export default function StatusLine({ code, children, className = '', onExplain }: StatusLineProps) {
  const severity = severityFor(code)
  const label = (
    <>
      <span className={TONE[severity]}>{typeLabel(code)}</span>
      {code && (
        <span className="rounded-xs border border-rule px-1.5 py-px font-mono text-[11px] text-pencil">
          {code}
        </span>
      )}
    </>
  )

  return (
    <div
      className={`border-l-2 pl-4 ${RULE[severity]} ${className}`}
      data-severity={severity}
      data-code={code ?? ''}
    >
      {onExplain ? (
        <button
          type="button"
          onClick={onExplain}
          aria-haspopup="dialog"
          className={`${LABEL} flex w-fit cursor-pointer flex-wrap items-center gap-2 text-left`}
        >
          {label}
        </button>
      ) : (
        <p className={`${LABEL} flex flex-wrap items-center gap-2`}>{label}</p>
      )}
      <p className="mt-1 max-w-prose">{children}</p>
    </div>
  )
}
