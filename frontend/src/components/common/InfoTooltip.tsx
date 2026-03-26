import { Info } from 'lucide-react'

interface InfoTooltipProps {
  title: string
  content: string
  className?: string
}

function InfoTooltip({ title, content, className = '' }: InfoTooltipProps) {
  return (
    <span className={`group relative inline-flex shrink-0 ${className}`}>
      <span
        aria-label={title}
        className="inline-flex h-5 w-5 cursor-help items-center justify-center rounded-full text-gray-400 transition hover:bg-gray-100 hover:text-gray-700 dark:text-gray-500 dark:hover:bg-gray-700 dark:hover:text-gray-200"
      >
        <Info className="h-4 w-4" />
      </span>
      <div className="absolute left-0 top-full z-50 mt-2 hidden max-w-[280px] whitespace-normal break-words rounded-xl bg-gray-900 px-4 py-3 text-left text-xs leading-5 text-white shadow-lg ring-1 ring-gray-800 group-hover:block dark:bg-white dark:text-gray-900 dark:ring-gray-200">
        <p className="font-semibold">{title}</p>
        <p className="mt-2">{content}</p>
      </div>
    </span>
  )
}

export default InfoTooltip
