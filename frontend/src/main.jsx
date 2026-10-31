import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, fmt, key, today } from './api';
import './style.css';
const pages = [['Overview', '01'], ['Master data', '02'], ['MRP planning', '03'], ['Production', '04'], ['Engineering changes', '05'], ['Integration ledger', '06']];
const pageInfo = {
    'Overview': ['Production workspace', 'Plan materials. Build bikes. Control changes.'],
    'Master data': ['Manufacturing master data', 'The materials, structures, operations, and resources behind EB-1000.'],
    'MRP planning': ['Material requirements planning', 'Translate dated demand into make proposals and external supply.'],
    'Production': ['Production order execution', 'Reservations, component issue, confirmations, and output receipts.'],
    'Engineering changes': ['Engineering change management', 'Release dated BOM revisions and review their impact on open orders.'],
    'Integration ledger': ['Cross-module event ledger', 'Trace simulated MM, SD, QM, and FI/CO effects to their source.'],
};
function Badge({ children }) { return <span className={`badge ${String(children).toLowerCase().replace(/\W/g, '')}`}>{children}</span>; }
function Empty({ children }) { return <p className="empty">{children}</p>; }
function Panel({ title, label, children, action }) {
    return <section className="panel"><div className="panel-heading"><div>{label && <small>{label}</small>}<h2>{title}</h2></div>{action}</div>{children}</section>;
}
function Table({ headers, children }) { return <div className="table-wrap"><table><thead><tr>{headers.map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>; }
function Field({ label, children }) { return <label className="field"><span>{label}</span>{children}</label>; }
function Modal({ title, close, children }) {
    const ref = useRef(null);
    useEffect(() => { const dialog = ref.current; dialog.showModal(); return () => dialog.close(); }, []);
    return <dialog ref={ref} onCancel={close}><div className="modal-heading"><h2>{title}</h2><button onClick={close} aria-label="Close dialog">×</button></div>{children}</dialog>;
}
function BomTree({ node, depth = 0 }) {
    return <><div className="bom-row" style={{ paddingLeft: `${18 + depth * 26}px` }}><span className="bom-branch">{depth ? '└' : '●'}</span><code>{node.matnr}</code><span>{node.name}</span>{node.revision && <Badge>Rev {node.revision}</Badge>}<strong>{fmt(node.qty)} {node.unit}</strong></div>{node.children.map(c => <BomTree key={c.matnr} node={c} depth={depth + 1}/>)}</>;
}
function App() {
    const [data, setData] = useState(null);
    const [page, setPage] = useState('Overview');
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState(null);
    const [modal, setModal] = useState(null);
    const [selectedOrder, setSelectedOrder] = useState(null);
    const [masterTab, setMasterTab] = useState('Materials');
    const [tree, setTree] = useState(null);
    const [bomMaterial, setBomMaterial] = useState('EB-1000');
    const [bomDate, setBomDate] = useState(today());
    const [stockMaterial, setStockMaterial] = useState('EB-1000');
    const [impact, setImpact] = useState(null);
    const [moduleFilter, setModuleFilter] = useState('All');
    const [materialQuery, setMaterialQuery] = useState('');
    async function refresh() {
        const [dashboard, materials, centers, proposals, orders, changes, events, demands, revisions, runs, movements] = await Promise.all([
            api('/dashboard'), api('/materials'), api('/work-centers'), api('/mrp/proposals'), api('/orders'), api('/ecn'), api('/events'), api('/requirements'), api('/bom-revisions'), api('/mrp/runs'), api('/movements'),
        ]);
        setData({ dashboard, materials, centers, proposals, orders, changes, events, demands, revisions, runs, movements });
    }
    useEffect(() => { refresh().catch(e => setMessage({ text: e.message, error: true })); }, []);
    useEffect(() => { if (data && masterTab === 'BOM structure')
        api(`/bom/${bomMaterial}?valid_on=${bomDate}`).then(setTree).catch(e => { setTree(null); setMessage({ text: e.message, error: true }); }); }, [bomMaterial, bomDate, masterTab, data]);
    async function perform(work, success, close = true) {
        setBusy(true);
        setMessage(null);
        try {
            await work();
            await refresh();
            setMessage({ text: success, error: false });
            if (close)
                setModal(null);
        }
        catch (e) {
            setMessage({ text: e.message, error: true });
            throw e;
        }
        finally {
            setBusy(false);
        }
    }
    const act = (work, text, close = true) => { void perform(work, text, close).catch(() => { }); };
    const close = () => setModal(null);
    const button = (label, callback, secondary = false) => <button className={secondary ? 'secondary' : 'primary'} disabled={busy} onClick={callback}>{label}</button>;
    function openMaterial(existing) {
        setModal(<MaterialForm existing={existing} close={close} onSave={v => perform(() => api(`/materials${existing ? `/${existing.matnr}` : ''}`, v, existing ? 'PUT' : 'POST'), 'Material saved')}/>);
    }
    function openStructure(change) {
        if (!data)
            return;
        setModal(<StructureForm change={change} materials={data.materials} revisions={data.revisions} close={close} onSave={v => perform(() => api(change ? '/ecn' : '/bom', v), change ? 'Engineering change requested; revision remains draft until release' : 'Initial BOM released')}/>);
    }
    function openCenter(existing) {
        setModal(<CenterForm existing={existing} close={close} onSave={v => perform(() => api(`/work-centers${existing ? `/${existing.arbpl}` : ''}`, v, existing ? 'PUT' : 'POST'), 'Work center saved')}/>);
    }
    function openRouting() {
        if (!data)
            return;
        setModal(<RoutingForm materials={data.materials.filter(m => m.procurement === 'E')} centers={data.centers} close={close} onSave={(matnr, operations) => perform(() => api(`/routing/${matnr}`, { matnr, operations }, 'PUT'), 'Routing saved; existing orders keep their operations')}/>);
    }
    function receiptDialog(proposal) {
        setModal(<QuantityForm title={`Receive PR-${proposal.id}: ${proposal.matnr}`} max={proposal.qty - proposal.received} close={close} onSave={qty => perform(() => api(`/purchase-requisitions/${proposal.id}/goods-receipt`, { qty, key: key() }), 'External components received into stock')}/>);
    }
    function orderReceipt(order) {
        const max = Number(order.operations.at(-1)?.yield || 0) - order.received;
        setModal(<QuantityForm title={`Receive output: ORD-${order.id}`} max={max} close={close} onSave={qty => perform(() => api(`/orders/${order.id}/goods-receipt`, { qty, key: key() }), 'Confirmed output received into stock')}/>);
    }
    if (!data)
        return <main className="startup"><h1>E-Bike Manufacturing</h1><p>{message?.text || 'Connecting to the production workspace…'}</p>{message && <button onClick={() => { setMessage(null); refresh().catch(e => setMessage({ text: e.message, error: true })); }}>Retry connection</button>}</main>;
    const { dashboard, materials, proposals, orders, changes, events, demands } = data;
    const run = data.runs.find(r => r.active);
    const order = orders.find(o => o.id === selectedOrder);
    const activeProposals = proposals.filter(p => ['Open', 'Committed'].includes(p.status));
    const openOrders = orders.filter(o => !['DLV', 'TECO'].includes(o.status));
    const stockRows = run?.rows.filter(r => r.matnr === stockMaterial) || [];
    const makeOption = (onlyMake = false) => materials.filter(m => !onlyMake || m.procurement === 'E').map(m => <option key={m.matnr} value={m.matnr}>{m.matnr} · {m.name}</option>);
    return <div className="app-shell"><aside className="sidebar"><div className="brand"><div className="brand-symbol">EB</div><div>E-Bike Manufacturing<small>PP + PLM SIMULATOR</small></div></div><div className="plant-label">WORKSPACE <span>Plant 1000</span></div><nav aria-label="Main navigation">{pages.map(([name, number]) => <button key={name} className={page === name ? 'nav-item active' : 'nav-item'} onClick={() => { setPage(name); setMessage(null); }}><span>{number}</span>{name}</button>)}</nav><div className="sidebar-footer"><strong>City E-Bike 250W</strong><p>Discrete manufacturing<br />One plant · One storage location</p><a href="/docs" target="_blank" rel="noreferrer">API documentation ↗</a><p className="simulator-note">Educational simulator.<br />No connection to SAP.</p></div></aside>
    <div className="workspace"><header className="topbar"><span>Manufacturing / <strong>{page}</strong></span><span className="local-status">Local demo · IST dates</span></header><main><div className="page-heading"><div><p className="overline">SAP PP / PLM · E-BIKE SCENARIO</p><h1>{pageInfo[page][0]}</h1><p>{pageInfo[page][1]}</p></div><div className="heading-actions">{button('Refresh', () => act(refresh, 'Workspace refreshed'), true)}{page === 'Overview' && button('Plan production', () => setPage('MRP planning'))}</div></div>
    {message && <div role={message.error ? 'alert' : 'status'} className={`notice ${message.error ? 'error' : 'success'}`}><span>{message.text}</span><button aria-label="Dismiss notification" onClick={() => setMessage(null)}>×</button></div>}
    {busy && <p className="working" role="status">Saving and updating workspace…</p>}

    {page === 'Overview' && <><div className="metrics"><div><small>Active supply proposals</small><strong>{dashboard.open_proposals}</strong><span>Make + external procurement</span></div><div><small>Orders in production</small><strong>{openOrders.length}</strong><span>{orders.filter(o => o.status === 'TECO').length} technically complete</span></div><div><small>Demand for EB-1000</small><strong>{fmt(demands.filter(d => d.matnr === 'EB-1000').reduce((n, d) => n + d.qty, 0))}</strong><span>{fmt(materials.find(m => m.matnr === 'EB-1000')?.stock)} bikes in physical stock</span></div><div><small>Engineering changes</small><strong>{changes.length}</strong><span>{changes.filter(c => c.status === 'Released').length} released changes</span></div></div>
      <div className="workflow-strip"><div><b>01</b><span>Maintain<br /><strong>Master data</strong></span></div><div><b>02</b><span>Calculate<br /><strong>Material needs</strong></span></div><div><b>03</b><span>Execute<br /><strong>Production orders</strong></span></div><div><b>04</b><span>Control<br /><strong>Engineering changes</strong></span></div></div>
      <div className="two-columns"><Panel title="Work center load" label="OPEN PRODUCTION ORDERS"><p className="panel-note">Remaining operation minutes against one 480-minute shift. Informational load; orders are not finitely scheduled.</p>{dashboard.capacity.map(c => <div className="capacity-row" key={c.arbpl}><div><strong>{c.arbpl}</strong><span>{fmt(c.load_minutes)} min / {c.shift_minutes} min</span></div><progress value={Math.min(c.load_minutes || 0, c.shift_minutes)} max={c.shift_minutes} aria-label={`${c.arbpl} shift load`}/><small>{c.shifts_required} shifts required</small></div>)}</Panel><Panel title="Supply and scheduling exceptions" label={run ? `MRP RUN ${run.id}` : 'NO MRP RUN YET'}>{!run ? <Empty>Add demand and run MRP to see the material plan.</Empty> : <><p className="panel-note">{dashboard.shortages.length} requirement buckets need replenishment. Proposed supply is included in projected balances.</p>{dashboard.exceptions.length ? dashboard.exceptions.slice(0, 8).map((e, i) => <div className="exception" key={i}><code>{e.matnr}</code><span>{e.message}</span></div>) : <Empty>No start dates fall before the planning date.</Empty>}{button('Inspect material plan', () => setPage('MRP planning'), true)}</>}</Panel></div>
      <Panel title="Recent activity" action={button('View ledger', () => setPage('Integration ledger'), true)}><EventList events={events.slice(0, 5)}/></Panel>
      <Panel title="Repeatable demo" label="LOCAL DEVELOPMENT"><p className="panel-note">Reset removes all demand, planning runs, orders, movements, and changes. It restores the original e-bike masters and opening stock.</p>{dashboard.demo_reset_enabled ? <div className="button-row">{button('Reset to demo stock', () => { if (window.confirm('Delete all simulator transactions and restore demo opening stock?'))
            act(async () => { await api('/demo/reset', { fixture: 'demo', confirmation: 'RESET DEMO DATA' }); setSelectedOrder(null); setImpact(null); }, 'Demo data restored'); }, true)}{button('Reset to zero stock', () => { if (window.confirm('Delete all simulator transactions and restore zero-stock calculation fixture?'))
            act(async () => { await api('/demo/reset', { fixture: 'zero', confirmation: 'RESET DEMO DATA' }); setSelectedOrder(null); setImpact(null); }, 'Zero-stock fixture restored'); }, true)}</div> : <p>Reset disabled for this deployment.</p>}</Panel>
    </>}

    {page === 'Master data' && <><div className="tabs" role="tablist" aria-label="Master data categories">{['Materials', 'BOM structure', 'Routings', 'Work centers'].map(t => <button role="tab" aria-selected={masterTab === t} className={masterTab === t ? 'selected' : ''} key={t} onClick={() => setMasterTab(t)}>{t}</button>)}</div>
      {masterTab === 'Materials' && <Panel title="Material master" label="MM01 / MM02" action={button('Create material', () => openMaterial())}><input className="search" aria-label="Search materials" placeholder="Search code or description" value={materialQuery} onChange={e => setMaterialQuery(e.target.value)}/><Table headers={['Material', 'Description', 'Type', 'Procurement', 'Physical stock', 'Lead time', 'Lot rule', '']}>
        {materials.filter(m => `${m.matnr} ${m.name}`.toLowerCase().includes(materialQuery.toLowerCase())).map(m => <tr key={m.matnr}><td><code>{m.matnr}</code></td><td>{m.name}</td><td>{m.kind}</td><td>{m.procurement === 'E' ? 'Make' : 'Buy'}</td><td className="numeric">{fmt(m.stock)} {m.unit}</td><td>{m.lead_days} days</td><td>{m.lot_rule}</td><td><button className="text-button" onClick={() => openMaterial(m)}>Edit</button></td></tr>)}
      </Table></Panel>}
      {masterTab === 'BOM structure' && <><Panel title="Multi-level bill of materials" label="CS01 / CS02" action={button('Create initial BOM', () => openStructure(false))}><div className="form-grid compact"><Field label="Assembly"><select value={bomMaterial} onChange={e => setBomMaterial(e.target.value)}>{makeOption(true)}</select></Field><Field label="Valid on"><input type="date" value={bomDate} onChange={e => { if (e.target.value)
                setBomDate(e.target.value); }}/></Field></div><p className="panel-note">Quantities are cumulative per one selected assembly. Existing revisions are changed through engineering change management.</p>{tree ? <div className="bom-tree"><BomTree node={tree}/></div> : <Empty>No released BOM available for this selection.</Empty>}</Panel><Panel title="Revision register"><Table headers={['Assembly', 'Revision', 'Valid from (inclusive)', 'Status']}>
        {data.revisions.map(r => <tr key={r.id}><td><code>{r.matnr}</code></td><td>{r.revision}</td><td>{r.valid_from}</td><td><Badge>{r.status}</Badge></td></tr>)}
      </Table></Panel></>}
      {masterTab === 'Routings' && <Panel title="Operation routing" label="CA01 / CA02" action={button('Maintain routing', openRouting)}><RoutingViewer materials={materials.filter(m => m.procurement === 'E')}/></Panel>}
      {masterTab === 'Work centers' && <Panel title="Work centers" label="CR01 / CR02" action={button('Create work center', () => openCenter())}><Table headers={['Work center', 'Description', 'Reference units/shift', 'Shift minutes', 'Cost / min (demo units)', '']}>
        {data.centers.map(c => <tr key={c.arbpl}><td><code>{c.arbpl}</code></td><td>{c.name}</td><td>{c.units_per_shift}</td><td>{c.shift_minutes}</td><td>{fmt(c.rate)}</td><td><button className="text-button" onClick={() => openCenter(c)}>Edit</button></td></tr>)}
      </Table></Panel>}
    </>}

    {page === 'MRP planning' && <><div className="two-columns"><Panel title="Independent requirement" label="DEMAND INPUT / SD MAPPING"><DemandForm materials={materials} onSave={v => perform(() => api('/requirements', v), 'Demand added; run MRP to update proposals', false)}/><p className="panel-note">Each submission adds demand. Use demo reset to start a fresh scenario.</p></Panel><Panel title="Run material planning" label="MD01"><form onSubmit={e => { e.preventDefault(); const v = new FormData(e.currentTarget); act(() => api('/mrp/run', { planning_date: v.get('planning_date') }), 'MRP complete; stock unchanged'); }}><Field label="Planning date"><input name="planning_date" type="date" defaultValue={today()} required/></Field><p className="panel-note">Net stock and committed supply, apply lot sizes, offset lead times, and explode effective BOMs. Previous open proposals are superseded.</p><button className="primary" disabled={busy || !demands.length}>Run MRP</button></form>{run && <p className="run-stamp">Latest: run {run.id} · {new Date(run.created).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} IST</p>}</Panel></div>
      <Panel title="Demand register"><Table headers={['Reference', 'Material', 'Quantity', 'Due date', 'Source']}>{demands.map(d => <tr key={d.id}><td>DEMAND-{d.id}</td><td><code>{d.matnr}</code></td><td>{fmt(d.qty)}</td><td>{d.due}</td><td>{d.source}</td></tr>)}</Table>{!demands.length && <Empty>No demand yet. Start with 200 EB-1000 bikes.</Empty>}</Panel>
      <Panel title="Supply proposals" label="PLANNED ORDERS + PURCHASE REQUISITIONS"><p className="panel-note">Receive external parts first. Build lower-level assemblies before their parents. Conversion creates an executable order with frozen master data.</p><Table headers={['Reference', 'Material', 'Type', 'Quantity / received', 'Start / release', 'Due / receipt', 'Status', 'Action']}>
        {activeProposals.map(p => <tr key={p.id}><td>{p.kind === 'MAKE' ? 'PLN' : 'PR'}-{p.id}</td><td><code>{p.matnr}</code></td><td>{p.kind}</td><td>{fmt(p.qty)} / {fmt(p.received)}</td><td>{p.start}</td><td>{p.due}</td><td><Badge>{p.status}</Badge></td><td>{p.kind === 'MAKE' ? button('Convert', () => act(async () => { const o = await api('/orders/convert', { proposal_id: p.id }); setSelectedOrder(o.id); setPage('Production'); }, 'Production order created'), true) : button('Receive', () => receiptDialog(p), true)}</td></tr>)}
      </Table>{!activeProposals.length && <Empty>No open proposals. Run MRP or inspect existing production orders.</Empty>}</Panel>
      <Panel title="Stock / requirements list" label="MD04"><Field label="Material"><select value={stockMaterial} onChange={e => setStockMaterial(e.target.value)}>{makeOption()}</select></Field><p className="panel-note">Snapshot of the last MRP run. Physical stock now: {fmt(materials.find(m => m.matnr === stockMaterial)?.stock)}. Re-run after execution to refresh the projection.</p><StockTable rows={stockRows}/></Panel>
    </>}

    {page === 'Production' && <><Panel title="Production orders" label="CO01 / CO02"><Table headers={['Order', 'Material', 'Quantity', 'Received', 'Status', 'Start', 'Due', '']}>
      {[...orders].reverse().map(o => <tr key={o.id} className={o.id === selectedOrder ? 'selected-row' : ''}><td>ORD-{o.id}</td><td><code>{o.matnr}</code></td><td>{fmt(o.qty)}</td><td>{fmt(o.received)}</td><td><Badge>{o.status}</Badge></td><td>{o.start}</td><td>{o.due}</td><td><button className="text-button" onClick={() => setSelectedOrder(o.id)}>Open order</button></td></tr>)}
    </Table>{!orders.length && <Empty>Convert a make proposal in MRP planning to create an order.</Empty>}</Panel>
      {order && <Panel title={`ORD-${order.id} · ${order.matnr}`} label={`FROZEN BOM ${data.revisions.find(r => r.id === order.bom_id)?.revision || order.bom_id}`}><div className="order-summary"><Badge>{order.status}</Badge><span>Target <strong>{fmt(order.qty)}</strong></span><span>Planned cost <strong>{fmt(order.planned_cost)}</strong></span><span>Actual cost <strong>{fmt(order.actual_cost)}</strong></span><span>Variance <strong>{fmt(order.actual_cost - order.planned_cost)}</strong></span></div><p className="panel-note">Costs use illustrative material prices and activity rates in demo cost units.</p><div className="button-row">
        {order.status === 'CRTD' && button('Release order', () => act(() => api(`/orders/${order.id}/release`, { key: key() }), 'Order released; component reservations created'))}
        {['REL', 'PCNF'].includes(order.status) && button('Issue all components', () => act(() => api(`/orders/${order.id}/goods-issue`, { key: key() }), 'Reserved components issued'), true)}
        {['REL', 'PCNF'].includes(order.status) && button('Confirm operation', () => setModal(<ConfirmationForm order={order} close={close} onSave={v => perform(() => api(`/orders/${order.id}/confirm`, { ...v, key: key() }), 'Operation confirmation posted')}/>))}
        {['PCNF', 'CNF'].includes(order.status) && Number(order.operations.at(-1)?.yield || 0) > order.received && button('Receive output', () => orderReceipt(order))}
        {order.status === 'DLV' && button('Technically complete', () => act(() => api(`/orders/${order.id}/complete`, { key: key() }), 'Order technically complete'))}
      </div><h3>Copied components</h3><Table headers={['Component', 'Required', 'Physical stock now', 'Frozen unit cost']}>
        {order.components.map(c => <tr key={c.matnr}><td><code>{c.matnr}</code></td><td>{fmt(c.qty)}</td><td>{fmt(materials.find(m => m.matnr === c.matnr)?.stock)}</td><td>{fmt(c.rate)}</td></tr>)}
      </Table><h3>Operations · CO11N</h3><Table headers={['Operation', 'Work center', 'Description', 'Yield', 'Scrap', 'Actual minutes', 'Status']}>
        {order.operations.map(o => <tr key={o.op}><td>{o.op}</td><td><code>{o.center}</code></td><td>{o.description}</td><td>{fmt(o.yield)}</td><td>{fmt(o.scrap)}</td><td>{fmt(o.minutes)}</td><td><Badge>{o.final ? 'Final' : Number(o.yield || 0) ? 'Partial' : 'Open'}</Badge></td></tr>)}
      </Table><h3>Order activity</h3><EventList events={events.filter(e => e.reference === `ORD-${order.id}`)}/></Panel>}
    </>}

    {page === 'Engineering changes' && <><Panel title="Engineering change register" label="CC01 / CS02" action={button('Request engineering change', () => openStructure(true))}><p className="panel-note">Requested → Approved → Released → Implemented. Released revisions become eligible on their valid-from date. Production orders keep their copied BOM.</p><Table headers={['Change', 'Assembly', 'Reason', 'Valid from', 'Status', 'Actions']}>
      {[...changes].reverse().map(c => <tr key={c.id}><td>ECN-{c.id}</td><td><code>{c.matnr}</code></td><td className="description-cell">{c.reason}</td><td>{c.valid_from}</td><td><Badge>{c.status}</Badge></td><td><div className="button-row">{button('Impact', () => act(async () => { const rows = await api(`/ecn/${c.id}/impact`); setImpact({ id: c.id, rows }); }, 'Impact analysis refreshed'), true)}{c.status !== 'Implemented' && button(c.status === 'Requested' ? 'Approve' : c.status === 'Approved' ? 'Release' : 'Record implementation', () => act(() => api(`/ecn/${c.id}/status`, { target: c.status === 'Requested' ? 'Approved' : c.status === 'Approved' ? 'Released' : 'Implemented' }), 'Engineering change status updated'), true)}</div></td></tr>)}
    </Table>{!changes.length && <Empty>No engineering changes. Try replacing CT-403 with CT-404 in the PU-400 BOM.</Empty>}</Panel>
      {impact && <Panel title={`Open-order impact · ECN-${impact.id}`}><Table headers={['Document', 'Material', 'Start', 'Status', 'On/after effectivity', 'Review action']}>
        {impact.rows.map(r => <tr key={`${r.type}-${r.id}`}><td>{r.type} {r.id}</td><td><code>{r.matnr}</code></td><td>{r.start}</td><td><Badge>{r.status}</Badge></td><td>{r.effectivity_relevant ? 'Yes' : 'No'}</td><td>{r.action}</td></tr>)}
      </Table>{!impact.rows.length && <Empty>No open make proposals or production orders use the affected assembly.</Empty>}</Panel>}
      <Panel title="Revision effectivity"><Table headers={['Assembly', 'Revision', 'Valid from', 'Status']}>
        {data.revisions.map(r => <tr key={r.id}><td><code>{r.matnr}</code></td><td>{r.revision}</td><td>{r.valid_from}</td><td><Badge>{r.status}</Badge></td></tr>)}
      </Table><p className="panel-note">Use Master data → BOM structure to compare dates before and after a released change.</p></Panel>
    </>}

    {page === 'Integration ledger' && <><Panel title="Event timeline" label="SIMULATED MODULE EFFECTS" action={<select aria-label="Filter integration module" value={moduleFilter} onChange={e => setModuleFilter(e.target.value)}>{['All', 'PP', 'MM', 'SD', 'CO', 'FI', 'QM', 'PLM'].map(m => <option key={m}>{m}</option>)}</select>}><p className="panel-note">These are persisted explanations of simulator actions, not postings to SAP. Latest 250 events shown.</p><EventList events={events.filter(e => moduleFilter === 'All' || e.module.split(/\s*\/\s*/).includes(moduleFilter))}/></Panel><Panel title="Physical inventory movements" label="OPENING + RECEIPTS − ISSUES = STOCK"><Table headers={['Movement', 'Material', 'Type', 'Signed quantity', 'Reference', 'Recorded (IST)']}>
      {[...data.movements].reverse().map(m => <tr key={m.id}><td>{m.id}</td><td><code>{m.matnr}</code></td><td>{m.kind}</td><td className={m.qty < 0 ? 'negative numeric' : 'numeric'}>{m.qty > 0 ? '+' : ''}{fmt(m.qty)}</td><td>{m.reference}</td><td>{new Date(m.created).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}</td></tr>)}
    </Table>{!data.movements.length && <Empty>No physical inventory movements yet.</Empty>}</Panel></>}
    <footer className="page-footer">E-Bike PP + PLM Simulator <span>One plant · Calendar-day planning · Educational costing</span></footer></main></div>{modal}
  </div>;
}
function EventList({ events }) {
    if (!events.length)
        return <Empty>No events for this view. Actions in the simulator will appear here.</Empty>;
    return <div className="event-list">{events.map(e => <div className="event" key={e.id}><Badge>{e.module}</Badge><div><strong>{e.reference}</strong><p>{e.message}</p></div><time>{new Date(e.created).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' })} IST</time></div>)}</div>;
}
function StockTable({ rows }) {
    return <><Table headers={['Date', 'Element', 'Gross demand', 'Scheduled receipt', 'Net shortfall', 'Planned / opening supply', 'Projected stock']}>{rows.map((r, i) => <tr key={i}><td>{r.date}</td><td>{r.type}</td><td>{fmt(r.gross)}</td><td>{fmt(r.scheduled)}</td><td>{fmt(r.shortfall)}</td><td>{fmt(r.supply)}</td><td>{fmt(r.projected)}</td></tr>)}</Table>{!rows.length && <Empty>No stock/requirements rows for this material in the active run.</Empty>}</>;
}
function AsyncForm({ onSubmit, children }) {
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    async function submit(e) {
        e.preventDefault();
        const form = new FormData(e.currentTarget);
        setSaving(true);
        setError('');
        try {
            await onSubmit(form);
        }
        catch (e) {
            setError(e.message);
        }
        finally {
            setSaving(false);
        }
    }
    return <form onSubmit={submit}><fieldset disabled={saving}>{children}</fieldset>{error && <p role="alert" className="form-error">{error}</p>}{saving && <p role="status">Saving…</p>}</form>;
}
function FormButtons({ close, submit = 'Save' }) { return <div className="form-actions"><button type="button" className="secondary" onClick={close}>Cancel</button><button className="primary" type="submit">{submit}</button></div>; }
function MaterialForm({ existing, onSave, close }) {
    const defaults = existing || { matnr: '', name: '', kind: 'ROH', unit: 'EA', procurement: 'F', safety: 0, lead_days: 3, lot_rule: 'LFL', lot_qty: 1, cost: 10 };
    return <Modal title={existing ? `Edit ${existing.matnr}` : 'Create material'} close={close}><AsyncForm onSubmit={form => { const v = Object.fromEntries(form); return onSave({ ...v, lead_days: Number(v.lead_days) }); }}><div className="form-grid"><Field label="Material code"><input name="matnr" defaultValue={defaults.matnr} readOnly={!!existing} required maxLength={40} pattern="[A-Za-z0-9_-]+"/></Field><Field label="Description"><input name="name" defaultValue={defaults.name} required maxLength={120}/></Field><Field label="Material type"><select name="kind" defaultValue={defaults.kind}>{['FERT', 'HALB', 'ROH'].map(v => <option key={v}>{v}</option>)}</select></Field><Field label="Base unit (fixed after creation)"><select name="unit" defaultValue={defaults.unit} onChange={e => { if (existing)
        e.target.value = existing.unit; }}><option>EA</option><option>L</option></select></Field><Field label="Procurement (fixed after creation)"><select name="procurement" defaultValue={defaults.procurement} onChange={e => { if (existing)
        e.target.value = existing.procurement; }}><option value="E">E · In-house</option><option value="F">F · External</option></select></Field><Field label="Lead time · calendar days"><input name="lead_days" type="number" min="0" max="365" defaultValue={defaults.lead_days} required/></Field><Field label="Safety stock"><input name="safety" type="number" min="0" step="0.0001" defaultValue={defaults.safety} required/></Field><Field label="Lot rule"><select name="lot_rule" defaultValue={defaults.lot_rule}><option value="LFL">Lot-for-lot</option><option value="FIXED">Fixed batches</option><option value="MIN">Minimum lot</option></select></Field><Field label="Lot quantity"><input name="lot_qty" type="number" min="0.0001" step="0.0001" defaultValue={defaults.lot_qty} required/></Field><Field label="Unit cost · demo units"><input name="cost" type="number" min="0" step="0.0001" defaultValue={defaults.cost} required/></Field></div><p className="panel-note">New materials start at zero stock. Physical inventory changes only through receipts and issues.</p><FormButtons close={close}/></AsyncForm></Modal>;
}
function CenterForm({ existing, onSave, close }) {
    return <Modal title={existing ? `Edit ${existing.arbpl}` : 'Create work center'} close={close}><AsyncForm onSubmit={f => onSave({ arbpl: f.get('arbpl'), name: f.get('name'), units_per_shift: Number(f.get('units_per_shift')), shift_minutes: Number(f.get('shift_minutes')), rate: Number(f.get('rate')) })}><div className="form-grid"><Field label="Work center code"><input name="arbpl" required defaultValue={existing?.arbpl} readOnly={!!existing}/></Field><Field label="Description"><input name="name" required defaultValue={existing?.name}/></Field><Field label="Reference units / shift"><input name="units_per_shift" type="number" min="1" required defaultValue={existing?.units_per_shift || 25}/></Field><Field label="Shift minutes"><input name="shift_minutes" type="number" min="1" max="1440" required defaultValue={existing?.shift_minutes || 480}/></Field><Field label="Activity cost / minute"><input name="rate" type="number" min="0" step="0.0001" required defaultValue={existing?.rate ?? 2}/></Field></div><FormButtons close={close}/></AsyncForm></Modal>;
}
function StructureForm({ change, materials, revisions, close, onSave }) {
    const [matnr, setMatnr] = useState(change ? 'PU-400' : materials.find(m => m.procurement === 'E' && !revisions.some(r => r.matnr === m.matnr))?.matnr || '');
    const latest = (code) => [...revisions].filter(r => r.matnr === code && r.status === 'Released').sort((a, b) => b.valid_from.localeCompare(a.valid_from))[0];
    const [components, setComponents] = useState(change ? latest('PU-400')?.components.map(c => ({ component: c.component, qty: c.qty })) || [] : [{ component: materials[0].matnr, qty: 1 }]);
    const update = (i, field, value) => setComponents(old => old.map((c, j) => i === j ? { ...c, [field]: value } : c));
    return <Modal title={change ? 'Request engineering change' : 'Create initial BOM'} close={close}><AsyncForm onSubmit={f => onSave({ matnr, revision: f.get('revision'), valid_from: f.get('valid_from'), components, ...(change ? { reason: f.get('reason') } : {}) })}><div className="form-grid"><Field label="Assembly"><select required value={matnr} onChange={e => { setMatnr(e.target.value); if (change)
        setComponents(latest(e.target.value)?.components.map(c => ({ component: c.component, qty: c.qty })) || []); }}><option value="">Select assembly</option>{materials.filter(m => m.procurement === 'E' && (change || !revisions.some(r => r.matnr === m.matnr))).map(m => <option key={m.matnr} value={m.matnr}>{m.matnr} · {m.name}</option>)}</select></Field><Field label="New revision"><input name="revision" defaultValue={change ? 'B' : 'A'} required maxLength={20}/></Field><Field label="Valid from (inclusive)"><input name="valid_from" type="date" required defaultValue={today(1)}/></Field></div>{change && <Field label="Business reason"><textarea name="reason" required minLength={5} defaultValue="Upgrade controller for improved thermal performance"/></Field>}<h3>Components per one assembly</h3>{components.map((c, i) => <div className="component-edit" key={i}><Field label={`Component ${i + 1}`}><select value={c.component} onChange={e => update(i, 'component', e.target.value)}>{materials.filter(m => m.matnr !== matnr).map(m => <option key={m.matnr} value={m.matnr}>{m.matnr} · {m.name}</option>)}</select></Field><Field label="Quantity"><input type="number" min="0.0001" step="0.0001" required value={c.qty} onChange={e => update(i, 'qty', e.target.value)}/></Field><button type="button" className="secondary" aria-label={`Remove component ${i + 1}`} onClick={() => setComponents(old => old.filter((_, j) => i !== j))}>Remove</button></div>)}<button className="secondary" type="button" onClick={() => setComponents(old => [...old, { component: materials.find(m => m.procurement === 'F').matnr, qty: 1 }])}>Add component</button><p className="panel-note">{change ? 'For the sample change, replace CT-403 with CT-404. Approval and release are separate actions. Orders already created retain their snapshot.' : 'Existing BOMs can only be revised through engineering change management.'}</p><FormButtons close={close} submit={change ? 'Create change request' : 'Create BOM'}/></AsyncForm></Modal>;
}
function RoutingViewer({ materials }) {
    const [material, setMaterial] = useState(materials[0]?.matnr || '');
    const [ops, setOps] = useState([]);
    const [error, setError] = useState('');
    useEffect(() => { setError(''); api(`/routing/${material}`).then(setOps).catch(e => setError(e.message)); }, [material, materials]);
    return <><Field label="Material"><select value={material} onChange={e => setMaterial(e.target.value)}>{materials.map(m => <option key={m.matnr} value={m.matnr}>{m.matnr} · {m.name}</option>)}</select></Field>{error && <p role="alert">{error}</p>}<Table headers={['Operation', 'Work center', 'Description', 'Setup (min)', 'Run (min/unit)']}>{ops.map(o => <tr key={o.op}><td>{o.op}</td><td>{o.center}</td><td>{o.description}</td><td>{fmt(o.setup)}</td><td>{fmt(o.run)}</td></tr>)}</Table>{!ops.length && <Empty>No routing maintained for this material.</Empty>}</>;
}
function RoutingForm({ materials, centers, close, onSave }) {
    const [matnr, setMatnr] = useState(materials[0].matnr);
    const [operations, setOperations] = useState([]);
    const [loadError, setLoadError] = useState('');
    useEffect(() => { api(`/routing/${matnr}`).then(rows => setOperations(rows.map(({ op, center, description, setup, run }) => ({ op, center, description, setup, run })))).catch(e => setLoadError(e.message)); }, [matnr]);
    function update(i, field, value) { setOperations(old => old.map((o, j) => i === j ? { ...o, [field]: value } : o)); }
    return <Modal title="Maintain routing" close={close}><AsyncForm onSubmit={() => onSave(matnr, operations)}><Field label="Material"><select value={matnr} onChange={e => setMatnr(e.target.value)}>{materials.map(m => <option key={m.matnr} value={m.matnr}>{m.matnr}</option>)}</select></Field>{loadError && <p role="alert">{loadError}</p>}{operations.map((o, i) => <div className="operation-edit" key={i}><Field label="Op"><input required pattern="\d{4}" value={o.op} onChange={e => update(i, 'op', e.target.value)}/></Field><Field label="Center"><select value={o.center} onChange={e => update(i, 'center', e.target.value)}>{centers.map(c => <option key={c.arbpl}>{c.arbpl}</option>)}</select></Field><Field label="Description"><input required value={o.description} onChange={e => update(i, 'description', e.target.value)}/></Field><Field label="Setup min"><input required type="number" min="0" step="0.0001" value={o.setup} onChange={e => update(i, 'setup', e.target.value)}/></Field><Field label="Run min / unit"><input required type="number" min="0" step="0.0001" value={o.run} onChange={e => update(i, 'run', e.target.value)}/></Field><button className="secondary" type="button" onClick={() => setOperations(old => old.filter((_, j) => i !== j))}>Remove</button></div>)}<button type="button" className="secondary" onClick={() => setOperations(old => [...old, { op: String((old.length + 1) * 10).padStart(4, '0'), center: centers[0].arbpl, description: '', setup: 5, run: 5 }])}>Add operation</button><p className="panel-note">Changes apply to future conversions. Existing order operations remain frozen.</p><FormButtons close={close}/></AsyncForm></Modal>;
}
function DemandForm({ materials, onSave }) {
    return <AsyncForm onSubmit={f => onSave({ matnr: f.get('matnr'), qty: f.get('qty'), due: f.get('due'), source: 'SD demo demand' })}><div className="form-grid"><Field label="Material"><select name="matnr" defaultValue="EB-1000">{materials.map(m => <option key={m.matnr} value={m.matnr}>{m.matnr} · {m.name}</option>)}</select></Field><Field label="Required quantity"><input name="qty" type="number" min="0.0001" step="0.0001" defaultValue="200" required/></Field><Field label="Required receipt date"><input name="due" type="date" defaultValue={today(30)} required/></Field></div><button className="primary">Add demand</button></AsyncForm>;
}
function QuantityForm({ title, max, close, onSave }) {
    return <Modal title={title} close={close}><AsyncForm onSubmit={f => onSave(String(f.get('qty')))}><Field label={`Quantity (maximum ${fmt(max)})`}><input name="qty" type="number" min="0.0001" max={max} step="0.0001" defaultValue={max} required/></Field><FormButtons close={close} submit="Post goods receipt"/></AsyncForm></Modal>;
}
function ConfirmationForm({ order, close, onSave }) {
    const nextIndex = order.operations.findIndex(o => !o.final);
    const [op, setOp] = useState(order.operations[nextIndex]?.op || '');
    const selected = order.operations.find(o => o.op === op);
    const index = order.operations.indexOf(selected);
    const max = (index ? Number(order.operations[index - 1].yield) : order.qty) - Number(selected.yield || 0) - Number(selected.scrap || 0);
    return <Modal title={`Confirm operation · ORD-${order.id}`} close={close}><AsyncForm onSubmit={f => onSave({ op, yield_qty: f.get('yield_qty'), scrap: f.get('scrap'), minutes: f.get('minutes'), final: f.get('final') === 'on' })}><Field label="Operation"><select value={op} onChange={e => setOp(e.target.value)}>{order.operations.filter(o => !o.final).map(o => <option key={o.op} value={o.op}>{o.op} · {o.description}</option>)}</select></Field><div className="form-grid" key={op}><Field label="Incremental good yield"><input name="yield_qty" type="number" min="0" step="1" max={max} defaultValue={max} required/></Field><Field label="Incremental scrap"><input name="scrap" type="number" min="0" step="1" defaultValue="0" required/></Field><Field label="Actual minutes"><input name="minutes" type="number" min="0" step="0.0001" defaultValue={Number(selected.setup) + Number(selected.run) * max} required/></Field></div><label className="checkbox"><input name="final" type="checkbox" defaultChecked/> Final confirmation for this operation</label><p className="panel-note">Issue all components and complete preceding operations first. Final yield plus scrap must account for all input. Scrapped orders cannot be fully delivered in this simplified release.</p><FormButtons close={close} submit="Post confirmation"/></AsyncForm></Modal>;
}
createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>);
