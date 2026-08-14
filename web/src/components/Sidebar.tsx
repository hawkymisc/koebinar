import { NavLink } from 'react-router-dom'
import type { Tenant } from '../api/types'

export function Sidebar({ tenant, onLogout }: { tenant: Tenant; onLogout: () => void }) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-mark" aria-hidden="true">K</span>
        <div>
          <strong>Koebinar</strong>
          <small>Operator Console</small>
        </div>
      </div>

      <div className="workspace-card">
        <span className="workspace-label">WORKSPACE</span>
        <strong>{tenant.name}</strong>
        <small>{tenant.id}</small>
      </div>

      <nav className="sidebar-nav" aria-label="メインナビゲーション">
        <NavLink to="/" end>
          <span aria-hidden="true">▦</span>
          ウェビナー
        </NavLink>
        <NavLink to="/settings/integrations">
          <span aria-hidden="true">⌁</span>
          連携設定
        </NavLink>
      </nav>

      <button className="sidebar-logout" type="button" onClick={onLogout}>
        ログアウト
      </button>
    </aside>
  )
}
