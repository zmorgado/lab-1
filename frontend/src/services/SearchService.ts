import axios from 'axios'
import { API_URL, LANGUAGE } from '@/constants/api'
import type { PreviewResponse } from '@/jsons/PreviewResponse'
import { getAxiosData } from './common'

const backend = axios.create({ baseURL: API_URL })

class SearchService {
  // El snippet viaja sin trim: la sangria de la primera linea es parte de un metodo pegado
  async preview(source: string) {
    return await getAxiosData(() =>
      backend.post<PreviewResponse>('/api/search/preview', { source, language: LANGUAGE }),
    )
  }
}

export const searchService = new SearchService()
