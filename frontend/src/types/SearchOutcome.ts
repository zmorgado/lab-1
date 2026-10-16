export type SubtreeMatch = {
  // `Clase.metodo` o `funcion`
  name: string
  startLine: number
  endLine: number
  cosine: number
  url: string | null
  code: string
  // Los otros repos con el mismo contenido
  alsoIn: string[]
}

export type FileMatches = { path: string; bestCosine: number; subtrees: SubtreeMatch[] }

export type RepositoryMatches = { repo: string; bestCosine: number; files: FileMatches[] }

// Vacio cuando no se encontro nada: no es un error
export type SearchOutcome = { repositories: RepositoryMatches[] }
