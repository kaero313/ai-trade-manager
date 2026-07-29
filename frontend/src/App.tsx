import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'

import AdminAuthProvider from './components/common/AdminAuthProvider'
import AdminSessionGate from './components/common/AdminSessionGate'
import RouteFallback from './components/common/RouteFallback'
import Layout from './components/layout/Layout'
import { ThemeProvider } from './contexts/ThemeContext'

// 페이지는 라우트 진입 시점에 개별 청크로 지연 로딩한다. 초기 번들에서 recharts·
// lightweight-charts 등 무거운 시각화 의존성을 해당 페이지 청크로 분리하기 위함이다.
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const PortfolioPage = lazy(() => import('./pages/PortfolioPage'))
const AIChatPage = lazy(() => import('./pages/AIChatPage'))
const LaboratoryPage = lazy(() => import('./pages/LaboratoryPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))

function App() {
  return (
    <AdminAuthProvider>
      <AdminSessionGate>
        <ThemeProvider>
          <BrowserRouter>
            <Layout>
              <Suspense fallback={<RouteFallback />}>
                <Routes>
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/portfolio" element={<PortfolioPage />} />
                  <Route path="/chat" element={<AIChatPage />} />
                  <Route path="/laboratory" element={<LaboratoryPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                </Routes>
              </Suspense>
            </Layout>
          </BrowserRouter>
        </ThemeProvider>
      </AdminSessionGate>
    </AdminAuthProvider>
  )
}

export default App
