import { useState, useEffect, useCallback } from 'react'
import NavBar from '../components/NavBar'
import api from '../api/client'

type Restaurant = 'sezatoare' | 'andys'

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
  name_ru: string
  felul_1_ru: string
  felul_2_ru: string
  garnitura_ru: string
  is_approved: boolean
  day_of_week: number
  week_start_date: string
  restaurant: Restaurant
  sort_order?: number
  options?: MenuOption[]
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

interface OptionEditFields {
  text: string
  text_ru: string
}

const DAYS = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri']

const RESTAURANTS: { key: Restaurant; label: string }[] = [
  { key: 'sezatoare', label: '🍲 La Șezătoare' },
  { key: 'andys', label: "🍛 Andy's" },
]

/** Luni din săptămâna curentă, în format YYYY-MM-DD (fără drift de fus orar). */
function currentWeekStart(): string {
  const now = new Date()
  const dow = now.getDay() // 0=Duminică
  const offset = dow === 0 ? -6 : 1 - dow
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset)
  const m = String(monday.getMonth() + 1).padStart(2, '0')
  const d = String(monday.getDate()).padStart(2, '0')
  return `${monday.getFullYear()}-${m}-${d}`
}

export default function MenuManagement() {
  const [activeRestaurant, setActiveRestaurant] = useState<Restaurant>('sezatoare')
  const [activeDay, setActiveDay] = useState(0)
  const [menus, setMenus] = useState<Menu[]>([])
  const [edits, setEdits] = useState<Record<number, EditFields>>({})
  const [optionEdits, setOptionEdits] = useState<Record<number, OptionEditFields>>({})
  const [toast, setToast] = useState('')
  const [saving, setSaving] = useState(false)

  const fetchMenus = useCallback(async () => {
    try {
      const { data } = await api.get(
        `/menus?restaurant=${activeRestaurant}&day_of_week=${activeDay}`
      )
      const list: Menu[] = data
      setMenus(list)

      const editMap: Record<number, EditFields> = {}
      const optMap: Record<number, OptionEditFields> = {}
      list.forEach((m) => {
        editMap[m.id] = {
          name: m.name || '',
          name_ru: m.name_ru || '',
          felul_1: m.felul_1 || '',
          felul_2: m.felul_2 || '',
          garnitura: m.garnitura || '',
          felul_1_ru: m.felul_1_ru || '',
          felul_2_ru: m.felul_2_ru || '',
          garnitura_ru: m.garnitura_ru || '',
        }
        ;(m.options || []).forEach((o) => {
          optMap[o.id] = { text: o.text || '', text_ru: o.text_ru || '' }
        })
      })
      setEdits(editMap)
      setOptionEdits(optMap)
    } catch (e) {
      console.error(e)
    }
  }, [activeRestaurant, activeDay])

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

  const updateOptionField = (optionId: number, field: keyof OptionEditFields, value: string) => {
    setOptionEdits((prev) => ({
      ...prev,
      [optionId]: { ...prev[optionId], [field]: value },
    }))
  }

  const saveAll = async () => {
    setSaving(true)
    try {
      const calls: Promise<unknown>[] = []

      menus.forEach((m) => {
        const edit = edits[m.id]
        if (edit) {
          const payload: Record<string, string> = {
            name: edit.name,
            name_ru: edit.name_ru,
            felul_2: edit.felul_2,
            felul_2_ru: edit.felul_2_ru,
            garnitura: edit.garnitura,
            garnitura_ru: edit.garnitura_ru,
          }
          // Felul 1 se folosește doar la Șezătoare — la Andy's e înlocuit de opțiuni
          if (m.restaurant !== 'andys') {
            payload.felul_1 = edit.felul_1
            payload.felul_1_ru = edit.felul_1_ru
          }
          calls.push(api.put(`/menus/${m.id}`, payload))
        }

        ;(m.options || []).forEach((o) => {
          const oe = optionEdits[o.id]
          if (!oe) return
          calls.push(
            api.put(`/menu-options/${o.id}`, {
              text: oe.text,
              text_ru: oe.text_ru,
              sort_order: o.sort_order,
            })
          )
        })
      })

      await Promise.all(calls)
      await fetchMenus()
      showToast('Toate meniurile au fost salvate!')
    } catch (e) {
      console.error(e)
      showToast('Eroare la salvare!')
    }
    setSaving(false)
  }

  const approveMenu = async (menuId: number) => {
    try {
      await api.post(`/menus/${menuId}/approve`)
      await fetchMenus()
      showToast('Meniu aprobat!')
    } catch (e) {
      console.error(e)
      showToast('Eroare la aprobare!')
    }
  }

  const addMenu = async () => {
    const count = menus.length + 1
    const isAndys = activeRestaurant === 'andys'
    const name = isAndys ? `Business Lunch ${count}` : `Lunch ${count}`
    const nameRu = isAndys ? `Бизнес Ланч ${count}` : `Обед ${count}`
    try {
      await api.post('/menus', {
        restaurant: activeRestaurant,
        name,
        name_ru: nameRu,
        day_of_week: activeDay,
        week_start_date: currentWeekStart(),
        sort_order: menus.length,
      })
      await fetchMenus()
      showToast(isAndys ? 'Business lunch adăugat!' : 'Meniu adăugat!')
    } catch (e) {
      console.error(e)
      showToast('Eroare la adăugare!')
    }
  }

  const deleteMenu = async (menu: Menu) => {
    if (
      !confirm(
        `Sigur ștergi „${menu.name}"?\n\nSe vor șterge și comenzile legate de acest meniu. Acțiunea nu poate fi anulată.`
      )
    )
      return
    try {
      await api.delete(`/menus/${menu.id}`)
      await fetchMenus()
      showToast('Meniu șters!')
    } catch (e) {
      console.error(e)
      showToast('Eroare la ștergere!')
    }
  }

  const addOption = async (menu: Menu) => {
    try {
      await api.post(`/menus/${menu.id}/options`, {
        text: '',
        text_ru: '',
        sort_order: (menu.options || []).length,
      })
      await fetchMenus()
      showToast('Opțiune adăugată!')
    } catch (e) {
      console.error(e)
      showToast('Eroare la adăugarea opțiunii!')
    }
  }

  const deleteOption = async (option: MenuOption) => {
    if (
      !confirm(
        `Sigur ștergi această opțiune de Felul 1?\n\nSe vor șterge și comenzile care au ales-o.`
      )
    )
      return
    try {
      await api.delete(`/menu-options/${option.id}`)
      await fetchMenus()
      showToast('Opțiune ștearsă!')
    } catch (e) {
      console.error(e)
      showToast('Eroare la ștergerea opțiunii!')
    }
  }

  const resetMenuContent = async () => {
    if (
      !confirm(
        'Sigur vrei să resetezi conținutul meniurilor (Felul 1 / Felul 2) pentru toată săptămâna? Structura meniurilor va rămâne.'
      )
    )
      return
    try {
      const { data } = await api.post('/menus/reset-content')
      await fetchMenus()
      showToast(`Conținutul a fost resetat pentru ${data.reset} meniuri!`)
    } catch (e) {
      console.error(e)
      showToast('Eroare la resetare!')
    }
  }

  const isAndys = activeRestaurant === 'andys'

  return (
    <>
      <NavBar />
      <div className="container">
        <h2 style={{ marginBottom: 20 }}>📋 Gestionare Meniu Săptămânal</h2>

        {/* Nivel 1 — restaurantul */}
        <div className="restaurant-tabs">
          {RESTAURANTS.map((r) => (
            <button
              key={r.key}
              className={`restaurant-tab ${activeRestaurant === r.key ? 'active' : ''}`}
              onClick={() => setActiveRestaurant(r.key)}
            >
              {r.label}
            </button>
          ))}
        </div>

        {/* Nivel 2 — ziua */}
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
            <p>
              Nu sunt meniuri pentru {DAYS[activeDay]} la{' '}
              {isAndys ? "Andy's" : 'La Șezătoare'}.
            </p>
          </div>
        )}

        {menus.map((m) => (
          <div key={m.id} className="menu-edit-card">
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 8,
              }}
            >
              <span className={`status-badge ${m.is_approved ? 'approved' : 'pending'}`}>
                {m.is_approved ? '✅ Aprobat' : '⚠️ Neaprobat'}
              </span>
              <button
                className="btn btn-danger"
                onClick={() => deleteMenu(m)}
                style={{ padding: '4px 12px', fontSize: 13 }}
              >
                🗑 Șterge
              </button>
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
              {!isAndys && (
                <>
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
                </>
              )}
              <div>
                <label>{isAndys ? '🇷🇴 Felul 2 (inclus automat):' : '🇷🇴 Felul 2:'}</label>
                <input
                  value={edits[m.id]?.felul_2 ?? ''}
                  onChange={(e) => updateField(m.id, 'felul_2', e.target.value)}
                  placeholder="Felul 2 (română)..."
                />
              </div>
              <div>
                <label>{isAndys ? '🇷🇺 Блюдо 2 (входит в состав):' : '🇷🇺 Блюдо 2:'}</label>
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

            {/* Opțiunile de Felul 1 — doar la Andy's */}
            {isAndys && (
              <div className="options-block">
                <h4 style={{ marginBottom: 8 }}>🥣 Opțiuni Felul 1 (clientul alege una)</h4>
                {(m.options || []).length === 0 && (
                  <p style={{ color: '#999', fontSize: 13, marginBottom: 8 }}>
                    Nicio opțiune. Adaugă cel puțin una, altfel nimeni nu poate comanda.
                  </p>
                )}
                {(m.options || []).map((o, idx) => (
                  <div key={o.id} className="option-row">
                    <span className="option-index">{idx + 1}.</span>
                    <div className="menu-lang-grid" style={{ flex: 1, marginBottom: 0 }}>
                      <div>
                        <label>🇷🇴 Opțiune:</label>
                        <input
                          value={optionEdits[o.id]?.text ?? ''}
                          onChange={(e) => updateOptionField(o.id, 'text', e.target.value)}
                          placeholder="Opțiune Felul 1 (română)..."
                        />
                      </div>
                      <div>
                        <label>🇷🇺 Вариант:</label>
                        <input
                          value={optionEdits[o.id]?.text_ru ?? ''}
                          onChange={(e) => updateOptionField(o.id, 'text_ru', e.target.value)}
                          placeholder="Вариант Блюдо 1 (русский)..."
                        />
                      </div>
                    </div>
                    <button
                      className="btn btn-danger"
                      onClick={() => deleteOption(o)}
                      style={{ padding: '4px 10px', fontSize: 13 }}
                      title="Șterge opțiunea"
                    >
                      🗑
                    </button>
                  </div>
                ))}
                <button
                  className="btn btn-primary"
                  onClick={() => addOption(m)}
                  style={{ marginTop: 8, padding: '6px 14px', fontSize: 13 }}
                >
                  ➕ Adaugă opțiune Felul 1
                </button>
              </div>
            )}

            {!m.is_approved && (
              <div style={{ marginTop: 12 }}>
                <button className="btn btn-success" onClick={() => approveMenu(m.id)}>
                  ✅ Aprobă
                </button>
              </div>
            )}
          </div>
        ))}

        <div
          style={{ display: 'flex', gap: 12, marginTop: 8, marginBottom: 20, flexWrap: 'wrap' }}
        >
          <button className="btn btn-success btn-big" onClick={addMenu}>
            {isAndys ? '➕ Adaugă business lunch' : '➕ Adaugă meniu'}
          </button>
          {menus.length > 0 && (
            <>
              <button className="btn btn-primary btn-big" onClick={saveAll} disabled={saving}>
                {saving ? '⏳ Se salvează...' : '💾 Salvează toate meniurile'}
              </button>
              <button
                className="btn btn-danger btn-big"
                onClick={resetMenuContent}
                style={{ background: '#e67e22', borderColor: '#e67e22' }}
              >
                🔄 Resetează conținutul meniurilor
              </button>
            </>
          )}
        </div>
      </div>

      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
