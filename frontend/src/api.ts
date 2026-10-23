export type Material = { matnr: string; name: string; kind: string; unit: string; procurement: string; stock: number; safety: number; lead_days: number; lot_rule: string; lot_qty: number; cost: number }
export type Center = { arbpl: string; name: string; units_per_shift: number; shift_minutes: number; rate: number; load_minutes?: number; shifts_required?: number }
export type Operation = { op: string; center: string; description: string; setup: string | number; run: string | number; rate?: string; yield?: string; scrap?: string; minutes?: string; final?: boolean }
export type Component = { component: string; qty: string | number }
export type Revision = { id: number; matnr: string; revision: string; valid_from: string; status: string; components: Component[] }
export type Tree = { matnr: string; name: string; qty: number; unit: string; revision?: string; children: Tree[] }
export type Proposal = { id: number; run_id: number; matnr: string; qty: number; received: number; kind: string; start: string; due: string; status: string; bom_id: number | null }
export type Order = { id: number; matnr: string; qty: number; received: number; start: string; due: string; status: string; bom_id: number; planned_cost: number; actual_cost: number; components: { matnr: string; qty: string; rate: string }[]; operations: Operation[] }
export type Change = { id: number; matnr: string; reason: string; valid_from: string; status: string; history: { status: string; at: string }[] }
export type Event = { id: number; module: string; reference: string; message: string; created: string }
export type Demand = { id: number; matnr: string; qty: number; due: string; source: string }
export type StockRow = { matnr: string; date: string; type: string; gross: number; scheduled?: number; shortfall?: number; supply: number; projected: number; before_supply?: number }
export type Run = { id: number; active: boolean; created: string; rows: StockRow[]; exceptions: { matnr: string; message: string }[] }
export type Dashboard = { orders_by_status: Record<string, number>; open_proposals: number; shortages: StockRow[]; exceptions: { matnr: string; message: string }[]; capacity: Center[]; recent_changes: Change[]; demo_reset_enabled: boolean }
export type Movement = { id: number; matnr: string; qty: number; kind: string; reference: string; created: string }
export type Impact = { type: string; id: number; matnr: string; status: string; start: string; effectivity_relevant: boolean; action: string }

export async function api<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await fetch(`/api${path}`, body === undefined ? undefined : { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const result = await response.json()
  if (!response.ok) {
    const detail = result.detail
    throw new Error(Array.isArray(detail) ? detail.map((d: { loc: string[]; msg: string }) => `${d.loc.slice(1).join('.')}: ${d.msg}`).join('; ') : detail || `Request failed (${response.status})`)
  }
  return result as T
}

export function today(offset = 0) {
  const d = new Date()
  d.setDate(d.getDate() + offset)
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d)
}
export const key = () => crypto.randomUUID()
export const fmt = (value: number | string | undefined) => Number(value || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })

