import { useState, type ReactNode } from 'react'
import ErrorDialog from '@/components/ErrorDialog'
import StatusLine from '@/components/StatusLine'
import { errorCode, errorCopy } from '@/utility/ErrorCopy'

type FailureProps = { error: unknown; children: ReactNode }

// El unico lugar de la pagina con una falla que frena un paso: la linea dice el
// tipo y el tono, y el popup explica la familia sin sacar al usuario de aca
export default function Failure({ error, children }: FailureProps) {
  const [showType, setShowType] = useState(false)
  const code = errorCode(error)
  const copy = errorCopy(error)

  return (
    <div className="mt-6">
      <div role="alert">
        <StatusLine code={code} onExplain={() => setShowType(true)}>
          {copy}
        </StatusLine>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">{children}</div>
      <ErrorDialog open={showType} onClose={() => setShowType(false)} code={code} copy={copy} />
    </div>
  )
}
