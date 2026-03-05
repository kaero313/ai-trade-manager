import { BrowserRouter, Route, Routes } from 'react-router-dom'

import Layout from './components/layout/Layout'
import DashboardPage from './pages/DashboardPage'
import LaboratoryPage from './pages/LaboratoryPage'

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/laboratory" element={<LaboratoryPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
