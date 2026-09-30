import { PaperPlaneRightIcon } from "@phosphor-icons/react"
import { handleTextAreaEnter } from "@/utility/HandleTextAreaEnter"
import type { InputAreaProps } from "@/types/InputAreaProps"
import { autoGrow } from "@/utility/AutoGrow";

export default function InputArea({
  textareaRef,
  value,
  onChange,
  onSubmit,
  disabled,
  id,
  children,
}: InputAreaProps) {
  return (
    <form
      className="flex w-full flex-col gap-3"
      onSubmit={(e) => { e.preventDefault(); onSubmit() }}
    >
      <div className="flex items-end gap-2">
        <textarea
          id={id}
          ref={textareaRef}
          value={value}
          onChange={(e) => { onChange(e.target.value); autoGrow(e.currentTarget) }}
          onKeyDown={(e) => handleTextAreaEnter(e, (ev) => ev.currentTarget.form?.requestSubmit())}
          rows={1}
          className="no-scrollbar flex-1 rounded-2xl border border-gray-300 px-2 py-2 resize-none overflow-y-auto focus:outline-1 focus:outline-gray-400"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="rounded-full border border-gray-300 p-2 disabled:opacity-40"
        >
          <PaperPlaneRightIcon size={20} />
        </button>
      </div>
      {children}
    </form>
  )
}
