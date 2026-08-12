import { useState } from 'react'
import { Link, Outlet, Route, Routes } from 'react-router-dom'
import './App.css'
import { getToken, setToken } from './api/client'
import { WebinarDetailPage } from './pages/WebinarDetailPage'
import { WebinarListPage } from './pages/WebinarListPage'
import { ViewerPage } from './pages/ViewerPage'

function TokenField() {
  const [value, setValue] = useState(getToken())

  return (
    <label className="token-field">
      APIトークン
      <input
        type="password"
        autoComplete="off"
        value={value}
        onChange={(e) => {
          setValue(e.target.value)
          setToken(e.target.value)
        }}
      />
    </label>
  )
}

function AdminLayout() {
  return (
    <div className="layout">
      <header className="header">
        <Link className="brand" to="/">
          <h1>Koebinar</h1>
          <span className="tagline">あなたの声が、あなたの代わりに登壇する。</span>
        </Link>
        <TokenField />
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/watch/:id" element={<ViewerPage />} />
      <Route element={<AdminLayout />}>
        <Route path="/" element={<WebinarListPage />} />
        <Route path="/webinars/:id" element={<WebinarDetailPage />} />
      </Route>
    </Routes>
  )
}

export default App
