import axios from 'axios'
import { API_URL, LANGUAGE } from '@/constants/api'
import type { ExplainItemBody } from '@/jsons/ExplainRequest'
import type { ExplainResponse } from '@/jsons/ExplainResponse'
import type { PreviewResponse } from '@/jsons/PreviewResponse'
import type { ConfirmedTagBody } from '@/jsons/SearchRequest'
import type { SearchResponse } from '@/jsons/SearchResponse'
import { getAxiosData } from './common'

const backend = axios.create({ baseURL: API_URL })

class SearchService {
  // El snippet viaja sin trim: la sangria de la primera linea es parte de un metodo pegado
  async preview(source: string) {
    return await getAxiosData(() =>
      backend.post<PreviewResponse>('/api/search/preview', { source, language: LANGUAGE }),
    )
  }

  // Rearma las queries con los tags elegidos, sin el modelo: dice cuales no entran
  async plan(source: string, tags: ConfirmedTagBody[]) {
    return await getAxiosData(() =>
      backend.post<PreviewResponse>('/api/search/preview', { source, language: LANGUAGE, tags }),
    )
  }

  // Con los tags confirmados el backend no vuelve a llamar al modelo
  async search(source: string, tags: ConfirmedTagBody[]) {
    return await getAxiosData(() =>
      backend.post<SearchResponse>('/api/search', { source, language: LANGUAGE, tags }),
    )
  }

  // Que aporta cada resultado (#43). Va despues de la busqueda
  async explain(source: string, results: ExplainItemBody[]) {
    return await getAxiosData(() =>
      backend.post<ExplainResponse>('/api/search/explain', { source, results }),
    )
  }
}

export const searchService = new SearchService()
