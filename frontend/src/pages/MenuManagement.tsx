import { useState, useEffect, useCallback } from 'react'
import NavBar from '../components/NavBar'
import api from '../api/client'

interface Menu {
  id: number
  name: string
  felul_1: string
  felul_2: string
  name_ru: string
  felul_1_ru: string
  felul_2_ru: string
  is_approved: boolean
  day_of_week: number
  week_start_date: string
}

interface EditFields {
  felul_1: string
  felul_2: string
  felul_1_ru: string
  felul_2_ru: string
}

const DAYS = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri']

export default function MenuManagement() {
  const [activeDay, setActiveDay] = useState(0)
  const [menus, setMenus] = useState<Menu[]>([])
  const [edits, setEdits] = useState<Record<number, EditFields>>({})
  const [toast, setToast] = useState('')
  const [saving, setSaving] = useState(false)

  const fetchMenus = useCallback(async () => {
    try {
      const { data } = await api.get(`/menus?day_of_week=${activeDay}`)
      setMenus(data)
      const editMap: Record<number, EditFields> = {}
      data.forEach((m: Menu) => {
        editMap[m.id] = {
          felul_1: m.felul_1,
          felul_2: m.felul_2,
          felul_1_ru: m.felul_1_ru || '',
          felul_2_ru: m.felul_2_ru || '',
        }
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

  const updateField = (menuId: number, field: keyof EditFields, value: string) => {
    setEdits((prev) => ({
      ...prev,
      [menuId]: { ...prev[menuId], [field]: value },
    }))
  }

  const saveAll = async () => {
    setSaving(true)
    try {
      await Promise.all(
        menus.map((m) => {
          const edit = edits[m.id]
          if (!edit) return Promise.resolve()
          return api.put(`/menus/${m.id}`, {
            felul_1: edit.felul_1,
            felul_2: edit.felul_2,
            felul_1_ru: edit.felul_1_ru,
            felul_2_ru: edit.felul_2_ru,
          })
        })
      )
      fetchMenus()
      showToast('Toate meniurile au fost salvate!')
    } catch (e) {
      console.error(e)
      showToast('Eroare la salvare!')
    }
    setSaving(false)
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
              <h4>🍽 {m.name} {m.name_ru ? `/ ${m.name_ru}` : ''}</h4>
              <span className={`status-badge ${m.is_approved ? 'approved' : 'pending'}`}>
                {m.is_approved ? '✅ Aprobat' : '⚠️ Neaprobat'}
              </span>
            </div>

            <div className="menu-lang-grid">
              <div>
                <label>🇷🇴 Felul 1:</label>
                <input
                  value={edits[m.id]?.felul_1 ?? ''}
                  onChange={(e) => updateField(m.id, 'felul_1', e.target.value)}
                  placeholder="Felul 1 (română)..."
                />
              </div>
              <div>
                <label>🇷🇺 Блюдо 1:</label>
                <input
                  value={edits[m.id]?.felul_1_ru ?? ''}
                  onChange={(e) => updateField(m.id, 'felul_1_ru', e.target.value)}
                  placeholder="Блюдо 1 (русский)..."
                />
              </div>
              <div>
                <label>🇷🇴 Felul 2:</label>
                <input
                  value={edits[m.id]?.felul_2 ?? ''}
                  onChange={(e) => updateField(m.id, 'felul_2', e.target.value)}
                  placeholder="Felul 2 (română)..."
                />
              </div>
              <div>
                <label>🇷🇺 Блюдо 2:</label>
                <input
                  value={edits[m.id]?.felul_2_ru ?? ''}
                  onChange={(e) => updateField(m.id, 'felul_2_ru', e.target.value)}
                  placeholder="Блюдо 2 (русский)..."
                />
              </div>
            </div>

            {!m.is_approved && (
              <div style={{ marginTop: 12 }}>
                <button className="btn btn-success" onClick={() => approveMenu(m.id)}>
                  ✅ Aprobă
                </button>
              </div>
            )}
          </div>
        ))}

        {menus.length > 0 && (
          <button
            className="btn btn-primary btn-big"
            onClick={saveAll}
            disabled={saving}
            style={{ marginTop: 8, marginBottom: 20 }}
          >
            {saving ? '⏳ Se salvează...' : '💾 Salvează toate meniurile'}
          </button>
        )}
      </div>

      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
