export default function HomeOptionButton({text, redirectTo}:{text: string, redirectTo: string}) {
  return (
    <a className="border border-gray-300 px-5 py-3 rounded-xl bg-blue-600 text-white font-semibold shadow-md transition-all duration-300 hover:bg-blue-700 hover:scale-105" href={redirectTo}>
      {text}
    </a>
  )
}