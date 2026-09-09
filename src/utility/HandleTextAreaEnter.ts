export const handleTextAreaEnter = (
  event: React.KeyboardEvent<HTMLTextAreaElement>,
  callback: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void
): void => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    callback(event)
  }
}
