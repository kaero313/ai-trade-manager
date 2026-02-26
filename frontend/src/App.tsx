import { BrowserRouter, Route, Routes } from 'react-router-dom'

import Layout from './components/layout/Layout'
import DashboardPage from './pages/DashboardPage'

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
