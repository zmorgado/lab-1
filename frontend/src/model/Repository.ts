import type { SearchRepoItem, SearchRepoQueryResponse } from "@/jsons/SearchRepoQueryResponse"
import type { Repository } from "@/types/Repository"

export type SearchResult = {
  totalCount: number
  repositories: Repository[]
}

// Achicamos el JSON de GitHub a lo que la card necesita
export function toRepository(item: SearchRepoItem): Repository {
  return {
    id: item.id,
    name: item.name,
    fullName: item.full_name,
    description: item.description,
    url: item.html_url,
    stars: item.stargazers_count,
    forks: item.forks_count,
    language: item.language,
    topics: item.topics ?? [],
    owner: item.owner.login,
    ownerUrl: item.owner.html_url,
    ownerAvatar: item.owner.avatar_url,
  }
}

export function toSearchResult(response: SearchRepoQueryResponse): SearchResult {
  return {
    totalCount: response.total_count,
    repositories: (response.items ?? []).map(toRepository),
  }
}
