import type { SearchRepoQueryResponse } from "@/jsons/SearchRepoQueryResponse";
import { getAxiosData } from "./common";
import axios from "axios";

class SearchRepoService {
  async search(query: string) {
    const response = () =>
      axios.get<SearchRepoQueryResponse>(query)
    return await getAxiosData(response)
  }
}

export const searchRepoService = new SearchRepoService()
