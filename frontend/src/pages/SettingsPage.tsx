import BotConfigForm from '../components/trading/BotConfigForm'

function SettingsPage() {
  return (
    <div className="flex h-full min-h-0 flex-col gap-6">
      <section className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
        <p className="text-sm font-semibold uppercase tracking-[0.24em] text-emerald-600 dark:text-emerald-300">
          AI Settings
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-gray-900 dark:text-gray-100">
          AI 자동매매 설정
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
          그리드 방식과 관리자용 placeholder를 걷어내고, 실제 운용 중 직접 조정할 AI 설정만 남긴 화면입니다.
        </p>
      </section>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
        <BotConfigForm />
      </div>
    </div>
  )
}

export default SettingsPage