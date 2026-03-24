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
  week_start_date: string
}

const DAYS = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri']

export default function MenuManagement() {
  const [activeDay, setActiveDay] = useState(0)
  const [menus, setMenus] = useState<Menu[]>([])
  const [edits, setEdits] = useState<Record<number, { felul_1: string; felul_2: string }>>({})
  const [toast, setToast] = useState('')

  const fetchMenus = useCallback(async () => {
    try {
      const { data } = await api.get(`/menus?day_of_week=${activeDay}`)
      setMenus(data)
      const editMap: Record<number, { felul_1: string; felul_2: string }> = {}
      data.forEach((m: Menu) => {
        editMap[m.id] = { felul_1: m.felul_1, felul_2: m.felul_2 }
      })
      setEdits(editMap)
    } catch (e) {
      console.error(e)
    }
  }, [activeDay])

  useEffect(() => {
    fetchMenus()
  }, [fetchMenus])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  const updateField = (menuId: number, field: 'felul_1' | 'felul_2', value: string) => {
    setEdits((prev) => ({
      ...prev,
      [menuId]: { ...prev[menuId], [field]: value },
    }))
  }

  const saveMenu = async (menuId: number) => {
    const edit = edits[menuId]
    if (!edit) return
    await api.put(`/menus/${menuId}`, {
      felul_1: edit.felul_1,
      felul_2: edit.felul_2,
    })
    fetchMenus()
    showToast('Meniu salvat!')
  }

  const approveMenu = async (menuId: number) => {
    await api.post(`/menus/${menuId}/approve`)
    fetchMenus()
    showToast('Meniu aprobat!')
  }

  return (
    <>
      <NavBar />
      <div className="container">
        <h2 style={{ marginBottom: 20 }}>📋 Gestionare Meniu Săptămânal</h2>

        <div className="day-tabs">
          {DAYS.map((d, i) => (
            <button
              key={i}
              className={`day-tab ${activeDay === i ? 'active' : ''}`}
              onClick={() => setActiveDay(i)}
            >
              {d}
            </button>
          ))}
        </div>

        {menus.length === 0 && (
          <div className="dashboard-section">
            <p>Nu sunt meniuri pentru {DAYS[activeDay]}.</p>
          </div>
        )}

        {menus.map((m) => (
          <div key={m.id} className="menu-edit-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h4>🍽 {m.name}</h4>
              <span className={`status-badge ${m.is_approved ? 'approved' : 'pending'}`}>
                {m.is_approved ? '✅ Aprobat' : '⚠️ Neaprobat'}
              </span>
            </div>

            <label>Felul 1:</label>
            <input
              value={edits[m.id]?.felul_1 ?? ''}
              onChange={(e) => updateField(m.id, 'felul_1', e.target.value)}
              placeholder="Introduceți felul 1..."
            />

            <label>Felul 2:</label>
            <input
              value={edits[m.id]?.felul_2 ?? ''}
              onChange={(e) => updateField(m.id, 'felul_2', e.target.value)}
              placeholder="Introduceți felul 2..."
            />

            <div className="btn-group">
              <button className="btn btn-primary" onClick={() => saveMenu(m.id)}>
                💾 Salvează
              </button>
              {!m.is_approved && (
                <button className="btn btn-success" onClick={() => approveMenu(m.id)}>
                  ✅ Aprobă
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
