// El cuerpo de un error del backend: `code` es estable, `message` puede cambiar
export type ErrorBody = {
  code?: unknown
}
