import type { ReactNode } from 'react'
import { errorCopy } from '@/utility/ErrorCopy'

type FailureProps = { error: unknown; children: ReactNode }

// El unico lugar de la pagina con --alert: el paso que fallo
export default function Failure({ error, children }: FailureProps) {
  return (
    <div className="mt-6">
      <p role="alert" className="max-w-prose text-alert">
        {errorCopy(error)}
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-2">{children}</div>
    </div>
  )
}
