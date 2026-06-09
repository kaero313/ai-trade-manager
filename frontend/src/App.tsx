import { BrowserRouter, Route, Routes } from 'react-router-dom'

import AdminAuthProvider from './components/common/AdminAuthProvider'
import Layout from './components/layout/Layout'
import { ThemeProvider } from './contexts/ThemeContext'
import AIChatPage from './pages/AIChatPage'
import DashboardPage from './pages/DashboardPage'
import LaboratoryPage from './pages/LaboratoryPage'
import PortfolioPage from './pages/PortfolioPage'
import SettingsPage from './pages/SettingsPage'

function App() {
  return (
    <AdminAuthProvider>
      <ThemeProvider>
        <BrowserRouter>
          <Layout>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/portfolio" element={<PortfolioPage />} />
              <Route path="/chat" element={<AIChatPage />} />
              <Route path="/laboratory" element={<LaboratoryPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </ThemeProvider>
    </AdminAuthProvider>
  )
}

export default App
