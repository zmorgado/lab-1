import { GitForkIcon, LinkIcon, StarIcon } from "@phosphor-icons/react"
import type { Repository } from "@/types/Repository"

export default function RepositoryCard({ repository }: { repository: Repository }) {
  return (
    <article className="flex flex-col gap-2 rounded-2xl border border-gray-300 bg-white p-3">
      <div className="flex items-center gap-2">
        <h3 className="flex-1 truncate rounded-xl bg-gray-100 px-3 py-2 font-semibold text-slate-900">
          {repository.name}
        </h3>
        <span
          className="flex items-center gap-1 rounded-xl bg-gray-100 px-3 py-2 text-sm"
          title={`${repository.stars.toLocaleString()} stars`}
        >
          <StarIcon size={16} />
          {repository.stars.toLocaleString()}
        </span>
        <span
          className="flex items-center gap-1 rounded-xl bg-gray-100 px-3 py-2 text-sm"
          title={`${repository.forks.toLocaleString()} forks`}
        >
          <GitForkIcon size={16} />
          {repository.forks.toLocaleString()}
        </span>
      </div>

      <div className="flex flex-col gap-2 md:flex-row">
        <p className="flex-1 rounded-xl bg-gray-100 px-3 py-2 text-sm text-slate-700">
          {repository.description ?? "No description"}
        </p>
        <div className="flex flex-1 flex-wrap content-start items-start gap-1 rounded-xl bg-gray-100 px-3 py-2">
          {repository.language && (
            <span className="rounded-full bg-slate-900 px-2 py-0.5 text-xs text-white">
              {repository.language}
            </span>
          )}
          {repository.topics.slice(0, 5).map(topic => (
            <span key={topic} className="rounded-full bg-white px-2 py-0.5 text-xs text-slate-600">
              {topic}
            </span>
          ))}
          {!repository.language && repository.topics.length === 0 && (
            <span className="text-xs text-slate-500">No languages or topics</span>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-2 md:flex-row">
        <a
          href={repository.url}
          target="_blank"
          rel="noreferrer"
          className="flex flex-1 items-center gap-1 truncate rounded-xl bg-gray-100 px-3 py-2 text-sm text-slate-700 hover:underline"
        >
          <LinkIcon size={16} className="shrink-0" />
          <span className="truncate">{repository.url}</span>
        </a>
        <a
          href={repository.ownerUrl}
          target="_blank"
          rel="noreferrer"
          className="flex flex-1 items-center gap-2 truncate rounded-xl bg-gray-100 px-3 py-2 text-sm text-slate-700 hover:underline"
        >
          <img src={repository.ownerAvatar} alt="" className="h-5 w-5 shrink-0 rounded-full" />
          <span className="truncate">{repository.owner}</span>
        </a>
      </div>
    </article>
  )
}
