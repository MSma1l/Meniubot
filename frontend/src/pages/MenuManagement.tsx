import { useState, useEffect, useCallback } from 'react'
import NavBar from '../components/NavBar'
import api from '../api/client'

interface Menu {
  id: number
  name: string
  felul_1: string
  felul_2: string
  garnitura: string
  name_ru: string
  felul_1_ru: string
  felul_2_ru: string
  garnitura_ru: string
  is_approved: boolean
  day_of_week: number
  week_start_date: string
}

interface EditFields {
  name: string
  name_ru: string
  felul_1: string
  felul_2: string
  garnitura: string
  felul_1_ru: string
  felul_2_ru: string
  garnitura_ru: string
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
          name: m.name,
          name_ru: m.name_ru || '',
          felul_1: m.felul_1,
          felul_2: m.felul_2,
          garnitura: m.garnitura || '',
          felul_1_ru: m.felul_1_ru || '',
          felul_2_ru: m.felul_2_ru || '',
          garnitura_ru: m.garnitura_ru || '',
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
            name: edit.name,
            name_ru: edit.name_ru,
            felul_1: edit.felul_1,
            felul_2: edit.felul_2,
            garnitura: edit.garnitura,
            felul_1_ru: edit.felul_1_ru,
            felul_2_ru: edit.felul_2_ru,
            garnitura_ru: edit.garnitura_ru,
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

  const resetMenuContent = async () => {
    if (!confirm('Sigur vrei să resetezi conținutul meniurilor (Felul 1 / Felul 2) pentru toată săptămâna? Structura meniurilor va rămâne.')) return
    try {
      const { data } = await api.post('/menus/reset-content')
      fetchMenus()
      showToast(`Conținutul a fost resetat pentru ${data.reset} meniuri!`)
    } catch (e) {
      console.error(e)
      showToast('Eroare la resetare!')
    }
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
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <span className={`status-badge ${m.is_approved ? 'approved' : 'pending'}`}>
                {m.is_approved ? '✅ Aprobat' : '⚠️ Neaprobat'}
              </span>
            </div>

            <div className="menu-lang-grid">
              <div>
                <label>🇷🇴 Denumire meniu:</label>
                <input
                  value={edits[m.id]?.name ?? ''}
                  onChange={(e) => updateField(m.id, 'name', e.target.value)}
                  placeholder="Denumire (română)..."
                  style={{ fontWeight: 600 }}
                />
              </div>
              <div>
                <label>🇷🇺 Название меню:</label>
                <input
                  value={edits[m.id]?.name_ru ?? ''}
                  onChange={(e) => updateField(m.id, 'name_ru', e.target.value)}
                  placeholder="Название (русский)..."
                  style={{ fontWeight: 600 }}
                />
              </div>
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
              <div>
                <label>🇷🇴 Garnitură / Salată:</label>
                <input
                  value={edits[m.id]?.garnitura ?? ''}
                  onChange={(e) => updateField(m.id, 'garnitura', e.target.value)}
                  placeholder="Garnitură / Salată (română)..."
                />
              </div>
              <div>
                <label>🇷🇺 Гарнир / Салат:</label>
                <input
                  value={edits[m.id]?.garnitura_ru ?? ''}
                  onChange={(e) => updateField(m.id, 'garnitura_ru', e.target.value)}
                  placeholder="Гарнир / Салат (русский)..."
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
          <div style={{ display: 'flex', gap: 12, marginTop: 8, marginBottom: 20, flexWrap: 'wrap' }}>
            <button
              className="btn btn-primary btn-big"
              onClick={saveAll}
              disabled={saving}
            >
              {saving ? '⏳ Se salvează...' : '💾 Salvează toate meniurile'}
            </button>
            <button
              className="btn btn-danger btn-big"
              onClick={resetMenuContent}
              style={{ background: '#e67e22', borderColor: '#e67e22' }}
            >
              🔄 Resetează conținutul meniurilor
            </button>
          </div>
        )}
      </div>

      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
