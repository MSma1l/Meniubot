import { useState, useEffect, useCallback } from 'react'
import NavBar from '../components/NavBar'
import api from '../api/client'

interface Menu {
  id: number
  name: string
  felul_1: string
  felul_2: string
  is_approved: boolean
  day_of_week: number
}

interface Selection {
  id: number
  user: { first_name: string; last_name: string }
  menu: { name: string }
  fel_selectat: string
  selected_at: string
}

interface Report {
  report_text: string
  portions: Record<string, { maxi: number; standard: number }>
  date: string
}

const DAYS = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri']
const FEL_LABELS: Record<string, string> = {
  felul1: 'Felul 1',
  felul2: 'Felul 2',
  ambele: 'Ambele',
  fara_pranz: '🚫 Fără prânz',
}

export default function Dashboard() {
  const [menus, setMenus] = useState<Menu[]>([])
  const [selections, setSelections] = useState<Selection[]>([])
  const [toast, setToast] = useState('')
  const [editingMenu, setEditingMenu] = useState<Menu | null>(null)
  const [editFelul1, setEditFelul1] = useState('')
  const [editFelul2, setEditFelul2] = useState('')
  const [filterDay, setFilterDay] = useState(new Date().getDay() - 1) // 0=Mon
  const [report, setReport] = useState<Report | null>(null)
  const [showReport, setShowReport] = useState(false)

  const today = new Date().toLocaleDateString('ro-RO', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })

  const getDateForDay = (dayIndex: number) => {
    const now = new Date()
    const currentDay = now.getDay() // 0=Sun
    const mondayOffset = currentDay === 0 ? -6 : 1 - currentDay
    const monday = new Date(now)
    monday.setDate(now.getDate() + mondayOffset)
    const target = new Date(monday)
    target.setDate(monday.getDate() + dayIndex)
    return target.toISOString().split('T')[0]
  }

  const fetchMenus = useCallback(async () => {
    try {
      const { data } = await api.get('/menus/today')
      setMenus(data)
    } catch (e) {
      console.error(e)
    }
  }, [])

  const fetchSelections = useCallback(async () => {
    try {
      const selDate = getDateForDay(filterDay)
      const { data } = await api.get(`/selections?date=${selDate}`)
      setSelections(data)
    } catch (e) {
      console.error(e)
    }
  }, [filterDay])

  useEffect(() => {
    fetchMenus()
    fetchSelections()
    const interval = setInterval(fetchSelections, 30000)
    return () => clearInterval(interval)
  }, [fetchMenus, fetchSelections])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  const approveAllToday = async () => {
    await api.post('/menus/approve-today')
    fetchMenus()
    showToast('Meniurile au fost aprobate!')
  }

  const sendFoodArrived = async () => {
    if (!confirm('Sigur trimiți notificarea?')) return
    const { data } = await api.post('/notify/food-arrived')
    showToast(`Notificare trimisă la ${data.count} persoane!`)
  }

  const openEdit = (menu: Menu) => {
    setEditingMenu(menu)
    setEditFelul1(menu.felul_1)
    setEditFelul2(menu.felul_2)
  }

  const saveEdit = async () => {
    if (!editingMenu) return
    await api.put(`/menus/${editingMenu.id}`, {
      felul_1: editFelul1,
      felul_2: editFelul2,
    })
    setEditingMenu(null)
    fetchMenus()
    showToast('Meniu salvat!')
  }

  const fetchReport = async () => {
    const { data } = await api.get('/report')
    setReport(data)
    setShowReport(true)
  }

  const copyReport = () => {
    if (report) {
      navigator.clipboard.writeText(report.report_text)
      showToast('Raport copiat!')
    }
  }

  const downloadReport = () => {
    if (!report) return
    const blob = new Blob([report.report_text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `raport_${report.date}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <NavBar />
      <div className="container">
        <p className="date-header">📅 {today}</p>

        {/* Section A: Today's menus */}
        <div className="dashboard-section">
          <h3>Meniu pe azi</h3>
          {menus.length === 0 && <p>Nu sunt meniuri configurate pentru azi.</p>}
          {menus.map((m) => (
            <div key={m.id} className={`menu-card ${m.is_approved ? 'approved' : 'not-approved'}`}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong>🍽 {m.name}</strong>
                <span className={`status-badge ${m.is_approved ? 'approved' : 'pending'}`}>
                  {m.is_approved ? '✅ Aprobat' : '⚠️ Neaprobat'}
                </span>
              </div>
              <p style={{ margin: '8px 0', color: '#666' }}>
                Felul 1: {m.felul_1 || '—'} | Felul 2: {m.felul_2 || '—'}
              </p>
              <button className="btn btn-primary" onClick={() => openEdit(m)} style={{ marginRight: 8 }}>
                ✏️ Editează
              </button>
            </div>
          ))}
          {menus.length > 0 && (
            <button className="btn btn-success" onClick={approveAllToday} style={{ marginTop: 12 }}>
              ✅ Aprobă toate meniurile pe azi
            </button>
          )}
        </div>

        {/* Section B: Selections */}
        <div className="dashboard-section">
          <h3>Rezultatele selecțiilor</h3>
          <div className="filter-tabs">
            {DAYS.map((d, i) => (
              <button
                key={i}
                className={`filter-tab ${filterDay === i ? 'active' : ''}`}
                onClick={() => setFilterDay(i)}
              >
                {d}
              </button>
            ))}
          </div>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Nume</th>
                <th>Meniu</th>
                <th>Selectat</th>
                <th>Ora</th>
              </tr>
            </thead>
            <tbody>
              {selections.length === 0 && (
                <tr><td colSpan={5} style={{ textAlign: 'center', color: '#999' }}>Fără selecții</td></tr>
              )}
              {selections.map((s, idx) => (
                <tr key={s.id}>
                  <td>{idx + 1}</td>
                  <td>{s.user.first_name} {s.user.last_name}</td>
                  <td>{s.menu?.name ?? '—'}</td>
                  <td>{FEL_LABELS[s.fel_selectat] || s.fel_selectat}</td>
                  <td>{new Date(s.selected_at).toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit' })}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ marginTop: 8, color: '#999', fontSize: 13 }}>
            Auto-refresh la fiecare 30 secunde
          </p>
        </div>

        {/* Section C: Food arrived */}
        <div className="dashboard-section">
          <h3>Notificare</h3>
          <button className="btn btn-success btn-big" onClick={sendFoodArrived}>
            🔔 Mâncarea a sosit — trimite notificare
          </button>
        </div>

        {/* Section D: Report */}
        <div className="dashboard-section">
          <h3>Export / Raport</h3>
          <button className="btn btn-primary" onClick={fetchReport}>
            📤 Generează raport
          </button>
          {showReport && report && (
            <div style={{ marginTop: 16 }}>
              <pre style={{
                background: '#f8f9fa',
                padding: 16,
                borderRadius: 8,
                whiteSpace: 'pre-wrap',
                fontSize: 14,
                lineHeight: 1.6,
              }}>
                {report.report_text}
              </pre>
              <div className="btn-group">
                <button className="btn btn-primary" onClick={copyReport}>📋 Copiază</button>
                <button className="btn btn-warning" onClick={downloadReport}>💾 Descarcă .txt</button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Edit modal */}
      {editingMenu && (
        <div className="modal-overlay" onClick={() => setEditingMenu(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>✏️ Editează: {editingMenu.name}</h3>
            <label>Felul 1</label>
            <input value={editFelul1} onChange={(e) => setEditFelul1(e.target.value)} />
            <label>Felul 2</label>
            <input value={editFelul2} onChange={(e) => setEditFelul2(e.target.value)} />
            <div className="btn-group">
              <button className="btn btn-success" onClick={saveEdit}>💾 Salvează</button>
              <button className="btn btn-danger" onClick={() => setEditingMenu(null)}>Anulează</button>
            </div>
          </div>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
