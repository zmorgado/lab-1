import { useEffect, useRef, type RefObject } from "react"

// Cierra algo flotante (dropdown, modal) al hacer click afuera o apretar Escape
export const useDismissable = (
  ref: RefObject<HTMLElement | null>,
  isOpen: boolean,
  onClose: () => void
): void => {
  // Guardamos el callback en una ref asi no re-suscribimos los listeners en cada render
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!isOpen) return

    function handlePointerDown(event: MouseEvent) {
      if (!ref.current?.contains(event.target as Node)) onCloseRef.current()
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseRef.current()
    }

    document.addEventListener("mousedown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("mousedown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [ref, isOpen])
}
