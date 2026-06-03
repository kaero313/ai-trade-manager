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
        className="inline-flex h-5 w-5 cursor-help items-center justify-center rounded-full text-[#849495] transition hover:bg-[#00dbe9]/10 hover:text-[#7df4ff]"
      >
        <Info className="h-4 w-4" />
      </span>
      <div className="absolute left-0 top-full z-50 mt-2 hidden max-w-[280px] whitespace-normal break-words rounded-lg border border-[#3b494b]/55 bg-[#0a0e14] px-4 py-3 text-left text-xs leading-5 text-[#b9cacb] group-hover:block">
        <p className="font-bold text-[#7df4ff]">{title}</p>
        <p className="mt-2">{content}</p>
      </div>
    </span>
  )
}

export default InfoTooltip
