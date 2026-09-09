import type { Filters } from "./Filters"

export type SearchQuery = {
  message: string
  filters: Filters
  query: string
}