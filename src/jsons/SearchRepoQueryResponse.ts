// Solo declaramos los campos que realmente usamos. GitHub devuelve ~100 por repo
export type SearchRepoItem = {
  id: number
  name: string
  full_name: string
  html_url: string
  description: string | null
  stargazers_count: number
  forks_count: number
  language: string | null
  topics?: string[]
  owner: {
    login: string
    avatar_url: string
    html_url: string
  }
}

export type SearchRepoQueryResponse = {
  total_count: number
  incomplete_results: boolean
  items: SearchRepoItem[]
}
