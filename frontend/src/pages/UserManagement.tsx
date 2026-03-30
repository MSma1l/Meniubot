import { useState, useEffect, useCallback } from 'react'
import NavBar from '../components/NavBar'
import api from '../api/client'

interface User {
  id: number
  telegram_id: number
  first_name: string
  last_name: string
  language: string
  registered_at: string
  is_active: boolean
}

interface HistoryEntry {
  id: number
  date: string
  fel_selectat: string
  menu_name: string | null
  menu_felul_1: string | null
  menu_felul_2: string | null
  selected_at: string
}

interface AttendanceStat {
  user_id: number
  first_name: string
  last_name: string
  days_present: number
  days_absent: number
  total_days: number
}

interface AttendanceItem {
  user_id: number
  first_name: string
  last_name: string
  telegram_id: number
  is_present: boolean
}

const LANG_LABELS: Record<string, string> = {
  ro: '🇷🇴 Română',
  ru: '🇷🇺 Русский',
}

const FEL_LABELS: Record<string, string> = {
  felul1: 'Felul 1',
  felul2: 'Felul 2',
  ambele: 'Ambele',
  fara_pranz: '🚫 Fără prânz',
}

export default function UserManagement() {
  const [users, setUsers] = useState<User[]>([])
  const [toast, setToast] = useState('')
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [editFirstName, setEditFirstName] = useState('')
  const [editLastName, setEditLastName] = useState('')
  const [editLang, setEditLang] = useState('ro')
  const [editActive, setEditActive] = useState(true)
  const [search, setSearch] = useState('')
  const [historyUser, setHistoryUser] = useState<User | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [attendance, setAttendance] = useState<AttendanceItem[]>([])
  const [attendanceStats, setAttendanceStats] = useState<AttendanceStat[]>([])
  const [showStats, setShowStats] = useState(false)
  const [activeTab, setActiveTab] = useState<'users' | 'attendance'>('users')

  const fetchUsers = useCallback(async () => {
    try {
      const { data } = await api.get('/users')
      setUsers(data)
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

  const fetchStats = useCallback(async () => {
    try {
      const { data } = await api.get('/attendance/stats')
      setAttendanceStats(data)
    } catch (e) {
      console.error(e)
    }
  }, [])

  useEffect(() => {
    fetchUsers()
    fetchAttendance()
  }, [fetchUsers, fetchAttendance])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  const openEdit = (user: User) => {
    setEditingUser(user)
    setEditFirstName(user.first_name)
    setEditLastName(user.last_name)
    setEditLang(user.language)
    setEditActive(user.is_active)
  }

  const saveEdit = async () => {
    if (!editingUser) return
    await api.put(`/users/${editingUser.id}`, {
      first_name: editFirstName,
      last_name: editLastName,
      language: editLang,
      is_active: editActive,
    })
    setEditingUser(null)
    fetchUsers()
    showToast('Utilizator salvat!')
  }

  const deleteUser = async (user: User) => {
    if (!confirm(`Sigur vrei să ștergi pe ${user.first_name} ${user.last_name}? Toate selecțiile vor fi șterse.`)) return
    await api.delete(`/users/${user.id}`)
    fetchUsers()
    showToast('Utilizator șters!')
  }

  const openHistory = async (user: User) => {
    setHistoryUser(user)
    setHistoryLoading(true)
    try {
      const { data } = await api.get(`/users/${user.id}/history`)
      setHistory(data)
    } catch (e) {
      console.error(e)
      setHistory([])
    }
    setHistoryLoading(false)
  }

  const toggleAttendance = async (userId: number, isPresent: boolean) => {
    await api.post('/attendance', { user_id: userId, is_present: isPresent })
    setAttendance(prev => prev.map(a =>
      a.user_id === userId ? { ...a, is_present: isPresent } : a
    ))
  }

  const loadStats = () => {
    fetchStats()
    setShowStats(true)
  }

  const filtered = users.filter((u) => {
    const q = search.toLowerCase()
    if (!q) return true
    return (
      u.first_name.toLowerCase().includes(q) ||
      u.last_name.toLowerCase().includes(q) ||
      String(u.telegram_id).includes(q)
    )
  })

  return (
    <>
      <NavBar />
      <div className="container">
        <h2 style={{ marginBottom: 20 }}>👥 Gestionare Utilizatori</h2>

        {/* Tab switcher */}
        <div className="filter-tabs" style={{ marginBottom: 16 }}>
          <button
            className={`filter-tab ${activeTab === 'users' ? 'active' : ''}`}
            onClick={() => setActiveTab('users')}
          >
            👥 Utilizatori
          </button>
          <button
            className={`filter-tab ${activeTab === 'attendance' ? 'active' : ''}`}
            onClick={() => setActiveTab('attendance')}
          >
            📋 Prezența azi
          </button>
        </div>

        {/* Users tab */}
        {activeTab === 'users' && (
          <div className="dashboard-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <span style={{ color: '#666', fontSize: 14 }}>
                Total: <strong>{users.length}</strong> utilizatori
                {users.filter(u => u.is_active).length !== users.length && (
                  <> ({users.filter(u => u.is_active).length} activi)</>
                )}
              </span>
              <input
                type="text"
                placeholder="Caută..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{ padding: '6px 12px', borderRadius: 8, border: '1px solid #ddd', width: 200 }}
              />
            </div>

            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Nume</th>
                  <th>Telegram ID</th>
                  <th>Limba</th>
                  <th>Status</th>
                  <th>Înregistrat</th>
                  <th>Acțiuni</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr><td colSpan={7} style={{ textAlign: 'center', color: '#999' }}>Niciun utilizator</td></tr>
                )}
                {filtered.map((u, idx) => (
                  <tr
                    key={u.id}
                    style={{ opacity: u.is_active ? 1 : 0.5, cursor: 'pointer' }}
                    onClick={() => openHistory(u)}
                  >
                    <td>{idx + 1}</td>
                    <td><strong>{u.first_name} {u.last_name}</strong></td>
                    <td style={{ fontFamily: 'monospace', fontSize: 13 }}>{u.telegram_id}</td>
                    <td>{LANG_LABELS[u.language] || u.language}</td>
                    <td>
                      <span className={`status-badge ${u.is_active ? 'approved' : 'pending'}`}>
                        {u.is_active ? 'Activ' : 'Inactiv'}
                      </span>
                    </td>
                    <td style={{ fontSize: 13, color: '#666' }}>
                      {u.registered_at ? new Date(u.registered_at).toLocaleDateString('ro-RO') : '—'}
                    </td>
                    <td>
                      <button
                        className="btn btn-primary"
                        onClick={(e) => { e.stopPropagation(); openEdit(u) }}
                        style={{ marginRight: 6, padding: '4px 10px', fontSize: 13 }}
                      >
                        ✏️
                      </button>
                      <button
                        className="btn btn-danger"
                        onClick={(e) => { e.stopPropagation(); deleteUser(u) }}
                        style={{ padding: '4px 10px', fontSize: 13 }}
                      >
                        🗑️
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Attendance tab */}
        {activeTab === 'attendance' && (
          <>
            <div className="dashboard-section">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <span style={{ color: '#666', fontSize: 14 }}>
                  Prezenți: <strong style={{ color: '#22c55e' }}>{attendance.filter(a => a.is_present).length}</strong>
                  {' '} / Absenți: <strong style={{ color: '#ef4444' }}>{attendance.filter(a => !a.is_present).length}</strong>
                  {' '} / Total: <strong>{attendance.length}</strong>
                </span>
                <button className="btn btn-primary" onClick={loadStats} style={{ padding: '6px 14px', fontSize: 13 }}>
                  📊 Statistici săptămâna
                </button>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 10 }}>
                {attendance.map(a => (
                  <label
                    key={a.user_id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      padding: '10px 14px',
                      background: a.is_present ? '#f0fdf4' : '#fef2f2',
                      borderRadius: 12,
                      cursor: 'pointer',
                      border: `1px solid ${a.is_present ? '#bbf7d0' : '#fecaca'}`,
                      transition: 'all 0.2s',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={a.is_present}
                      onChange={(e) => toggleAttendance(a.user_id, e.target.checked)}
                      style={{ width: 20, height: 20, accentColor: '#22c55e' }}
                    />
                    <div>
                      <div style={{
                        fontWeight: 600,
                        fontSize: 14,
                        color: a.is_present ? '#166534' : '#991b1b',
                      }}>
                        {a.first_name} {a.last_name}
                      </div>
                      <div style={{ fontSize: 12, color: '#999' }}>
                        {a.is_present ? '✅ Prezent' : '❌ Absent'}
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {/* Statistics modal */}
            {showStats && (
              <div className="dashboard-section">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <h3 style={{ margin: 0 }}>📊 Statistici prezență (săptămâna curentă)</h3>
                  <button className="btn btn-danger" onClick={() => setShowStats(false)} style={{ padding: '4px 12px', fontSize: 13 }}>
                    Închide
                  </button>
                </div>
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Nume</th>
                      <th>Zile prezent</th>
                      <th>Zile absent</th>
                      <th>Rata prezență</th>
                    </tr>
                  </thead>
                  <tbody>
                    {attendanceStats.map((s, idx) => {
                      const rate = s.total_days > 0 ? Math.round((s.days_present / s.total_days) * 100) : 100
                      return (
                        <tr key={s.user_id}>
                          <td>{idx + 1}</td>
                          <td><strong>{s.first_name} {s.last_name}</strong></td>
                          <td style={{ color: '#22c55e', fontWeight: 600 }}>{s.days_present}</td>
                          <td style={{ color: s.days_absent > 0 ? '#ef4444' : '#999', fontWeight: 600 }}>{s.days_absent}</td>
                          <td>
                            <div style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 8,
                            }}>
                              <div style={{
                                width: 60,
                                height: 8,
                                background: '#e5e7eb',
                                borderRadius: 4,
                                overflow: 'hidden',
                              }}>
                                <div style={{
                                  width: `${rate}%`,
                                  height: '100%',
                                  background: rate >= 80 ? '#22c55e' : rate >= 50 ? '#f59e0b' : '#ef4444',
                                  borderRadius: 4,
                                }} />
                              </div>
                              <span style={{ fontSize: 13, fontWeight: 600 }}>{rate}%</span>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>

      {/* History modal */}
      {historyUser && (
        <div className="modal-overlay" onClick={() => setHistoryUser(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 600, maxHeight: '80vh', overflow: 'auto' }}>
            <h3>📋 Istoria selecțiilor: {historyUser.first_name} {historyUser.last_name}</h3>
            {historyLoading ? (
              <p style={{ textAlign: 'center', color: '#999', padding: 20 }}>Se încarcă...</p>
            ) : history.length === 0 ? (
              <p style={{ textAlign: 'center', color: '#999', padding: 20 }}>Nicio selecție înregistrată</p>
            ) : (
              <table style={{ width: '100%', fontSize: 13 }}>
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Meniu</th>
                    <th>Ales</th>
                    <th>Detalii</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.id}>
                      <td style={{ whiteSpace: 'nowrap', fontWeight: 600 }}>
                        {h.date ? new Date(h.date + 'T00:00:00').toLocaleDateString('ro-RO', {
                          weekday: 'short',
                          day: 'numeric',
                          month: 'short',
                          year: 'numeric',
                        }) : '—'}
                      </td>
                      <td>{h.menu_name ?? '—'}</td>
                      <td>
                        <span className={`status-badge ${h.fel_selectat === 'fara_pranz' ? 'pending' : 'approved'}`}>
                          {FEL_LABELS[h.fel_selectat] || h.fel_selectat}
                        </span>
                      </td>
                      <td style={{ fontSize: 12, color: '#888' }}>
                        {h.fel_selectat === 'fara_pranz' ? '—' : (
                          <>
                            {(h.fel_selectat === 'felul1' || h.fel_selectat === 'ambele') && h.menu_felul_1 && (
                              <div>F1: {h.menu_felul_1}</div>
                            )}
                            {(h.fel_selectat === 'felul2' || h.fel_selectat === 'ambele') && h.menu_felul_2 && (
                              <div>F2: {h.menu_felul_2}</div>
                            )}
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="btn-group" style={{ marginTop: 16 }}>
              <button className="btn btn-primary" onClick={() => { setHistoryUser(null); openEdit(historyUser) }}>
                ✏️ Editează utilizator
              </button>
              <button className="btn btn-danger" onClick={() => setHistoryUser(null)}>Închide</button>
            </div>
          </div>
        </div>
      )}

      {/* Edit modal */}
      {editingUser && (
        <div className="modal-overlay" onClick={() => setEditingUser(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>✏️ Editează: {editingUser.first_name} {editingUser.last_name}</h3>
            <label>Prenume</label>
            <input value={editFirstName} onChange={(e) => setEditFirstName(e.target.value)} />
            <label>Nume de familie</label>
            <input value={editLastName} onChange={(e) => setEditLastName(e.target.value)} />
            <label>Limba</label>
            <select value={editLang} onChange={(e) => setEditLang(e.target.value)} style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #ddd', width: '100%', marginBottom: 12 }}>
              <option value="ro">🇷🇴 Română</option>
              <option value="ru">🇷🇺 Русский</option>
            </select>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={editActive}
                onChange={(e) => setEditActive(e.target.checked)}
                style={{ width: 18, height: 18 }}
              />
              Utilizator activ
            </label>
            <div className="btn-group">
              <button className="btn btn-success" onClick={saveEdit}>💾 Salvează</button>
              <button className="btn btn-danger" onClick={() => setEditingUser(null)}>Anulează</button>
            </div>
          </div>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
