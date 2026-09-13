export function autoGrow(el: HTMLTextAreaElement) {
  el.style.height = "auto"
  el.style.height = `${Math.min(el.scrollHeight, 240)}px`
}