import type { ComponentProps } from 'react'

type ButtonProps = ComponentProps<'button'> & { primary?: boolean }

// El boton de la Demo: mono, una linea de --rule, radio 2px, sin relleno, 44px de alto
export const BUTTON =
  'inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-xs border px-4 py-2 ' +
  'font-mono text-xs transition-colors hover:border-pencil hover:text-ink'

export default function Button({ primary = false, className = '', ...props }: ButtonProps) {
  const tone = primary ? 'border-pencil text-ink' : 'border-rule text-pencil'
  return (
    <button
      type="button"
      className={`${BUTTON} ${tone} disabled:cursor-not-allowed disabled:border-rule disabled:text-pencil disabled:opacity-60 ${className}`}
      {...props}
    />
  )
}
