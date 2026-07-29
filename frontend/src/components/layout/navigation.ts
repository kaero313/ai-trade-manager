import {
  Bot,
  FlaskConical,
  LayoutDashboard,
  Settings,
  WalletCards,
  type LucideIcon,
} from 'lucide-react'

export interface NavigationItem {
  to: string
  label: string
  description: string
  icon: LucideIcon
  end?: boolean
}

export const NAVIGATION_ITEMS: readonly NavigationItem[] = [
  {
    to: '/',
    label: '대시보드',
    description: '시장과 봇 운영 현황',
    icon: LayoutDashboard,
    end: true,
  },
  {
    to: '/portfolio',
    label: '포트폴리오',
    description: '실제 계좌 자산 현황',
    icon: WalletCards,
  },
  {
    to: '/laboratory',
    label: '정책 검증',
    description: '규칙 기반 참고 백테스트',
    icon: FlaskConical,
  },
  {
    to: '/chat',
    label: 'AI 뱅커',
    description: '분석 대화와 설정 제안',
    icon: Bot,
  },
  {
    to: '/settings',
    label: '설정',
    description: '운영 설정과 제공자 상태',
    icon: Settings,
  },
] as const

export function resolveNavigationClassName(
  { isActive }: { isActive: boolean },
  collapsed = false,
): string {
  return [
    'group flex min-h-11 items-center rounded-lg border py-2.5 text-sm font-semibold',
    collapsed ? 'justify-center gap-0 px-2' : 'gap-3 px-3',
    'transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring',
    isActive
      ? 'border-brand/25 bg-brand/12 text-brand-bright'
      : 'border-transparent text-content-secondary hover:border-border-subtle hover:bg-surface-high hover:text-content',
  ].join(' ')
}
