import { useState, useEffect, useCallback } from 'react'
import NavBar from '../components/NavBar'
import api from '../api/client'

type Restaurant = 'sezatoare' | 'andys'
type RestaurantFilter = Restaurant | 'all'

interface MenuOption {
  id: number
  menu_id: number
  text: string
  text_ru: string
  sort_order: number
}

interface Menu {
  id: number
  name: string
  felul_1: string
  felul_2: string
  garnitura: string
  sort_order: number
  is_approved: boolean
  day_of_week: number
  restaurant: Restaurant
  options?: MenuOption[]
}

interface Selection {
  id: number
  user: { first_name: string; last_name: string } | null
  restaurant: Restaurant
  fel_selectat: string
  selected_at: string
  felul1_menu: Menu | null
  felul2_menu: Menu | null
  felul1_option: MenuOption | null
}

interface Report {
  report_text: string
  date: string
  restaurant: string
  total: number
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

const RESTAURANT_LABELS: Record<Restaurant, string> = {
  sezatoare: '🍲 La Șezătoare',
  andys: "🍛 Andy's",
}

const RESTAURANTS: Restaurant[] = ['sezatoare', 'andys']

const RESTAURANT_FILTERS: { key: RestaurantFilter; label: string }[] = [
  { key: 'all', label: 'Toate' },
  { key: 'sezatoare', label: '🍲 Șezătoare' },
  { key: 'andys', label: "🍛 Andy's" },
]

/** Textul alegerii, tolerant la câmpuri lipsă (orice meniu/opțiune poate fi null). */
function describeSelection(s: Selection): string {
  if (s.fel_selectat === 'fara_pranz') return '🚫 Fără prânz'

  if (s.restaurant === 'andys') {
    const menu = s.felul1_menu ?? s.felul2_menu
    const dishes = [menu?.felul_2, s.felul1_option?.text].filter(
      (x): x is string => !!x && x.trim() !== ''
    )
    if (!menu) return dishes.length ? dishes.join(' + ') : '—'
    return dishes.length ? `${menu.name}: ${dishes.join(' + ')}` : menu.name
  }

  const parts: string[] = []
  if (s.felul1_menu) {
    const dish = s.felul1_menu.felul_1?.trim()
    parts.push(dish ? `${s.felul1_menu.name}: ${dish}` : `${s.felul1_menu.name}: —`)
  }
  if (s.felul2_menu) {
    const dish = s.felul2_menu.felul_2?.trim()
    parts.push(dish ? `${s.felul2_menu.name}: ${dish}` : `${s.felul2_menu.name}: —`)
  }
  return parts.length ? parts.join(' | ') : '—'
}

function selectionSortKey(s: Selection): number {
  const menu = s.felul1_menu ?? s.felul2_menu
  return menu?.sort_order ?? 99
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
  const [filterRestaurant, setFilterRestaurant] = useState<RestaurantFilter>('all')
  const [reports, setReports] = useState<Record<Restaurant, Report | null>>({
    sezatoare: null,
    andys: null,
  })
  const [orderingStatus, setOrderingStatus] = useState<OrderingStatus | null>(null)
  const [attendance, setAttendance] = useState<AttendanceItem[]>([])
  const [showAttendance, setShowAttendance] = useState(true)
  const [botEnabled, setBotEnabled] = useState(true)
  const [botStoppedAt, setBotStoppedAt] = useState<string | null>(null)
  const [showStopModal, setShowStopModal] = useState(false)
  const [showStartModal, setShowStartModal] = useState(false)
  const [stopPassword, setStopPassword] = useState('')
  const [stopError, setStopError] = useState('')
  const [reminderStart, setReminderStart] = useState('09:00')
  const [reminderEnd, setReminderEnd] = useState('10:30')
  const [isHoliday, setIsHoliday] = useState(false)
  const [updateRequired, setUpdateRequired] = useState(false)

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

  const fetchBotStatus = useCallback(async () => {
    try {
      const { data } = await api.get('/bot/status')
      setBotEnabled(data.is_enabled)
      setBotStoppedAt(data.stopped_at)
      setReminderStart(data.reminder_start || '09:00')
      setReminderEnd(data.reminder_end || '10:30')
      setIsHoliday(data.is_holiday || false)
      setUpdateRequired(data.update_required || false)
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
      const params = new URLSearchParams({ date: selDate })
      if (filterRestaurant !== 'all') params.set('restaurant', filterRestaurant)
      const { data } = await api.get(`/selections?${params.toString()}`)
      setSelections(data)
    } catch (e) {
      console.error(e)
    }
  }, [filterDay, filterRestaurant])

  useEffect(() => {
    fetchMenus()
    fetchSelections()
    fetchOrderingStatus()
    fetchAttendance()
    fetchBotStatus()
    const interval = setInterval(() => { fetchSelections(); fetchBotStatus() }, 30000)
    return () => clearInterval(interval)
  }, [fetchMenus, fetchSelections, fetchOrderingStatus, fetchAttendance, fetchBotStatus])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  /** `restaurant` lipsă → aprobă meniurile din AMBELE restaurante. */
  const approveToday = async (restaurant?: Restaurant) => {
    try {
      const { data } = await api.post(
        '/menus/approve-today',
        restaurant ? { restaurant } : {}
      )
      await fetchMenus()
      const where = restaurant ? RESTAURANT_LABELS[restaurant] : 'toate restaurantele'
      showToast(
        `✅ ${data.approved} meniuri aprobate (${where}). Notificați: ${data.notified} utilizatori.`
      )
    } catch (e) {
      console.error(e)
      showToast('Eroare la aprobarea meniurilor!')
    }
  }

  const sendFoodArrived = async (target: RestaurantFilter) => {
    const where =
      target === 'all' ? 'toți cei care au comandat azi' : RESTAURANT_LABELS[target]
    if (!confirm(`Sigur trimiți notificarea „Mâncarea a sosit" către ${where}?`)) return
    try {
      const { data } = await api.post('/notify/food-arrived', { restaurant: target })
      showToast(`🔔 Notificare trimisă la ${data.count} persoane (${where})!`)
    } catch (e) {
      console.error(e)
      showToast('Eroare la trimiterea notificării!')
    }
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

  const saveReminderHours = async (start: string, end: string) => {
    await api.put('/bot/settings', { reminder_start: start, reminder_end: end })
    showToast(`Program notificări: ${start} — ${end}`)
  }

  const toggleHoliday = async (value: boolean) => {
    setIsHoliday(value)
    await api.put('/bot/settings', { is_holiday: value })
    showToast(value ? '🎉 Zi de sărbătoare activată — notificări oprite' : '📅 Zi lucrătoare — notificări active')
  }

  const toggleUpdateRequired = async (value: boolean) => {
    setUpdateRequired(value)
    await api.put('/bot/settings', { update_required: value })
    showToast(value ? '🔄 Notificare de actualizare activată — utilizatorii vor vedea mesajul' : '✅ Notificare de actualizare dezactivată')
  }

  const handleBotStop = async () => {
    setStopError('')
    try {
      await api.post('/bot/stop', { password: stopPassword })
      setShowStopModal(false)
      setStopPassword('')
      fetchBotStatus()
      showToast('🛑 Bot oprit! Toate notificările sunt blocate.')
    } catch {
      setStopError('Parolă incorectă')
    }
  }

  const handleBotStart = async () => {
    setStopError('')
    try {
      await api.post('/bot/start', { password: stopPassword })
      setShowStartModal(false)
      setStopPassword('')
      fetchBotStatus()
      showToast('✅ Bot pornit! Notificările funcționează normal.')
    } catch {
      setStopError('Parolă incorectă')
    }
  }

  const toggleAttendance = async (userId: number, isPresent: boolean) => {
    try {
      await api.post('/attendance', { user_id: userId, is_present: isPresent })
      setAttendance(prev => prev.map(a =>
        a.user_id === userId ? { ...a, is_present: isPresent } : a
      ))
    } catch (e) {
      console.error(e)
      showToast('Eroare la salvarea prezenței')
    }
  }

  const openEdit = (menu: Menu) => {
    setEditingMenu(menu)
    setEditFelul1(menu.felul_1 || '')
    setEditFelul2(menu.felul_2 || '')
  }

  const saveEdit = async () => {
    if (!editingMenu) return
    const payload: Record<string, string> = { felul_2: editFelul2 }
    // La Andy's felul 1 vine din opțiuni (menu_options), nu din câmpul meniului.
    if (editingMenu.restaurant !== 'andys') payload.felul_1 = editFelul1
    await api.put(`/menus/${editingMenu.id}`, payload)
    setEditingMenu(null)
    fetchMenus()
    showToast('Meniu salvat!')
  }

  const fetchReport = async (restaurant: Restaurant) => {
    try {
      const { data } = await api.get(`/report?restaurant=${restaurant}`)
      setReports(prev => ({ ...prev, [restaurant]: data }))
    } catch (e) {
      console.error(e)
      showToast('Eroare la generarea raportului!')
    }
  }

  const copyReport = (restaurant: Restaurant) => {
    const report = reports[restaurant]
    if (!report) return
    navigator.clipboard.writeText(report.report_text)
    showToast('Raport copiat!')
  }

  const downloadReport = (restaurant: Restaurant) => {
    const report = reports[restaurant]
    if (!report) return
    const blob = new Blob([report.report_text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `raport_${restaurant}_${report.date}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const isOrderingOpen = orderingStatus ? orderingStatus.ordering_open : true
  const presentCount = attendance.filter(a => a.is_present).length
  const absentCount = attendance.filter(a => !a.is_present).length

  const menusOf = (r: Restaurant) =>
    menus
      .filter(m => m.restaurant === r)
      .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))

  const sortedSelections = [...selections].sort((a, b) => {
    if (a.restaurant !== b.restaurant) return a.restaurant < b.restaurant ? -1 : 1
    return selectionSortKey(a) - selectionSortKey(b)
  })

  return (
    <>
      <NavBar />
      <div className="container">
        <p className="date-header">📅 {today}</p>

        {/* Bot emergency stop banner */}
        {!botEnabled && (
          <div className="dashboard-section" style={{ borderLeft: '4px solid #7f1d1d', background: '#fef2f2', border: '2px solid #dc2626', borderRadius: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ color: '#dc2626', margin: 0, fontSize: 18 }}>🛑 STOP CRAN — Bot oprit</h3>
                <p style={{ fontSize: 13, color: '#991b1b', marginTop: 4 }}>
                  Toate notificările sunt blocate. Niciun mesaj nu se trimite.
                  {botStoppedAt && <> Oprit la: {new Date(botStoppedAt).toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit' })}</>}
                </p>
              </div>
              <button
                className="btn btn-success"
                onClick={() => { setStopPassword(''); setStopError(''); setShowStartModal(true) }}
                style={{ fontWeight: 700, fontSize: 15 }}
              >
                ▶️ Pornește Bot
              </button>
            </div>
          </div>
        )}

        {/* Bot enabled — show stop button */}
        {botEnabled && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
            <button
              className="btn btn-danger"
              onClick={() => { setStopPassword(''); setStopError(''); setShowStopModal(true) }}
              style={{ padding: '6px 14px', fontSize: 13 }}
            >
              🛑 Stop Cran
            </button>
          </div>
        )}

        {/* Holiday + Reminder hours */}
        <div className="dashboard-section">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <label style={{
                display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                padding: '8px 16px', borderRadius: 12,
                background: isHoliday ? '#fef3c7' : '#f0fdf4',
                border: `2px solid ${isHoliday ? '#f59e0b' : '#bbf7d0'}`,
                fontWeight: 600, fontSize: 14,
                color: isHoliday ? '#92400e' : '#166534',
              }}>
                <input
                  type="checkbox"
                  checked={isHoliday}
                  onChange={(e) => toggleHoliday(e.target.checked)}
                  style={{ width: 18, height: 18, accentColor: '#f59e0b' }}
                />
                {isHoliday ? '🎉 Sărbătoare (notificări oprite)' : '📅 Zi lucrătoare'}
              </label>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, color: '#666' }}>⏰ Notificări:</span>
              <input
                type="time"
                value={reminderStart}
                onChange={(e) => { setReminderStart(e.target.value); saveReminderHours(e.target.value, reminderEnd) }}
                style={{ padding: '4px 8px', borderRadius: 8, border: '1px solid #ddd', fontSize: 14 }}
              />
              <span style={{ color: '#999' }}>—</span>
              <input
                type="time"
                value={reminderEnd}
                onChange={(e) => { setReminderEnd(e.target.value); saveReminderHours(reminderStart, e.target.value) }}
                style={{ padding: '4px 8px', borderRadius: 8, border: '1px solid #ddd', fontSize: 14 }}
              />
            </div>
            <label style={{
              display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
              padding: '8px 16px', borderRadius: 12,
              background: updateRequired ? '#dbeafe' : '#f8fafc',
              border: `2px solid ${updateRequired ? '#3b82f6' : '#e2e8f0'}`,
              fontWeight: 600, fontSize: 14,
              color: updateRequired ? '#1e40af' : '#64748b',
            }}>
              <input
                type="checkbox"
                checked={updateRequired}
                onChange={(e) => toggleUpdateRequired(e.target.checked)}
                style={{ width: 18, height: 18, accentColor: '#3b82f6' }}
              />
              {updateRequired ? '🔄 Actualizare activă' : '🔄 Notificare actualizare'}
            </label>
          </div>
        </div>

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

        {/* Section A: Today's menus, per restaurant */}
        {RESTAURANTS.map((r) => {
          const list = menusOf(r)
          const isAndys = r === 'andys'
          return (
            <div className="dashboard-section" key={r}>
              <h3>{RESTAURANT_LABELS[r]} — meniu pe azi</h3>
              {list.length === 0 && <p>Nu sunt meniuri configurate pentru azi la acest restaurant.</p>}
              {list.map((m) => (
                <div key={m.id} className={`menu-card ${m.is_approved ? 'approved' : 'not-approved'}`}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <strong>🍽 {m.name}</strong>
                    <span className={`status-badge ${m.is_approved ? 'approved' : 'pending'}`}>
                      {m.is_approved ? '✅ Aprobat' : '⚠️ Neaprobat'}
                    </span>
                  </div>

                  {isAndys ? (
                    <div style={{ margin: '8px 0', color: '#666' }}>
                      <p style={{ margin: '4px 0' }}>
                        Felul 2 (inclus): <strong>{m.felul_2 || '—'}</strong>
                        {m.garnitura ? ` | Garnitură: ${m.garnitura}` : ''}
                      </p>
                      <p style={{ margin: '4px 0' }}>Opțiuni Felul 1 (clientul alege una):</p>
                      {(m.options || []).length === 0 ? (
                        <p style={{ margin: '4px 0 0 16px', color: '#e67e22' }}>
                          ⚠️ Nicio opțiune — nimeni nu poate comanda.
                        </p>
                      ) : (
                        <ul style={{ margin: '4px 0 0 20px' }}>
                          {(m.options || []).map((o) => (
                            <li key={o.id}>{o.text || '—'}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ) : (
                    <p style={{ margin: '8px 0', color: '#666' }}>
                      Felul 1: {m.felul_1 || '—'} | Felul 2: {m.felul_2 || '—'}
                      {m.garnitura ? ` | Garnitură: ${m.garnitura}` : ''}
                    </p>
                  )}

                  <button className="btn btn-primary" onClick={() => openEdit(m)} style={{ marginRight: 8 }}>
                    ✏️ Editează
                  </button>
                </div>
              ))}
              {list.length > 0 && (
                <button className="btn btn-success" onClick={() => approveToday(r)} style={{ marginTop: 12 }}>
                  {isAndys ? "✅ Aprobă meniurile Andy's" : '✅ Aprobă meniurile Șezătoare'}
                </button>
              )}
            </div>
          )
        })}

        {menus.length > 0 && (
          <div className="dashboard-section">
            <h3>Aprobare rapidă</h3>
            <button className="btn btn-success btn-big" onClick={() => approveToday()}>
              ✅ Aprobă TOATE meniurile de azi
            </button>
          </div>
        )}

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
          <div className="filter-tabs">
            {RESTAURANT_FILTERS.map((f) => (
              <button
                key={f.key}
                className={`filter-tab ${filterRestaurant === f.key ? 'active' : ''}`}
                onClick={() => setFilterRestaurant(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Nume</th>
                <th>Restaurant</th>
                <th>Alegere</th>
                <th>Ora</th>
              </tr>
            </thead>
            <tbody>
              {sortedSelections.length === 0 && (
                <tr><td colSpan={5} style={{ textAlign: 'center', color: '#999' }}>Fără selecții</td></tr>
              )}
              {sortedSelections.map((s, idx) => (
                <tr key={s.id}>
                  <td>{idx + 1}</td>
                  <td>{s.user ? `${s.user.first_name} ${s.user.last_name}` : '—'}</td>
                  <td>{RESTAURANT_LABELS[s.restaurant] ?? s.restaurant}</td>
                  <td>{describeSelection(s)}</td>
                  <td>{s.selected_at ? new Date(s.selected_at).toLocaleTimeString('ro-RO', { hour: '2-digit', minute: '2-digit' }) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ marginTop: 8, color: '#999', fontSize: 13 }}>
            Auto-refresh la fiecare 30 secunde
          </p>
        </div>

        {/* Section C: Ordering control + Food arrived */}
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
          </div>
          <h4 style={{ marginTop: 16, marginBottom: 8 }}>🔔 Mâncarea a sosit</h4>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <button className="btn btn-success btn-big" onClick={() => sendFoodArrived('sezatoare')}>
              🔔 A sosit — Șezătoare
            </button>
            <button className="btn btn-success btn-big" onClick={() => sendFoodArrived('andys')}>
              🔔 A sosit — Andy&apos;s
            </button>
            <button className="btn btn-warning btn-big" onClick={() => sendFoodArrived('all')}>
              🔔 A sosit — TOȚI
            </button>
          </div>
        </div>

        {/* Section D: Reports — separate per restaurant */}
        <div className="dashboard-section">
          <h3>Export / Rapoarte</h3>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <button className="btn btn-primary" onClick={() => fetchReport('sezatoare')}>
              📤 Raport Șezătoare
            </button>
            <button className="btn btn-primary" onClick={() => fetchReport('andys')}>
              📤 Raport Andy&apos;s
            </button>
          </div>

          {RESTAURANTS.map((r) => {
            const report = reports[r]
            if (!report) return null
            return (
              <div key={r} style={{ marginTop: 16 }}>
                <h4 style={{ marginBottom: 8 }}>
                  {RESTAURANT_LABELS[r]} — {report.date}
                  {typeof report.total === 'number' ? ` (total: ${report.total})` : ''}
                </h4>
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
                  <button className="btn btn-primary" onClick={() => copyReport(r)}>📋 Copiază</button>
                  <button className="btn btn-warning" onClick={() => downloadReport(r)}>💾 Descarcă .txt</button>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Edit modal */}
      {editingMenu && (
        <div className="modal-overlay" onClick={() => setEditingMenu(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>✏️ Editează: {editingMenu.name}</h3>
            {editingMenu.restaurant === 'andys' ? (
              <p style={{ fontSize: 13, color: '#666', marginBottom: 12 }}>
                La Andy&apos;s, Felul 1 se editează ca opțiuni în „Gestionare Meniu".
              </p>
            ) : (
              <>
                <label>Felul 1</label>
                <input value={editFelul1} onChange={(e) => setEditFelul1(e.target.value)} />
              </>
            )}
            <label>{editingMenu.restaurant === 'andys' ? 'Felul 2 (inclus automat)' : 'Felul 2'}</label>
            <input value={editFelul2} onChange={(e) => setEditFelul2(e.target.value)} />
            <div className="btn-group">
              <button className="btn btn-success" onClick={saveEdit}>💾 Salvează</button>
              <button className="btn btn-danger" onClick={() => setEditingMenu(null)}>Anulează</button>
            </div>
          </div>
        </div>
      )}

      {/* Stop Cran modal */}
      {showStopModal && (
        <div className="modal-overlay" onClick={() => setShowStopModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 400 }}>
            <h3 style={{ color: '#dc2626' }}>🛑 Stop Cran — Oprire Bot</h3>
            <p style={{ fontSize: 14, color: '#666', marginBottom: 16 }}>
              Aceasta va opri TOATE notificările botului. Niciun mesaj nu va fi trimis utilizatorilor.
            </p>
            <label>Parola de administrator:</label>
            <input
              type="password"
              value={stopPassword}
              onChange={(e) => setStopPassword(e.target.value)}
              placeholder="Introduceți parola..."
              autoFocus
              onKeyDown={(e) => e.key === 'Enter' && handleBotStop()}
            />
            {stopError && <p className="error-msg">{stopError}</p>}
            <div className="btn-group" style={{ marginTop: 16 }}>
              <button className="btn btn-danger" onClick={handleBotStop}>🛑 Oprește Botul</button>
              <button className="btn btn-primary" onClick={() => setShowStopModal(false)}>Anulează</button>
            </div>
          </div>
        </div>
      )}

      {/* Start Bot modal */}
      {showStartModal && (
        <div className="modal-overlay" onClick={() => setShowStartModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 400 }}>
            <h3 style={{ color: '#22c55e' }}>▶️ Pornire Bot</h3>
            <p style={{ fontSize: 14, color: '#666', marginBottom: 16 }}>
              Botul va fi repornit și toate notificările vor funcționa normal.
            </p>
            <label>Parola de administrator:</label>
            <input
              type="password"
              value={stopPassword}
              onChange={(e) => setStopPassword(e.target.value)}
              placeholder="Introduceți parola..."
              autoFocus
              onKeyDown={(e) => e.key === 'Enter' && handleBotStart()}
            />
            {stopError && <p className="error-msg">{stopError}</p>}
            <div className="btn-group" style={{ marginTop: 16 }}>
              <button className="btn btn-success" onClick={handleBotStart}>▶️ Pornește Botul</button>
              <button className="btn btn-danger" onClick={() => setShowStartModal(false)}>Anulează</button>
            </div>
          </div>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
