import { Fragment, type ReactNode } from 'react'

// AI 답변은 마크다운으로 온다. 번들을 늘리지 않으려고 라이브러리 대신
// 실제로 쓰이는 문법(제목, 목록, 굵게, 구분선)만 처리한다.

const EMPHASIS_PATTERN = /\*\*([^*]+)\*\*|\*([^*]+)\*/g

function renderInline(text: string): ReactNode {
  const nodes: ReactNode[] = []
  let last = 0
  let match: RegExpExecArray | null
  EMPHASIS_PATTERN.lastIndex = 0
  while ((match = EMPHASIS_PATTERN.exec(text)) !== null) {
    if (match.index > last) {
      nodes.push(text.slice(last, match.index))
    }
    nodes.push(
      match[1] !== undefined ? (
        <strong key={`b-${match.index}`}>{match[1]}</strong>
      ) : (
        <em key={`i-${match.index}`}>{match[2]}</em>
      ),
    )
    last = EMPHASIS_PATTERN.lastIndex
  }
  if (last < text.length) {
    nodes.push(text.slice(last))
  }
  return nodes.map((node, index) => <Fragment key={index}>{node}</Fragment>)
}

export function MarkdownLite({ text, className }: { text: string; className?: string }) {
  const lines = String(text ?? '').split('\n')

  return (
    <div className={className}>
      {lines.map((rawLine, index) => {
        const line = rawLine.trimEnd()
        const key = `l-${index}`

        if (!line.trim()) {
          return <div key={key} className="h-2" />
        }
        if (/^-{3,}$/.test(line.trim())) {
          return <hr key={key} className="my-3 border-border-subtle" />
        }

        const heading = line.match(/^(#{1,6})\s+(.*)$/)
        if (heading) {
          return (
            <div key={key} className="mt-3 mb-1 font-semibold text-content">
              {renderInline(heading[2])}
            </div>
          )
        }

        const bullet = line.match(/^(\s*)[*-]\s+(.*)$/)
        if (bullet) {
          const depth = Math.min(Math.floor(bullet[1].length / 2), 3)
          return (
            <div key={key} className="flex gap-2" style={{ paddingLeft: `${depth * 14}px` }}>
              <span className="select-none text-content-muted">•</span>
              <span className="min-w-0 flex-1 break-words">{renderInline(bullet[2])}</span>
            </div>
          )
        }

        const ordered = line.match(/^(\s*)(\d+)\.\s+(.*)$/)
        if (ordered) {
          const depth = Math.min(Math.floor(ordered[1].length / 2), 3)
          return (
            <div key={key} className="flex gap-2" style={{ paddingLeft: `${depth * 14}px` }}>
              <span className="select-none text-content-muted">{ordered[2]}.</span>
              <span className="min-w-0 flex-1 break-words">{renderInline(ordered[3])}</span>
            </div>
          )
        }

        return (
          <p key={key} className="break-words">
            {renderInline(line)}
          </p>
        )
      })}
    </div>
  )
}
