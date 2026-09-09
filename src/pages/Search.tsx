import { useRef, useState } from "react"
import { BracketsCurlyIcon, FolderIcon, SpinnerIcon, UserIcon } from "@phosphor-icons/react"
import InputArea from "@/components/InputArea"
import RepositoryCard from "@/components/RepositoryCard"
import { LANGUAGES } from "@/constants/languages"
import type { Message } from "@/types/Message"
import type { Filters } from "@/types/Filters"
import { buildQueryString, buildSearchQuery } from "@/model/SearchQuery"
import { toSearchResult } from "@/model/Repository"
import { MAX_QUERY_LENGTH } from "@/constants/github"
import { validateFilters } from "@/utility/ValidateFilters"
import { toSearchErrorMessage } from "@/utility/SearchErrorMessage"
import { toggleArrayItem } from "@/utility/ToggleArrayItem"
import { useScrollIntoView } from "@/utility/UseScrollIntoView"
import { useFocusWhen } from "@/utility/UseFocusWhen"
import { useDismissable } from "@/utility/UseDismissable"
import { searchRepoService } from "@/services/SearchService"

export default function Search() {
  const [userMessage, setUserMessage] = useState("")
  const [messages, setMessages] = useState<Message[]>([])
  const started: boolean = messages.length > 0

  const [filters, setFilters] = useState<Filters>({ owner: "", repoName: "", languages: [] })
  const [languagesOpen, setLanguagesOpen] = useState(false)

  const landingTextareaRef = useRef<HTMLTextAreaElement>(null)
  const chatTextareaRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const languagesRef = useRef<HTMLDivElement>(null)
  const messageId = useRef(0)
  const nextId = () => ++messageId.current

  useScrollIntoView(bottomRef, messages)
  useFocusWhen(chatTextareaRef, started)
  useDismissable(languagesRef, languagesOpen, () => setLanguagesOpen(false))

  const filterErrors = validateFilters(filters)
  const hasFilterErrors = Object.keys(filterErrors).length > 0

  function toggleLanguage(language: string) {
    setFilters(prev => ({ ...prev, languages: toggleArrayItem(prev.languages, language) }))
  }

  async function sendMessage(el?: HTMLTextAreaElement | null) {
    if (el) el.style.height = "auto"

    const text = userMessage.trim()
    if (!text) return

    if (hasFilterErrors) return

    const userId = nextId()
    const pendingId = nextId()
    setMessages(prev => [
      ...prev,
      { id: userId, role: "user", text },
      { id: pendingId, role: "assistant", status: "loading" },
    ])
    setUserMessage("")

    const replacePending = (message: Message) =>
      setMessages(prev => prev.map(m => (m.id === pendingId ? message : m)))

    const queryString = buildQueryString(text, filters)
    console.log("Message:", text)
    console.log("Query string:", queryString)

    if (!queryString) {
      replacePending({
        id: pendingId,
        role: "assistant",
        status: "error",
        text: "Add an owner, a repository name or a language to search for.",
      })
      return
    }

    if (queryString.length > MAX_QUERY_LENGTH) {
      replacePending({
        id: pendingId,
        role: "assistant",
        status: "error",
        text: `Your search is ${queryString.length} characters long and GitHub allows up to ${MAX_QUERY_LENGTH}. Try shortening it.`,
      })
      return
    }

    try {
      const query = buildSearchQuery(text, filters)
      console.log("Query:", query)

      const response = await searchRepoService.search(query)
      console.log("Response:", response)

      const { totalCount, repositories } = toSearchResult(response)
      replacePending({ id: pendingId, role: "assistant", status: "done", totalCount, repositories })
    } catch (error) {
      replacePending({
        id: pendingId,
        role: "assistant",
        status: "error",
        text: toSearchErrorMessage(error, filters),
      })
    }
  }

  return (
    <section className="relative flex-1 overflow-hidden">
      {/* Layer 1: landing (heading + input), fades/slides up and out */}
      <div className={`absolute inset-0 flex flex-col justify-center items-center gap-20
                      transition-all duration-200 ease-in
                      ${started ? "opacity-0 -translate-y-4 pointer-events-none"
                        : "opacity-100 translate-y-0"}`}>
        <h1 className="text-4xl md:text-5xl font-extrabold tracking-tight leading-tight text-slate-900">
          Make your first <span className="italic">Search</span>!
        </h1>
        <div className="w-2/3">
          <InputArea
            id="userInputTextArea"
            textareaRef={landingTextareaRef}
            value={userMessage}
            onChange={setUserMessage}
            onSubmit={() => sendMessage(landingTextareaRef.current)}
            disabled={hasFilterErrors}
          >
            <div className="flex flex-col items-start gap-2 text-sm">
              <div className="flex flex-col gap-1">
                <label className="flex items-center gap-2">
                  <UserIcon size={20} className="text-slate-600" />
                  <input
                    type="text"
                    value={filters.owner}
                    onChange={(e) => setFilters(prev => ({ ...prev, owner: e.target.value }))}
                    placeholder="Owner"
                    aria-invalid={Boolean(filterErrors.owner)}
                    className={`rounded-lg border px-2 py-1 focus:outline-1 ${
                      filterErrors.owner
                        ? "border-red-400 focus:outline-red-400"
                        : "border-gray-300 focus:outline-gray-400"
                    }`}
                  />
                </label>
                {filterErrors.owner && (
                  <span className="pl-7 text-xs text-red-600">{filterErrors.owner}</span>
                )}
              </div>

              <label className="flex items-center gap-2">
                <FolderIcon size={20} className="text-slate-600" />
                <input
                  type="text"
                  value={filters.repoName}
                  onChange={(e) => setFilters(prev => ({ ...prev, repoName: e.target.value }))}
                  placeholder="Repo name"
                  className="rounded-lg border border-gray-300 px-2 py-1"
                />
              </label>

              <div ref={languagesRef} className="relative flex items-center gap-2">
                <BracketsCurlyIcon size={20} className="text-slate-600" />
                <button
                  type="button"
                  onClick={() => setLanguagesOpen(open => !open)}
                  className="rounded-lg border border-gray-300 px-2 py-1"
                >
                  <span className="text-[#8b8b8f] font-light">Programming Languages
                  {filters.languages.length > 0 && ` (${filters.languages.length})`}</span>
                </button>

                {languagesOpen && (
                  <div className="app-scrollbar absolute left-7 top-full z-10 mt-1 max-h-60 w-56 overflow-y-auto rounded-lg border border-gray-300 bg-white py-1 shadow-lg">
                    {LANGUAGES.map(language => (
                      <label
                        key={language}
                        className="flex cursor-pointer items-center gap-2 px-3 py-1.5 hover:bg-gray-100"
                      >
                        <input
                          type="checkbox"
                          checked={filters.languages.includes(language)}
                          onChange={() => toggleLanguage(language)}
                        />
                        {language}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </InputArea>
        </div>
      </div>

      {/* Layer 2: chat window, fades/slides in from below */}
      <div className={`absolute inset-0 flex flex-col
                      transition-all duration-200 ease-out
                      ${started ? "opacity-100 translate-y-0"
                        : "opacity-0 translate-y-8 pointer-events-none"}`}>
        <div className="flex-1 overflow-y-auto app-scrollbar">
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
            {messages.map(m => {
              if (m.role === "user") {
                return (
                  <span key={m.id} className="self-end max-w-[80%] rounded-2xl bg-gray-200 px-4 py-2 whitespace-pre-wrap">
                    {m.text}
                  </span>
                )
              }

              if (m.status === "loading") {
                return (
                  <span key={m.id} className="flex items-center gap-2 self-start text-slate-600">
                    <SpinnerIcon size={20} className="animate-spin" />
                    Searching for repositories matching your criteria
                  </span>
                )
              }

              if (m.status === "error") {
                return (
                  <span key={m.id} className="self-start max-w-[90%] text-red-600">
                    {m.text}
                  </span>
                )
              }

              const remaining = m.totalCount - m.repositories.length

              return (
                <div key={m.id} className="flex w-full flex-col gap-3 text-slate-900">
                  {m.totalCount === 0 ? (
                    <span>I couldn't find any repositories matching your search criteria.</span>
                  ) : (
                    <>
                      <p>
                        I found {m.totalCount.toLocaleString()} repositories matching your search criteria.
                      </p>
                      {m.totalCount > 10 && <p>
                        Here are the best rated 10:
                      </p>}
                      {m.repositories.map(repository => (
                        <RepositoryCard key={repository.id} repository={repository} />
                      ))}
                      {remaining > 0 && (
                        <span className="text-slate-600">
                          There are {remaining.toLocaleString()} more repositories. Try narrowing your
                          search by adding an owner, a repository name or a language.
                        </span>
                      )}
                    </>
                  )}
                </div>
              )
            })}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="shrink-0 border-t border-gray-300 bg-[#F3F4F6]">
          <div className="mx-auto flex w-full max-w-3xl items-end gap-2 px-4 py-3">
            <InputArea
              textareaRef={chatTextareaRef}
              value={userMessage}
              onChange={setUserMessage}
              onSubmit={() => sendMessage(chatTextareaRef.current)}
            />
          </div>
        </div>
      </div>
    </section>
  )
}
