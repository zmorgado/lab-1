// Lineas del archivo, inclusivas
export type LineRange = { start: number; end: number }

// Lo que dijo el modelo de un resultado
export type Explanation = {
  value: string
  // null si no vio nada que valga la pena traer al snippet
  suggestion: string | null
  highlights: LineRange[]
}

// Las explicaciones, por puesto del resultado (#43). Llegan despues de
// los resultados, asi que tienen su propio estado
export type Explanations =
  // Sin resultados no hay nada que explicar, y no se llama al modelo
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; byRank: Map<number, Explanation> }
  | { status: 'failed'; error: unknown }
