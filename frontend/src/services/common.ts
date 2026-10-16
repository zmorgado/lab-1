import axios, { type AxiosResponse } from 'axios'
import type { ErrorBody } from '@/jsons/ErrorBody'

// Lo unico que la pagina sabe de un llamado fallido
export class ApiError extends Error {
  // El code estable del backend, si mando uno
  readonly code: string | null
  // null: no hubo respuesta
  readonly status: number | null

  constructor(code: string | null, status: number | null, options?: ErrorOptions) {
    super(status === null ? 'No response from the backend' : `Backend answered ${status}`, options)
    this.code = code
    this.status = status
  }
}

// El embudo de errores: todo llamado que falla sale como un ApiError
export const getAxiosData = async <T>(call: () => Promise<AxiosResponse<T>>): Promise<T> => {
  try {
    const response = await call()
    return response.data
  } catch (error) {
    if (!axios.isAxiosError(error) || !error.response) {
      throw new ApiError(null, null, { cause: error })
    }
    const body = error.response.data as ErrorBody | undefined
    const code = typeof body?.code === 'string' ? body.code : null
    throw new ApiError(code, error.response.status, { cause: error })
  }
}
