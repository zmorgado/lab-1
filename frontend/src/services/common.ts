import axios, { type AxiosResponse } from 'axios'

type GitHubErrorBody = {
  message?: string
  errors?: { message?: string }[]
}

export const getAxiosData = async <T>(query: () => Promise<AxiosResponse<T>>): Promise<T> => {
  try {
    const response = await query()
    return response.data
  } catch (error) {
    // Axios tira excepcion en 4xx/5xx, asi que el detalle util de GitHub esta en el body
    if (axios.isAxiosError(error)) {
      const body = error.response?.data as GitHubErrorBody | undefined
      const detail = body?.errors?.find(e => e.message)?.message ?? body?.message

      if (detail) {
        throw new Error(detail, { cause: error })
      }

      if (!error.response) {
        throw new Error('Error while making the call. Check connection and try again', { cause: error })
      }
    }

    throw error
  }
}
