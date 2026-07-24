import { Loader2 } from 'lucide-react'

/**
 * 지연 로딩되는 페이지 청크를 가져오는 동안 표시하는 Suspense fallback.
 * 레이아웃(Navbar/Sidebar) 안쪽 본문 영역만 채우도록 최소 높이만 확보한다.
 */
function RouteFallback() {
  return (
    <div
      className="flex min-h-[60vh] w-full items-center justify-center"
      role="status"
      aria-live="polite"
    >
      <div className="flex flex-col items-center gap-3 text-content-secondary">
        <Loader2 className="h-6 w-6 animate-spin text-brand" aria-hidden="true" />
        <span className="text-sm">화면을 불러오는 중입니다.</span>
      </div>
    </div>
  )
}

export default RouteFallback
