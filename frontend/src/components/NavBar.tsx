import { useNavigate, useLocation } from 'react-router-dom'

export default function NavBar() {
  const navigate = useNavigate()
  const location = useLocation()

  const logout = () => {
    localStorage.removeItem('token')
    navigate('/login')
  }

  return (
    <nav>
      <h2>🍽 MeniuBot Admin</h2>
      <div className="nav-links">
        <a
          href="/"
          className={location.pathname === '/' ? 'active' : ''}
          onClick={(e) => { e.preventDefault(); navigate('/') }}
        >
          Dashboard
        </a>
        <a
          href="/menus"
          className={location.pathname === '/menus' ? 'active' : ''}
          onClick={(e) => { e.preventDefault(); navigate('/menus') }}
        >
          Gestionare Meniu
        </a>
        <button className="nav-btn" onClick={logout}>
          Ieșire
        </button>
      </div>
    </nav>
  )
}
