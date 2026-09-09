import { BookBookmarkIcon, LineVerticalIcon } from "@phosphor-icons/react";

export default function Header() {
  return (
    <section className="flex flex-row gap-10 justify-between px-5 py-3 border-b border-gray-300">
      <a href="/" className="flex flex-row items-center gap-0.5">
        <BookBookmarkIcon size={32} /> REPO FINDER
      </a>

      <section className="flex items-center">
        <a href="/search" className="transition-transform duration-25 ease-in-out hover:scale-105 hover:underline">
          SEARCH A REPO
        </a>
        <LineVerticalIcon size={20} />
        <a href="/contact" className="transition-transform duration-25 ease-in-out hover:scale-105 hover:underline">
          FIND DEVS 
        </a>
        <LineVerticalIcon size={20} />
        <a href="/about-us" className="transition-transform duration-25 ease-in-out hover:scale-105 hover:underline">
          ABOUT US
        </a>  
      </section>
    </section>
  )
}