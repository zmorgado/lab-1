import { useEffect, useState } from 'react'

type ElapsedProps = { children: string }

// Un numero que cuenta segundos en vez de un spinner: nada en la pagina hace loop.
// Se monta al empezar la espera, asi que arranca en cero solo
export default function Elapsed({ children }: ElapsedProps) {
  const [start] = useState(() => Date.now())
  const [now, setNow] = useState(start)

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(timer)
  }, [])

  const seconds = Math.floor((now - start) / 1000)
  return (
    <p role="status" className="mt-4 text-base text-pencil">
      {children} <span className="font-mono text-sm text-ink">{seconds} s</span>
    </p>
  )
}
