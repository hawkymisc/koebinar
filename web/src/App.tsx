import { useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import './App.css'
import { getToken, setToken } from './api/client'
import { WebinarDetailPage } from './pages/WebinarDetailPage'
import { WebinarListPage } from './pages/WebinarListPage'

function TokenField() {
  const [value, setValue] = useState(getToken())

  return (
    <label className="token-field">
      APIトークン
      <input
        value={value}
        onChange={(e) => {
          setValue(e.target.value)
          setToken(e.target.value)
        }}
      />
    </label>
  )
}

function App() {
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
        <Routes>
          <Route path="/" element={<WebinarListPage />} />
          <Route path="/webinars/:id" element={<WebinarDetailPage />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
