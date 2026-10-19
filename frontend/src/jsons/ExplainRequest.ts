// Un resultado tal como lo recibe POST /api/search/explain (#43)
export type ExplainItemBody = {
  rank: number
  repo: string
  path: string
  name: string
  start_line: number
  code: string
}
