import { useEffect, type RefObject } from "react"

// Le da foco al elemento cuando la condicion pasa a ser true
export const useFocusWhen = (
  ref: RefObject<HTMLElement | null>,
  condition: boolean
): void => {
  useEffect(() => {
    if (condition) ref.current?.focus()
  }, [ref, condition])
}
