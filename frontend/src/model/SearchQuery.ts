import type { Filters } from "@/types/Filters"

const ENDPOINT = "https://api.github.com/search/repositories"

export const RESULTS_PER_PAGE = 10

// GitHub necesita comillas cuando el valor tiene espacios: language:"Jupyter Notebook"
const quote = (value: string): string => (/\s/.test(value) ? `"${value}"` : value)

// El valor de q, sin la URL. Sirve para chequear el limite de 256 caracteres
// TODO: el mensaje del usuario todavia no entra en la query
export function buildQueryString(_message: string, filters: Filters): string {
  const terms: string[] = []

  const repoName = filters.repoName.trim()
  if (repoName) {
    terms.push(quote(repoName), "in:name")
  }

  const owner = filters.owner.trim()
  if (owner) {
    terms.push(`user:${quote(owner)}`)
  }

  // El qualifier repetido y separado por espacios funciona como OR.
  // La palabra OR no: GitHub responde "Logical operators only apply to text, not to qualifiers"
  const languages = filters.languages.map(language => language.trim()).filter(Boolean)
  languages.forEach(language => terms.push(`language:${quote(language)}`))

  return terms.join(" ")
}

// URLSearchParams encodea todo (espacios, #, +, comillas) asi C# y C++ no rompen la URL
export function buildSearchQuery(message: string, filters: Filters, page: number = 1): string {
  const params = new URLSearchParams({
    q: buildQueryString(message, filters),
    sort: "stars",
    order: "desc",
    per_page: String(RESULTS_PER_PAGE),
    page: String(page),
  })

  return `${ENDPOINT}?${params}`
}
