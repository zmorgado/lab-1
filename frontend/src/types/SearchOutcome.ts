// Un subarbol que se parece al snippet
export type SubtreeMatch = {
  // `Clase.metodo` o `funcion`
  name: string
  startLine: number
  endLine: number
  cosine: number
  // Esas lineas en GitHub, o null si GitHub no dio la URL
  url: string | null
  code: string
  // Los otros repos con el mismo contenido
  alsoIn: string[]
}

export type FileMatches = { path: string; best: number; subtrees: SubtreeMatch[] }

export type RepositoryMatches = { repo: string; best: number; files: FileMatches[] }

// Vacio cuando no se encontro nada: no es un error
export type SearchOutcome = { repositories: RepositoryMatches[] }
