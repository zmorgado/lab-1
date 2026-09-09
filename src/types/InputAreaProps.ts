import type { ReactNode, Ref } from "react"

export type InputAreaProps = {
  textareaRef: Ref<HTMLTextAreaElement>
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  disabled?: boolean
  id?: string
  children?: ReactNode
}