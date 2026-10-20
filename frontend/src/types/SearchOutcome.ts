export type SubtreeMatch = {
  // El puesto que le dio el backend: identifica al resultado
  rank: number
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

// Una query que encontro el archivo: su tipo y el `q` tal como se mando
export type FoundBy = { kind: string; q: string }

export type FileMatches = { path: string; bestCosine: number; foundBy: FoundBy[]; subtrees: SubtreeMatch[] }

export type RepositoryMatches = { repo: string; bestCosine: number; files: FileMatches[] }

// Vacio cuando no se encontro nada: no es un error
export type SearchOutcome = { repositories: RepositoryMatches[] }
