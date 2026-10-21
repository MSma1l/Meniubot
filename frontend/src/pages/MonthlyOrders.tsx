import { useCallback, useEffect, useState } from 'react'
import NavBar from '../components/NavBar'
import api from '../api/client'

interface Order {
  id: number; date: string; restaurant: string; personal_item?: string | null
  personal_price?: number | null; user?: { first_name: string; last_name: string } | null
  felul1_menu?: { name: string } | null; felul2_menu?: { name: string } | null
}

const labels: Record<string, string> = { sezatoare: 'La Șezătoare', andys: "Andy's business lunch", personal_andys: "Andy's personală" }

export default function MonthlyOrders() {
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [orders, setOrders] = useState<Order[]>([])
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    try { setError(''); const { data } = await api.get(`/orders/monthly?month=${month}`); setOrders(data) }
    catch { setError('Nu s-au putut încărca comenzile.') }
  }, [month])
  useEffect(() => { load() }, [load])
  return <><NavBar /><div className="container"><h2>📅 Comenzi — tabel lunar</h2>
    <p style={{ color: '#666' }}>Datele sunt păstrate 30 de zile, apoi se șterg automat.</p>
    <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}><input aria-label="Luna" type="month" value={month} onChange={e => setMonth(e.target.value)} /><button className="btn btn-primary" onClick={load}>Actualizează</button></div>
    {error && <p className="error-msg">{error}</p>}
    <table><thead><tr><th>Data</th><th>Utilizator</th><th>Tip comandă</th><th>Detalii</th><th>Preț</th></tr></thead><tbody>
      {orders.length === 0 ? <tr><td colSpan={5} style={{ textAlign: 'center', color: '#999' }}>Nicio comandă în luna aleasă</td></tr> : orders.map(o => <tr key={o.id}><td>{o.date}</td><td>{o.user ? `${o.user.first_name} ${o.user.last_name}` : '—'}</td><td>{labels[o.restaurant] || o.restaurant}</td><td>{o.personal_item || o.felul1_menu?.name || o.felul2_menu?.name || '—'}</td><td>{o.personal_price != null ? `${Number(o.personal_price).toFixed(2)} lei` : '—'}</td></tr>)}
    </tbody></table></div></>
}
