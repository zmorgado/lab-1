import type { Filters } from "@/types/Filters"

// Traduce el error crudo de GitHub a algo que le sirva al usuario
export function toSearchErrorMessage(error: unknown, filters: Filters): string {
  const message = error instanceof Error ? error.message : ""
  const owner = filters.owner.trim()

  if (message.includes("cannot be searched")) {
    return owner
      ? `We couldn't find the owner "${owner}". Check the spelling and try again.`
      : "One of the users or repositories in your search doesn't exist."
  }

  if (message.includes("longer than 256")) {
    return "Your search is too long. Try shortening it."
  }

  if (message.includes("rate limit")) {
    return "Too many searches in a short time. Wait a minute and try again."
  }

  return message || "Something went wrong while searching. Try again."
}
