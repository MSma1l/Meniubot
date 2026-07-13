import { useState, useEffect, useCallback, useMemo } from 'react'
import axios from 'axios'
import NavBar from '../components/NavBar'
import api from '../api/client'

const MAX_LEN = 4096

interface User {
  id: number
  telegram_id: number
  first_name: string
  last_name: string
  username: string | null
  language: string
  is_active: boolean
}

interface BroadcastResult {
  sent: number
  failed: number
  total: number
  not_found: number
  bot_enabled: boolean
}

interface BroadcastPayload {
  text: string
  text_ru?: string
  target: 'all' | 'selected'
  user_ids?: number[]
}

export default function Broadcast() {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const [text, setText] = useState('')
  const [textRu, setTextRu] = useState('')
  const [selected, setSelected] = useState<number[]>([])
  const [search, setSearch] = useState('')

  const [sending, setSending] = useState(false)
  const [toast, setToast] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<BroadcastResult | null>(null)

  const fetchUsers = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const { data } = await api.get<User[]>('/users')
      setUsers(data)
    } catch (e) {
      console.error(e)
      setLoadError('Nu am putut încărca lista de utilizatori. Verifică conexiunea și încearcă din nou.')
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchUsers()
  }, [fetchUsers])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(''), 5000)
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return users
    return users.filter((u) =>
      `${u.first_name} ${u.last_name}`.toLowerCase().includes(q) ||
      (u.username || '').toLowerCase().includes(q)
    )
  }, [users, search])

  const allSelected = users.length > 0 && selected.length === users.length

  const toggleUser = (id: number) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    )
  }

  const toggleAll = () => {
    setSelected(allSelected ? [] : users.map((u) => u.id))
  }

  const tooLongRo = text.length > MAX_LEN
  const tooLongRu = textRu.length > MAX_LEN
  const emptyRo = text.trim().length === 0
  const canSend =
    !sending && !emptyRo && !tooLongRo && !tooLongRu && selected.length > 0

  const send = async () => {
    if (!canSend) return
    const n = selected.length
    const who = allSelected
      ? `toți cei ${n} utilizatori`
      : `${n} ${n === 1 ? 'persoană selectată' : 'persoane selectate'}`
    if (!confirm(`Trimiți mesajul către ${who}?`)) return

    setSending(true)
    setError('')
    setResult(null)

    const payload: BroadcastPayload = allSelected
      ? { text: text.trim(), target: 'all' }
      : { text: text.trim(), target: 'selected', user_ids: selected }
    if (textRu.trim()) payload.text_ru = textRu.trim()

    try {
      const { data } = await api.post<BroadcastResult>('/broadcast', payload)
      setResult(data)
      if (data.bot_enabled === false) {
        showToast('⚠️ Botul e oprit — niciun mesaj nu a plecat.')
      } else if (data.failed > 0) {
        showToast(`✅ Trimise: ${data.sent} — ❌ Eșuate: ${data.failed} (din ${data.total})`)
      } else {
        showToast(`✅ Mesaj trimis către ${data.sent} ${data.sent === 1 ? 'persoană' : 'persoane'}!`)
      }
    } catch (e) {
      console.error(e)
      let msg = 'Eroare la trimitere. Încearcă din nou.'
      if (axios.isAxiosError(e)) {
        const serverMsg = (e.response?.data as { error?: string } | undefined)?.error
        if (serverMsg) msg = serverMsg
        else if (e.response) msg = `Eroare de la server (${e.response.status}).`
        else msg = 'Serverul nu răspunde. Verifică conexiunea.'
      }
      setError(msg)
      showToast('❌ Mesajul nu a fost trimis.')
    }
    setSending(false)
  }

  return (
    <>
      <NavBar />
      <div className="container">
        <h2 style={{ marginBottom: 20 }}>📢 Mesaje</h2>

        {/* 1. Caseta de mesaj */}
        <div className="dashboard-section">
          <h3>✍️ Mesajul</h3>

          <label className="bc-label">🇷🇴 Textul în română (obligatoriu)</label>
          <textarea
            className="bc-textarea"
            rows={6}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Scrie aici mesajul care va pleca de la bot..."
          />
          <div className={`bc-counter ${tooLongRo ? 'over' : ''}`}>
            {text.length} / {MAX_LEN}
            {tooLongRo && ' — depășește limita Telegram!'}
          </div>

          <label className="bc-label" style={{ marginTop: 16 }}>
            🇷🇺 Varianta rusă (opțional) — dacă o lași goală, rusofonii primesc textul român
          </label>
          <textarea
            className="bc-textarea"
            rows={5}
            value={textRu}
            onChange={(e) => setTextRu(e.target.value)}
            placeholder="Текст на русском (необязательно)..."
          />
          <div className={`bc-counter ${tooLongRu ? 'over' : ''}`}>
            {textRu.length} / {MAX_LEN}
            {tooLongRu && ' — depășește limita Telegram!'}
          </div>
        </div>

        {/* 4. Previzualizare */}
        {(text.trim() || textRu.trim()) && (
          <div className="dashboard-section">
            <h3>👀 Previzualizare</h3>
            <div className="bc-preview-grid">
              {text.trim() && (
                <div>
                  <div className="bc-label">🇷🇴 Ce văd vorbitorii de română</div>
                  <div className="bc-bubble">{text}</div>
                </div>
              )}
              <div>
                <div className="bc-label">🇷🇺 Ce văd rusofonii</div>
                <div className="bc-bubble">
                  {textRu.trim() ? textRu : text}
                  {!textRu.trim() && text.trim() && (
                    <div className="bc-bubble-note">(fără variantă rusă — primesc textul român)</div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 2. Destinatarii */}
        <div className="dashboard-section">
          <h3>👥 Destinatari</h3>

          {loadError && (
            <div className="bc-warning">
              {loadError}{' '}
              <button className="btn btn-primary" onClick={fetchUsers} style={{ padding: '4px 12px', fontSize: 13, marginLeft: 8 }}>
                Reîncearcă
              </button>
            </div>
          )}

          <div className="bc-toolbar">
            <button className="btn btn-primary" onClick={toggleAll} disabled={users.length === 0}>
              {allSelected ? '☐ Deselectează toți' : '☑️ Selectează toți'}
            </button>
            <input
              type="text"
              placeholder="Caută după nume..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="bc-search"
            />
            <span className="bc-count">
              Trimit către <strong>{selected.length}</strong>{' '}
              {selected.length === 1 ? 'persoană' : 'persoane'}
            </span>
          </div>

          {loading ? (
            <p style={{ color: '#999', padding: 12 }}>Se încarcă utilizatorii...</p>
          ) : users.length === 0 && !loadError ? (
            <p style={{ color: '#999', padding: 12 }}>Niciun utilizator înregistrat.</p>
          ) : filtered.length === 0 ? (
            <p style={{ color: '#999', padding: 12 }}>Niciun utilizator nu se potrivește căutării.</p>
          ) : (
            <div className="bc-recipients">
              {filtered.map((u) => {
                const isOn = selected.includes(u.id)
                return (
                  <label key={u.id} className={`bc-recipient ${isOn ? 'selected' : ''}`}>
                    <input
                      type="checkbox"
                      checked={isOn}
                      onChange={() => toggleUser(u.id)}
                    />
                    <div style={{ minWidth: 0 }}>
                      <div className="bc-recipient-name">
                        {u.first_name} {u.last_name}{' '}
                        <span title={u.language === 'ru' ? 'Rusă' : 'Română'}>
                          {u.language === 'ru' ? '🇷🇺' : '🇷🇴'}
                        </span>
                        {!u.is_active && <span className="status-badge pending" style={{ marginLeft: 6 }}>inactiv</span>}
                      </div>
                      <div className="bc-recipient-meta">
                        {u.username ? `@${u.username}` : u.telegram_id}
                      </div>
                    </div>
                  </label>
                )
              })}
            </div>
          )}
        </div>

        {/* 3. Trimiterea */}
        <div className="dashboard-section">
          {error && <div className="bc-warning">❌ {error}</div>}

          {result && result.bot_enabled === false && (
            <div className="bc-warning">
              🛑 <strong>Botul este oprit (Stop Cran).</strong> Niciun mesaj nu pleacă până nu-l
              pornești din Dashboard. Repornește botul și trimite din nou.
            </div>
          )}

          {result && result.bot_enabled !== false && (
            <div className={result.failed > 0 ? 'bc-warning' : 'bc-ok'}>
              Rezultat: <strong>{result.sent}</strong> trimise
              {result.failed > 0 && <> · <strong>{result.failed}</strong> eșuate</>}
              {result.not_found > 0 && <> · <strong>{result.not_found}</strong> negăsite</>}
              {' '}(din {result.total}).
            </div>
          )}

          <button
            className="btn btn-success btn-big"
            onClick={send}
            disabled={!canSend}
            style={{ opacity: canSend ? 1 : 0.5, cursor: canSend ? 'pointer' : 'not-allowed', justifyContent: 'center' }}
          >
            {sending
              ? 'Se trimite...'
              : `🚀 Trimite mesajul către ${selected.length} ${selected.length === 1 ? 'persoană' : 'persoane'}`}
          </button>

          {!canSend && !sending && (
            <p style={{ marginTop: 10, fontSize: 13, color: '#999', textAlign: 'center' }}>
              {emptyRo
                ? 'Scrie textul în română ca să poți trimite.'
                : tooLongRo || tooLongRu
                  ? `Mesajul depășește limita de ${MAX_LEN} caractere.`
                  : 'Bifează cel puțin un destinatar.'}
            </p>
          )}
        </div>
      </div>

      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
