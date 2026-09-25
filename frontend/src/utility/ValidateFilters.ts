import { OWNER_PATTERN } from "@/constants/github"
import type { Filters } from "@/types/Filters"

export type FilterErrors = {
  owner?: string
}

/**
 * Solo validamos el owner: va como qualifier (user:...) y un valor invalido
 * hace que GitHub devuelva 422. El repo name viaja como texto con in:name,
 * asi que acepta cualquier caracter sin romper la query.
 */
export function validateFilters(filters: Filters): FilterErrors {
  const errors: FilterErrors = {}
  const owner = filters.owner.trim()

  if (owner && !OWNER_PATTERN.test(owner)) {
    errors.owner = "Only letters, numbers and single hyphens, up to 39 characters"
  }

  return errors
}
