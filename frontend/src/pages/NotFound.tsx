import { CaretCircleLeftIcon, ImageBrokenIcon, NumberSquareFourIcon, NumberSquareZeroIcon } from "@phosphor-icons/react";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-gray-100/60 backdrop-blur-sm flex items-center justify-center">
      <div className="flex flex-col border border-gray-300 w-100 bg-white rounded-sm shadow-2xl px-20 py-10 gap-5">
        <div className="justify-center flex-1 flex items-center">
          <ImageBrokenIcon size={32} />
          <NumberSquareFourIcon size={32} className="text-red-400" />
          <NumberSquareZeroIcon size={32} className="text-red-400" />
          <NumberSquareFourIcon size={32} className="text-red-400" />
        </div>
        <span>The page you are looking for does not seem to exist</span>
        <a className="w-fit flex items-center gap-1 transition-transform duration-25 ease-in-out hover:scale-105 hover:underline" href="/">
          <CaretCircleLeftIcon size={32} />
          Go back
        </a>
      </div>
    </div>
  )
}

