export type Repository = {
  id: number
  name: string
  fullName: string
  description: string | null
  url: string
  stars: number
  forks: number
  language: string | null
  topics: string[]
  owner: string
  ownerUrl: string
  ownerAvatar: string
}
