import { useCallback, useEffect, useMemo, useState } from 'react'
import { minutesToTime, request, roomCodes, timeToMinutes, todayIST } from '../api'

const ACTIONS = [
  ['bookings', 'Bookings', 'Select a date to review, edit or remove confirmed bookings.'],
  ['requests', 'Faculty requests', 'Review pending terminal booking requests.'],
  ['maintenance', 'Room maintenance', 'Mark rooms unavailable or clear a maintenance window.'],
  ['accounts', 'Create account', 'Create a student, faculty or admin login.'],
  ['activity', 'Mail & audit', 'Review imported mail and recent administrative activity.'],
]

function Panel({ title, children, action }) {
  return <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"><div className="mb-4 flex items-center justify-between gap-3"><h2 className="text-lg font-semibold">{title}</h2>{action}</div>{children}</section>
}

function ampm(value) {
  const [hour, minute] = value.split(':').map(Number)
  return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${hour < 12 ? 'AM' : 'PM'}`
}

function CreateUser({ token, onError, onNotice }) {
  const [form, setForm] = useState({ username: '', display_name: '', password: '', role: 'FACULTY' })
  async function submit(event) {
    event.preventDefault()
    try {
      const created = await request('/admin/users', { token, method: 'POST', body: JSON.stringify(form) })
      onNotice(`Created ${created.role.toLowerCase()} account for ${created.display_name}.`)
      setForm({ username: '', display_name: '', password: '', role: 'FACULTY' })
    } catch (error) { onError(error.message) }
  }
  return <Panel title="Create an account"><form onSubmit={submit} className="grid max-w-3xl gap-3 sm:grid-cols-2">
    <label className="field-label">Username<input className="input" autoComplete="off" minLength="3" maxLength="80" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required /></label>
    <label className="field-label">Display name<input className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required /></label>
    <label className="field-label">Temporary password<input className="input" type="password" autoComplete="new-password" minLength="12" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /><span className="mt-1 block text-xs font-normal text-slate-500">At least 12 characters.</span></label>
    <label className="field-label">Role<select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}><option>FACULTY</option><option>ADMIN</option></select></label>
    <div className="sm:col-span-2"><button className="button-primary">Create account</button></div>
  </form></Panel>
}

function MaintenanceManager({ token, onError, onNotice, refreshAvailability }) {
  const [entries, setEntries] = useState([])
  const [form, setForm] = useState({ room_code: 'T1', maintenance_date: todayIST(), start_time: '08:00', end_time: '09:00', note: 'Room maintenance' })
  const load = useCallback(async () => {
    try { setEntries(await request(`/admin/room-maintenance?from=${todayIST()}&days=28`, { token })) }
    catch (error) { onError(error.message) }
  }, [token, onError])
  useEffect(() => { load() }, [load])
  const startTimes = Array.from({ length: 24 }, (_, index) => minutesToTime(480 + index * 30))
  const endTimes = Array.from({ length: 24 }, (_, index) => minutesToTime(510 + index * 30)).filter((value) => timeToMinutes(value) > timeToMinutes(form.start_time))
  async function submit(event) {
    event.preventDefault()
    try {
      const result = await request('/admin/room-maintenance', { token, method: 'POST', body: JSON.stringify(form) })
      const affected = [result.cancelled_bookings ? `${result.cancelled_bookings} confirmed booking${result.cancelled_bookings===1?'':'s'} cancelled` : '', result.rejected_requests ? `${result.rejected_requests} pending request${result.rejected_requests===1?'':'s'} rejected` : ''].filter(Boolean).join(' and ')
      onNotice(`Marked ${form.room_code} under maintenance on ${form.maintenance_date}.${affected ? ` ${affected}.` : ''}`)
      setForm({ ...form, note: 'Room maintenance' }); await load(); refreshAvailability()
    } catch (error) { onError(error.message) }
  }
  async function clear(id) {
    try {
      await request(`/admin/room-maintenance/${id}/clear`, { token, method: 'POST' })
      onNotice('Maintenance window cleared.'); await load(); refreshAvailability()
    } catch (error) { onError(error.message) }
  }
  return <Panel title="Room maintenance"><div className="grid gap-6 xl:grid-cols-[minmax(320px,440px)_1fr]">
    <form onSubmit={submit} className="space-y-3"><label className="field-label">Room<select className="input" value={form.room_code} onChange={(e) => setForm({ ...form, room_code: e.target.value })}>{roomCodes.map((room) => <option key={room}>{room}</option>)}</select></label>
      <label className="field-label">Date<input className="input" type="date" min={todayIST()} value={form.maintenance_date} onChange={(e) => setForm({ ...form, maintenance_date: e.target.value })} required /></label>
      <div className="grid grid-cols-2 gap-3"><label className="field-label">Start (IST)<select className="input" value={form.start_time} onChange={(e) => { const start=e.target.value; setForm({ ...form, start_time:start, end_time:minutesToTime(timeToMinutes(start)+30) }) }}>{startTimes.map((time) => <option key={time} value={time}>{ampm(time)}</option>)}</select></label><label className="field-label">End (IST)<select className="input" value={form.end_time} onChange={(e) => setForm({ ...form, end_time:e.target.value })}>{endTimes.map((time) => <option key={time} value={time}>{ampm(time)}</option>)}</select></label></div>
      <p className="text-xs text-amber-800">Confirmed bookings inside this maintenance window are automatically cancelled and their slots released. Pending faculty requests in the window are rejected with a reason.</p>
      <label className="field-label">Note<input className="input" maxLength={500} value={form.note} onChange={(e) => setForm({ ...form, note:e.target.value })} required /></label><button className="button-primary">Mark under maintenance</button>
    </form>
    <div className="space-y-2">{entries.length ? entries.map((entry) => <article key={entry.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-amber-50 p-3 text-sm"><span><b>{entry.room_code}</b> · {entry.maintenance_date} · {ampm(entry.start_time)}–{ampm(entry.end_time)}<small className="block text-slate-600">{entry.note}</small></span><button className="button-secondary" onClick={() => clear(entry.id)}>Clear</button></article>) : <p className="text-sm text-slate-500">No active maintenance windows in the next 28 days.</p>}</div>
  </div></Panel>
}

function BookingManager({ token, onError, onNotice, refreshAdmin, refreshAvailability }) {
  const [selectedDate, setSelectedDate] = useState(todayIST())
  const [month, setMonth] = useState(() => `${todayIST().slice(0, 7)}-01`)
  const [bookings, setBookings] = useState([])
  const [bookingsLoading, setBookingsLoading] = useState(false)
  const [form, setForm] = useState(null)
  const monthPrefix = month.slice(0, 7)
  const load = useCallback(async () => {
    setBookingsLoading(true)
    try {
      const rows = await request(`/admin/bookings?from=${monthPrefix}-01&days=35`, { token })
      setBookings(rows.map((row) => ({ ...row, room: row.room_code, date: row.booking_date, start: row.start_time, end: row.end_time })))
    } catch (error) {
      onError(error.message)
    } finally {
      setBookingsLoading(false)
    }
  }, [monthPrefix, token, onError])
  useEffect(() => { load() }, [load, refreshAdmin])
  const dayBookings = useMemo(() => bookings.filter((booking) => booking.date === selectedDate)
    .sort((a, b) => a.start.localeCompare(b.start) || a.room.localeCompare(b.room)), [bookings, selectedDate])
  const bookingCounts = useMemo(() => bookings.reduce((counts, booking) => {
    counts[booking.date] = (counts[booking.date] || 0) + 1
    return counts
  }, {}), [bookings])
  const monthStart = new Date(`${month}T12:00:00`)
  const monthDays = new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0).getDate()
  const leading = (monthStart.getDay() + 6) % 7
  const startTimes = Array.from({ length: 24 }, (_, index) => minutesToTime(480 + index * 30))
  const endTimes = Array.from({ length: 24 }, (_, index) => minutesToTime(510 + index * 30))
  function openEditor(booking) { setForm({ ...booking, start_time: booking.start, end_time: booking.end, purpose: booking.purpose || 'Booking' }) }
  async function saveEdit(event) {
    event.preventDefault()
    try {
      await request(`/admin/bookings/${form.id}`, { token, method: 'PATCH', body: JSON.stringify({ room_code: form.room, booking_date: form.date, start_time: form.start_time, end_time: form.end_time, purpose: form.purpose }) })
      onNotice(`Updated ${form.room} booking to ${ampm(form.start_time)}–${ampm(form.end_time)}.`)
      setForm(null); await load(); refreshAvailability()
    } catch (error) { onError(error.message) }
  }
  async function remove(booking) {
    if (!window.confirm(`Delete ${booking.room} on ${booking.date}, ${ampm(booking.start)}–${ampm(booking.end)}? The slot will become available and an audit record will be kept.`)) return
    try {
      await request(`/admin/bookings/${booking.id}`, { token, method: 'DELETE' })
      onNotice('Booking deleted from the active schedule.'); setForm(null); await load(); refreshAvailability()
    } catch (error) { onError(error.message) }
  }
  return <Panel title="Bookings by date"><div className="grid gap-6 xl:grid-cols-[340px_1fr]">
    <div className="rounded-xl border border-slate-200 p-4">
      <div className="mb-4 flex items-center justify-between"><button className="button-secondary px-3" aria-label="Previous month" onClick={() => { const d = new Date(`${month}T12:00:00`); d.setMonth(d.getMonth()-1); setMonth(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`) }}>←</button><h3 className="font-semibold">{monthStart.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}</h3><button className="button-secondary px-3" aria-label="Next month" onClick={() => { const d = new Date(`${month}T12:00:00`); d.setMonth(d.getMonth()+1); setMonth(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`) }}>→</button></div>
      <div className="grid grid-cols-7 gap-1 text-center text-xs text-slate-500">{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((day) => <span key={day} className="py-2">{day}</span>)}
        {Array.from({ length: leading }, (_, i) => <span key={`blank-${i}`} />)}
        {Array.from({ length: monthDays }, (_, i) => { const date = `${month.slice(0,7)}-${String(i+1).padStart(2,'0')}`; const count=bookingCounts[date]||0; return <button key={date} onClick={() => { setSelectedDate(date); setForm(null) }} className={`relative rounded-lg py-2 text-sm hover:bg-teal-50 ${selectedDate===date ? 'bg-teal-700 font-semibold text-white hover:bg-teal-800' : 'text-slate-800'}`} aria-label={`${date}${count ? `, ${count} bookings` : ''}`} aria-pressed={selectedDate===date}>{i+1}{count>0 && <i className={`absolute bottom-0.5 left-1/2 h-1 w-1 -translate-x-1/2 rounded-full ${selectedDate===date?'bg-white':'bg-rose-500'}`} />}</button> })}
      </div><p className="mt-3 text-xs text-slate-500"><i className="mr-1 inline-block h-2 w-2 rounded-full bg-rose-500" />Days with confirmed bookings · Choose a date to view them.</p>
    </div>
    <div><div className="mb-4 flex flex-wrap items-center justify-between gap-2"><div><h3 className="font-semibold">{new Date(`${selectedDate}T12:00:00`).toLocaleDateString('en-IN',{weekday:'long',day:'numeric',month:'long',year:'numeric'})}</h3><p className="text-sm text-slate-500">{bookingsLoading?'Loading bookings from database…':`${dayBookings.length} confirmed booking${dayBookings.length===1?'':'s'}`}</p></div><input className="input max-w-48" type="date" value={selectedDate} onChange={(e) => { setSelectedDate(e.target.value); setMonth(`${e.target.value.slice(0,7)}-01`); setForm(null) }} aria-label="Select booking date" /></div>
      {form ? <form onSubmit={saveEdit} className="mb-4 rounded-xl border border-teal-200 bg-teal-50 p-4"><div className="mb-3 flex items-center justify-between"><b>Edit {form.room} booking · {form.date}</b><button type="button" className="text-sm text-slate-600 underline" onClick={() => setForm(null)}>Close</button></div><div className="grid gap-3 sm:grid-cols-2"><label className="field-label">Start (IST)<select className="input" value={form.start_time} onChange={(e)=>setForm({...form,start_time:e.target.value})}>{startTimes.map((time)=><option key={time} value={time}>{ampm(time)}</option>)}</select></label><label className="field-label">End (IST)<select className="input" value={form.end_time} onChange={(e)=>setForm({...form,end_time:e.target.value})}>{endTimes.filter((time)=>timeToMinutes(time)>timeToMinutes(form.start_time)).map((time)=><option key={time} value={time}>{ampm(time)}</option>)}</select></label><label className="field-label sm:col-span-2">Purpose<input className="input" maxLength={500} value={form.purpose} onChange={(e)=>setForm({...form,purpose:e.target.value})} required /></label></div><p className="my-3 text-xs text-slate-600">Room and date stay fixed. The server rejects time conflicts with bookings, requests, or maintenance.</p><div className="flex gap-2"><button className="button-primary">Save timing</button><button type="button" className="button-secondary" onClick={()=>setForm(null)}>Cancel</button></div></form> : null}
      <div className="space-y-2">{dayBookings.length ? dayBookings.map((booking)=><article key={booking.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"><div><p className="font-semibold">{booking.room} <span className="font-normal text-slate-600">· {ampm(booking.start)}–{ampm(booking.end)}</span></p><p className="mt-1 text-xs text-slate-500">Confirmed booking</p></div><div className="flex gap-2"><button className="button-secondary" onClick={()=>openEditor(booking)}>Edit time</button><button className="rounded-lg border border-rose-200 px-3 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50" onClick={()=>remove(booking)}>Delete</button></div></article>) : <p className="rounded-lg bg-slate-50 p-5 text-sm text-slate-500">No confirmed bookings for this date.</p>}</div>
    </div>
  </div></Panel>
}

export default function AdminDashboard({ token, schedule, onError, onNotice, refreshAdmin, refreshAvailability }) {
  const [active, setActive] = useState('')
  const [pending, setPending] = useState([])
  const [emailLogs, setEmailLogs] = useState([])
  const [auditLogs, setAuditLogs] = useState([])
  const [rejectingId, setRejectingId] = useState(null)
  const [rejectionReason, setRejectionReason] = useState('')
  const loadActivity = useCallback(async () => {
    try {
      const [requests, emails, audit] = await Promise.all([
        request('/admin/booking-requests?status=PENDING', { token }),
        request('/admin/email-logs', { token }), request('/admin/audit-logs', { token }),
      ])
      setPending(requests); setEmailLogs(emails); setAuditLogs(audit)
    } catch (error) { onError(error.message) }
  }, [token, onError])
  useEffect(() => { if (active === 'requests' || active === 'activity') loadActivity() }, [active, loadActivity, refreshAdmin])
  async function decide(id, choice, note = '') {
    try { await request(`/admin/booking-requests/${id}/${choice}`, { token, method: 'POST', ...(choice === 'reject' ? { body: JSON.stringify({ note }) } : {}) }); onNotice(`Request ${choice}d${choice === 'reject' ? ' with a reason' : ''}.`); setRejectingId(null); setRejectionReason(''); await loadActivity(); refreshAvailability() }
    catch (error) { onError(error.message) }
  }
  const activeAction = ACTIONS.find(([id]) => id === active)
  return <div className="space-y-6">
    <section className="rounded-2xl bg-slate-900 px-6 py-7 text-white sm:px-8"><p className="text-sm font-medium text-teal-300">CCC administration</p><h2 className="mt-2 text-3xl font-semibold">Admin dashboard</h2><p className="mt-2 text-sm text-slate-300">Choose an action to manage bookings, accounts, rooms and mail.</p></section>
    <section aria-label="Admin actions" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{ACTIONS.map(([id,title,description])=><button key={id} onClick={()=>setActive(active===id?'':id)} aria-expanded={active===id} className={`rounded-xl border p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-teal-300 hover:shadow ${active===id?'border-teal-600 bg-teal-50 ring-1 ring-teal-600':'border-slate-200 bg-white'}`}><span className="flex items-center justify-between font-semibold">{title}<span aria-hidden="true" className="text-teal-700">{active===id?'−':'+'}</span></span><span className="mt-1 block text-sm text-slate-500">{description}</span></button>)}</section>
    {activeAction && <div className="space-y-5"><div className="flex items-center justify-between"><div><p className="text-xs font-semibold uppercase tracking-wide text-teal-700">Admin action</p><h3 className="text-xl font-semibold">{activeAction[1]}</h3></div><button className="button-secondary" onClick={()=>setActive('')}>Close panel</button></div>
      {active==='bookings' && <BookingManager token={token} onError={onError} onNotice={onNotice} refreshAdmin={refreshAdmin} refreshAvailability={refreshAvailability} />}
      {active==='accounts' && <CreateUser token={token} onError={onError} onNotice={onNotice} />}
      {active==='maintenance' && <MaintenanceManager token={token} onError={onError} onNotice={onNotice} refreshAvailability={refreshAvailability} />}
      {active==='requests' && <Panel title="Pending faculty requests" action={<button className="button-secondary" onClick={loadActivity}>Refresh</button>}><div className="divide-y">{pending.length ? pending.map((item)=><article key={item.id} className="py-4"><div className="flex flex-wrap items-center justify-between gap-4"><div className="text-sm"><b>{item.room_code}</b> · {item.booking_date} · {ampm(item.start_time)}–{ampm(item.end_time)}<p className="mt-1 text-slate-600">{item.purpose}</p></div><div className="flex gap-2"><button className="button-primary" onClick={()=>decide(item.id,'approve')}>Approve</button><button className="button-secondary" onClick={()=>{setRejectingId(rejectingId===item.id?null:item.id);setRejectionReason('')}}>Reject</button></div></div>{rejectingId===item.id&&<form className="mt-3 rounded-lg bg-rose-50 p-3" onSubmit={(event)=>{event.preventDefault();decide(item.id,'reject',rejectionReason)}}><label className="field-label">Reason for rejection<textarea className="input min-h-20" minLength={3} maxLength={500} value={rejectionReason} onChange={(event)=>setRejectionReason(event.target.value)} placeholder="Explain why this request cannot be approved" required /></label><div className="mt-2 flex gap-2"><button className="rounded-lg bg-rose-700 px-3 py-2 text-sm font-semibold text-white" disabled={rejectionReason.trim().length<3}>Reject with reason</button><button type="button" className="button-secondary" onClick={()=>setRejectingId(null)}>Cancel</button></div></form>}</article>) : <p className="py-5 text-sm text-slate-500">No pending requests.</p>}</div></Panel>}
      {active==='activity' && <div className="grid gap-5 xl:grid-cols-2"><Panel title="Email processing"><div className="space-y-3">{emailLogs.length?emailLogs.map((email)=><article key={email.id} className="rounded-lg bg-slate-50 p-3 text-sm"><div className="flex justify-between gap-3"><b className="truncate">{email.subject||'(no subject)'}</b><span className="badge">{email.status}</span></div><p className="mt-1 truncate text-xs text-slate-500">{email.sender} {email.received_at?`· ${new Date(email.received_at).toLocaleString()}`:''}</p>{email.parsed&&<p className="mt-2 text-xs text-slate-700">{email.parsed.room_code||'Room unknown'} · {email.parsed.booking_date||'Date unknown'} · {email.parsed.start_time||'?'}–{email.parsed.end_time||'?'} IST</p>}{email.error&&<p className="mt-2 text-xs text-rose-700">{email.error}</p>}</article>):<p className="text-sm text-slate-500">No messages processed yet.</p>}</div></Panel><Panel title="Recent audit events"><div className="space-y-2">{auditLogs.slice(0,50).map((item)=><div key={item.id} className="flex justify-between gap-3 border-b py-2 text-xs"><span>{item.action} · {item.entity_type}</span><time className="shrink-0 text-slate-500">{new Date(item.created_at).toLocaleString()}</time></div>)}{!auditLogs.length&&<p className="text-sm text-slate-500">No events recorded.</p>}</div></Panel></div>}
    </div>}
  </div>
}
