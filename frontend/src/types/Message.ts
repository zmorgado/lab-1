import type { Repository } from "./Repository"

export type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "assistant"; status: "loading" }
  | { id: number; role: "assistant"; status: "error"; text: string }
  | {
      id: number
      role: "assistant"
      status: "done"
      totalCount: number
      repositories: Repository[]
    }
