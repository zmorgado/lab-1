import { useEffect, type RefObject } from "react"

// Scrollea el elemento a la vista cada vez que cambia el trigger
export const useScrollIntoView = (
  ref: RefObject<HTMLElement | null>,
  trigger: unknown
): void => {
  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: "smooth" })
  }, [ref, trigger])
}
