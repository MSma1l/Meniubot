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

interface Alert {
  menu: string
  count: number
  users: string[]
  message: string
}

interface AttendanceItem {
  user_id: number
  first_name: string
  last_name: string
  telegram_id: number
  is_present: boolean
}

interface OrderingStatus {
  ordering_open: boolean
  date: string
  closed_at: string | null
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
  const [filterDay, setFilterDay] = useState(() => {
    const dow = new Date().getDay() // 0=Sun, 1=Mon...6=Sat
    return dow >= 1 && dow <= 5 ? dow - 1 : 0 // weekend → show Monday
  })
  const [report, setReport] = useState<Report | null>(null)
  const [showReport, setShowReport] = useState(false)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [orderingStatus, setOrderingStatus] = useState<OrderingStatus | null>(null)
  const [attendance, setAttendance] = useState<AttendanceItem[]>([])
  const [showAttendance, setShowAttendance] = useState(true)

  const fetchAlerts = useCallback(async () => {
    try {
      const { data } = await api.get('/selections/alerts')
      setAlerts(data)
    } catch (e) {
      console.error(e)
    }
  }, [])

  const fetchOrderingStatus = useCallback(async () => {
    try {
      const { data } = await api.get('/ordering/status')
      setOrderingStatus(data)
    } catch (e) {
      console.error(e)
    }
  }, [])

  const fetchAttendance = useCallback(async () => {
    try {
      const { data } = await api.get('/attendance')
      setAttendance(data)
    } catch (e) {
      console.error(e)
    }
  }, [])

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
    fetchAlerts()
    fetchOrderingStatus()
    fetchAttendance()
    const interval = setInterval(() => { fetchSelections(); fetchAlerts() }, 30000)
    return () => clearInterval(interval)
  }, [fetchMenus, fetchSelections, fetchAlerts, fetchOrderingStatus, fetchAttendance])

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

  const closeOrdering = async () => {
    if (!confirm('Sigur vrei să închizi preluarea comenzilor? Toți utilizatorii vor fi notificați.')) return
    const { data } = await api.post('/ordering/close')
    fetchOrderingStatus()
    showToast(`Preluarea comenzilor închisă! Notificați: ${data.sent_count} persoane.`)
  }

  const openOrdering = async () => {
    await api.post('/ordering/open')
    fetchOrderingStatus()
    showToast('Preluarea comenzilor a fost redeschisă!')
  }

  const toggleAttendance = async (userId: number, isPresent: boolean) => {
    await api.post('/attendance', { user_id: userId, is_present: isPresent })
    setAttendance(prev => prev.map(a =>
      a.user_id === userId ? { ...a, is_present: isPresent } : a
    ))
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

  const isOrderingOpen = orderingStatus ? orderingStatus.ordering_open : true
  const presentCount = attendance.filter(a => a.is_present).length
  const absentCount = attendance.filter(a => !a.is_present).length

  return (
    <>
      <NavBar />
      <div className="container">
        <p className="date-header">📅 {today}</p>

        {/* Ordering status banner */}
        {!isOrderingOpen && (
          <div className="dashboard-section" style={{ borderLeft: '4px solid #e74c3c', background: '#fdf0f0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ color: '#e74c3c', margin: 0 }}>🔒 Preluarea comenzilor este închisă</h3>
                {orderingStatus?.closed_at && (
                  <p style={{ fontSize: 13, color: '#999', marginTop: 4 }}>
                    Închis la: {new Date(orderingStatus.closed_at).toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit' })}
                  </p>
                )}
              </div>
              <button className="btn btn-success" onClick={openOrdering}>
                🔓 Redeschide
              </button>
            </div>
          </div>
        )}

        {/* Section: Attendance */}
        <div className="dashboard-section">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>
              👥 Prezența ({presentCount} prezenți{absentCount > 0 ? `, ${absentCount} absenți` : ''})
            </h3>
            <button
              className="btn btn-primary"
              onClick={() => setShowAttendance(!showAttendance)}
              style={{ padding: '4px 12px', fontSize: 13 }}
            >
              {showAttendance ? '▲ Ascunde' : '▼ Arată'}
            </button>
          </div>
          {showAttendance && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8 }}>
              {attendance.map(a => (
                <label
                  key={a.user_id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '8px 12px',
                    background: a.is_present ? '#f0fdf4' : '#fdf0f0',
                    borderRadius: 10,
                    cursor: 'pointer',
                    border: `1px solid ${a.is_present ? '#bbf7d0' : '#fecaca'}`,
                    transition: 'all 0.2s',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={a.is_present}
                    onChange={(e) => toggleAttendance(a.user_id, e.target.checked)}
                    style={{ width: 18, height: 18, accentColor: '#22c55e' }}
                  />
                  <span style={{
                    fontSize: 14,
                    fontWeight: 500,
                    color: a.is_present ? '#166534' : '#991b1b',
                  }}>
                    {a.first_name} {a.last_name}
                  </span>
                </label>
              ))}
            </div>
          )}
        </div>

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

        {/* Section C: Alerts */}
        {alerts.length > 0 && (
          <div className="dashboard-section" style={{ borderLeft: '4px solid #e67e22', background: '#fff8f0' }}>
            <h3 style={{ color: '#e67e22' }}>⚠️ Atenție — Felul 1 nepereche!</h3>
            <p style={{ fontSize: 13, color: '#666', marginBottom: 12 }}>
              Acești utilizatori au ales doar Felul 1. Trebuie uniți cu cineva care a ales Felul 2 la același meniu pentru a forma o porție completă.
            </p>
            {alerts.map((a, i) => (
              <div key={i} style={{ padding: '10px 14px', background: 'white', borderRadius: 8, marginBottom: 8, border: '1px solid #f0e0cc' }}>
                <strong>{a.menu}</strong>: {a.count} x Felul 1
                <div style={{ fontSize: 13, color: '#888', marginTop: 4 }}>
                  {a.users.join(', ')}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Section D: Ordering control + Food arrived */}
        <div className="dashboard-section">
          <h3>Control & Notificări</h3>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {isOrderingOpen ? (
              <button className="btn btn-danger btn-big" onClick={closeOrdering}>
                🔒 Închide preluarea comenzilor
              </button>
            ) : (
              <button className="btn btn-success btn-big" onClick={openOrdering}>
                🔓 Redeschide preluarea comenzilor
              </button>
            )}
            <button className="btn btn-success btn-big" onClick={sendFoodArrived}>
              🔔 Mâncarea a sosit — trimite notificare
            </button>
          </div>
        </div>

        {/* Section E: Report */}
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
