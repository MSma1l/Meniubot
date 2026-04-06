import { useState, useEffect, useCallback } from 'react'
import NavBar from '../components/NavBar'
import api from '../api/client'

interface Instruction {
  id: number
  title: string
  title_ru: string
  content: string
  content_ru: string
  image_filename: string
  sort_order: number
  is_active: boolean
}

export default function Instructions() {
  const [instructions, setInstructions] = useState<Instruction[]>([])
  const [toast, setToast] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)

  // Form state
  const [title, setTitle] = useState('')
  const [titleRu, setTitleRu] = useState('')
  const [content, setContent] = useState('')
  const [contentRu, setContentRu] = useState('')
  const [sortOrder, setSortOrder] = useState(0)
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const fetchInstructions = useCallback(async () => {
    try {
      const { data } = await api.get('/instructions/all')
      setInstructions(data)
    } catch (e) {
      console.error(e)
    }
  }, [])

  useEffect(() => {
    fetchInstructions()
  }, [fetchInstructions])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  const resetForm = () => {
    setTitle('')
    setTitleRu('')
    setContent('')
    setContentRu('')
    setSortOrder(0)
    setImageFile(null)
    setImagePreview(null)
    setEditingId(null)
    setShowForm(false)
  }

  const openNew = () => {
    resetForm()
    setSortOrder(instructions.length)
    setShowForm(true)
  }

  const openEdit = (instr: Instruction) => {
    setEditingId(instr.id)
    setTitle(instr.title)
    setTitleRu(instr.title_ru)
    setContent(instr.content)
    setContentRu(instr.content_ru)
    setSortOrder(instr.sort_order)
    setImageFile(null)
    setImagePreview(instr.image_filename ? `/api/static/uploads/${instr.image_filename}` : null)
    setShowForm(true)
  }

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      setImageFile(file)
      setImagePreview(URL.createObjectURL(file))
    }
  }

  const handleSave = async () => {
    if (!title.trim()) {
      showToast('Titlul este obligatoriu!')
      return
    }
    setSaving(true)
    try {
      const formData = new FormData()
      formData.append('title', title)
      formData.append('title_ru', titleRu)
      formData.append('content', content)
      formData.append('content_ru', contentRu)
      formData.append('sort_order', String(sortOrder))
      if (imageFile) {
        formData.append('image', imageFile)
      }

      if (editingId) {
        await api.put(`/instructions/${editingId}`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        showToast('Instrucțiunea a fost salvată!')
      } else {
        await api.post('/instructions', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        showToast('Instrucțiunea a fost creată!')
      }
      resetForm()
      fetchInstructions()
    } catch (e) {
      console.error(e)
      showToast('Eroare la salvare!')
    }
    setSaving(false)
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Sigur vrei să ștergi această instrucțiune?')) return
    try {
      await api.delete(`/instructions/${id}`)
      fetchInstructions()
      showToast('Instrucțiunea a fost ștearsă!')
    } catch (e) {
      console.error(e)
      showToast('Eroare la ștergere!')
    }
  }

  const toggleActive = async (instr: Instruction) => {
    try {
      await api.put(`/instructions/${instr.id}`, {
        is_active: !instr.is_active,
      })
      fetchInstructions()
      showToast(instr.is_active ? 'Instrucțiunea a fost dezactivată' : 'Instrucțiunea a fost activată')
    } catch (e) {
      console.error(e)
    }
  }

  const removeImage = async (id: number) => {
    try {
      await api.post(`/instructions/${id}/remove-image`)
      fetchInstructions()
      if (editingId === id) {
        setImagePreview(null)
      }
      showToast('Imaginea a fost ștearsă!')
    } catch (e) {
      console.error(e)
    }
  }

  return (
    <>
      <NavBar />
      <div className="container">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ margin: 0 }}>📋 Instrucțiuni & Checklist</h2>
          <button className="btn btn-success" onClick={openNew} style={{ fontWeight: 700 }}>
            + Adaugă instrucțiune
          </button>
        </div>

        {/* Create/Edit form */}
        {showForm && (
          <div className="dashboard-section" style={{ border: '2px solid #f5920a', background: '#fffaf0' }}>
            <h3 style={{ marginBottom: 16 }}>
              {editingId ? '✏️ Editează instrucțiunea' : '✨ Instrucțiune nouă'}
            </h3>

            <div className="menu-lang-grid">
              <div>
                <label>🇷🇴 Titlu (română):</label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Ex: Cum comand meniul..."
                />
              </div>
              <div>
                <label>🇷🇺 Заголовок (русский):</label>
                <input
                  value={titleRu}
                  onChange={(e) => setTitleRu(e.target.value)}
                  placeholder="Напр: Как заказать меню..."
                />
              </div>
            </div>

            <div className="menu-lang-grid" style={{ marginTop: 12 }}>
              <div>
                <label>🇷🇴 Descriere (română):</label>
                <textarea
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="Descrieți pașii, explicațiile..."
                  rows={5}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: 10,
                    border: '1px solid #ddd',
                    fontSize: 14,
                    fontFamily: 'inherit',
                    resize: 'vertical',
                  }}
                />
              </div>
              <div>
                <label>🇷🇺 Описание (русский):</label>
                <textarea
                  value={contentRu}
                  onChange={(e) => setContentRu(e.target.value)}
                  placeholder="Опишите шаги, пояснения..."
                  rows={5}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: 10,
                    border: '1px solid #ddd',
                    fontSize: 14,
                    fontFamily: 'inherit',
                    resize: 'vertical',
                  }}
                />
              </div>
            </div>

            <div style={{ marginTop: 12, display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <div>
                <label>🖼 Imagine:</label>
                <input
                  type="file"
                  accept="image/*"
                  onChange={handleImageChange}
                  style={{ display: 'block', marginTop: 4 }}
                />
              </div>
              <div>
                <label>Ordine:</label>
                <input
                  type="number"
                  value={sortOrder}
                  onChange={(e) => setSortOrder(Number(e.target.value))}
                  style={{ width: 80 }}
                />
              </div>
            </div>

            {imagePreview && (
              <div style={{ marginTop: 12 }}>
                <img
                  src={imagePreview}
                  alt="Preview"
                  style={{ maxWidth: 300, maxHeight: 200, borderRadius: 10, border: '1px solid #ddd' }}
                />
                {editingId && (
                  <button
                    className="btn btn-danger"
                    onClick={() => removeImage(editingId)}
                    style={{ marginLeft: 12, padding: '4px 12px', fontSize: 12 }}
                  >
                    Șterge imaginea
                  </button>
                )}
              </div>
            )}

            <div className="btn-group" style={{ marginTop: 16 }}>
              <button className="btn btn-success" onClick={handleSave} disabled={saving}>
                {saving ? '⏳ Se salvează...' : '💾 Salvează'}
              </button>
              <button className="btn btn-danger" onClick={resetForm}>Anulează</button>
            </div>
          </div>
        )}

        {/* Instructions list */}
        {instructions.length === 0 && !showForm && (
          <div className="dashboard-section" style={{ textAlign: 'center', color: '#999' }}>
            <p>Nu sunt instrucțiuni. Apasă "Adaugă instrucțiune" pentru a crea prima.</p>
          </div>
        )}

        {instructions.map((instr) => (
          <div
            key={instr.id}
            className="dashboard-section"
            style={{
              opacity: instr.is_active ? 1 : 0.5,
              borderLeft: `4px solid ${instr.is_active ? '#22c55e' : '#999'}`,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 12, color: '#999', fontWeight: 600 }}>#{instr.sort_order}</span>
                  <h4 style={{ margin: 0 }}>{instr.title}</h4>
                  {instr.title_ru && (
                    <span style={{ color: '#888', fontSize: 14 }}>/ {instr.title_ru}</span>
                  )}
                  {!instr.is_active && (
                    <span style={{ fontSize: 11, background: '#eee', padding: '2px 8px', borderRadius: 6, color: '#666' }}>
                      Dezactivată
                    </span>
                  )}
                </div>
                {instr.content && (
                  <p style={{ fontSize: 14, color: '#555', margin: '8px 0', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                    {instr.content}
                  </p>
                )}
                {instr.image_filename && (
                  <img
                    src={`/api/static/uploads/${instr.image_filename}`}
                    alt={instr.title}
                    style={{ maxWidth: 400, maxHeight: 250, borderRadius: 10, marginTop: 8, border: '1px solid #eee' }}
                  />
                )}
              </div>
              <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                <button className="btn btn-primary" onClick={() => openEdit(instr)} style={{ padding: '6px 12px', fontSize: 13 }}>
                  ✏️
                </button>
                <button
                  className="btn btn-warning"
                  onClick={() => toggleActive(instr)}
                  style={{ padding: '6px 12px', fontSize: 13 }}
                >
                  {instr.is_active ? '👁' : '👁‍🗨'}
                </button>
                <button
                  className="btn btn-danger"
                  onClick={() => handleDelete(instr.id)}
                  style={{ padding: '6px 12px', fontSize: 13 }}
                >
                  🗑
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
