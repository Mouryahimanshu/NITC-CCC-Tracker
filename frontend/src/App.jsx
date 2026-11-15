import { useCallback, useEffect, useMemo, useState } from 'react'
import { request, roomCodes, timeToMinutes, todayIST } from './api'
import AdminDashboard from './pages/AdminDashboard'
import FacultyDashboard from './pages/FacultyDashboard'

function dateLabel(value, options = { weekday: 'short', day: 'numeric', month: 'short' }) {
  return new Intl.DateTimeFormat('en-IN', { ...options, timeZone: 'Asia/Kolkata' }).format(new Date(`${value}T12:00:00+05:30`))
}

function AvailabilityPage({ schedule, days, startDate, setStartDate, rangeDays, setRangeDays, shiftRange, goToday, loading, availabilityState, syncStatus }) {
  const byRoomDate = new Map(schedule.map((entry) => [`${entry.room_code}-${entry.date}`, entry]))
  const rangeEnd = days[days.length - 1]
  return <div className="space-y-6">
    <section className="rounded-2xl bg-slate-900 px-6 py-7 text-white sm:px-8">
      <div className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="text-sm font-medium text-teal-300">Central Computer Centre</p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight">Terminal room schedule</h2>
          <p className="mt-2 max-w-xl text-sm leading-6 text-slate-300">Browse multiple weeks. Bars show confirmed bookings and maintenance on a half-hour timeline in IST.</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm text-slate-300">Range<select className="ml-2 rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-white" value={rangeDays} onChange={(e) => setRangeDays(Number(e.target.value))}><option value={7}>1 week</option><option value={14}>2 weeks</option><option value={28}>4 weeks</option></select></label>
          <label className="text-sm text-slate-300">Starting date<input className="ml-2 rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-white" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} /></label>
        </div>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <button className="rounded-md border border-slate-600 px-3 py-2 text-sm hover:bg-slate-800" onClick={() => shiftRange(-1)}>← Previous</button>
        <button className="rounded-md border border-slate-600 px-3 py-2 text-sm hover:bg-slate-800" onClick={goToday}>Today</button>
        <button className="rounded-md border border-slate-600 px-3 py-2 text-sm hover:bg-slate-800" onClick={() => shiftRange(1)}>Next →</button>
        <span className="ml-1 text-sm text-slate-300">{dateLabel(startDate, { day: 'numeric', month: 'short', year: 'numeric' })} – {dateLabel(rangeEnd, { day: 'numeric', month: 'short', year: 'numeric' })}</span>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 pt-3 text-xs text-slate-400">
        <span>
          Last mailbox synchronization:{' '}
          <strong className="text-slate-200">
            {syncStatus?.last_sync_time ? `${new Date(syncStatus.last_sync_time).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Asia/Kolkata' })} IST` : 'No sync recorded'}
          </strong>
        </span>
        {syncStatus?.is_stale ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/20 px-2.5 py-0.5 text-xs font-medium text-amber-300 ring-1 ring-inset ring-amber-500/40">
            ⚠️ Mailbox sync older than 15 min
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full bg-teal-500/20 px-2.5 py-0.5 text-xs font-medium text-teal-300">
            ✓ Mailbox synchronized
          </span>
        )}
      </div>
    </section>
    {syncStatus?.is_stale && (
      <div role="alert" className="flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-900 shadow-sm">
        <span className="text-xl" aria-hidden="true">⚠️</span>
        <div>
          <h3 className="text-sm font-semibold">Stale Data Warning (NFR-08)</h3>
          <p className="mt-0.5 text-xs text-amber-800">
            Mailbox synchronization has not succeeded within the last 15 minutes. Displayed availability may not reflect recent email reservation requests.
          </p>
        </div>
      </div>
    )}
    {availabilityState !== 'ready' && <div role="status" className={`rounded-lg px-4 py-3 text-sm ${availabilityState === 'error' ? 'bg-amber-50 text-amber-900' : 'bg-slate-100 text-slate-700'}`}>{availabilityState === 'error' ? 'Availability could not be confirmed. Refresh after reconnecting to the database.' : 'Loading confirmed bookings…'}</div>}
    {days.map((day) => {
      const dayEntries = roomCodes.map((room) => ({ room, ...(byRoomDate.get(`${room}-${day}`) || { bookings: [], maintenance: [] }) }))
      const bookingCount = dayEntries.reduce((count, entry) => count + entry.bookings.length, 0)
      const maintenanceCount = dayEntries.reduce((count, entry) => count + (entry.maintenance || []).length, 0)
      return <section key={day} className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm"><div className="min-w-[900px]"><div className="flex items-center justify-between border-b bg-slate-50 px-5 py-3"><div><h3 className="font-semibold">{dateLabel(day, { weekday: 'long', day: 'numeric', month: 'long' })}</h3><p className="text-xs text-slate-500">{availabilityState === 'ready' ? `${bookingCount} booked · ${maintenanceCount} under maintenance` : availabilityState === 'loading' ? 'Loading schedule…' : 'Availability unknown'}</p></div><span className="text-xs text-slate-500">IST · 8 AM–8 PM</span></div>
        <div className="grid grid-cols-[60px_minmax(0,1fr)] items-end gap-4 px-4 pt-4"><span aria-hidden="true" /><div className="relative mb-2 h-5 text-[10px] text-slate-600">{Array.from({ length: 13 }, (_, index) => { const hour = 8 + index; const label = `${hour % 12 || 12} ${hour < 12 ? 'AM' : 'PM'}`; return <span key={hour} className={`absolute whitespace-nowrap ${index === 0 ? '' : index === 12 ? '-translate-x-full' : '-translate-x-1/2'}`} style={{ left: `${(index / 12) * 100}%` }}>{label}</span> })}</div></div>
        <div className="divide-y">{dayEntries.map(({ room, bookings, maintenance = [] }) => <div key={room} className="grid grid-cols-[60px_minmax(0,1fr)] items-center gap-4 px-4 py-2"><span className="text-sm font-semibold">{room}</span><div>
          <div className={`relative h-11 rounded-md ${availabilityState === 'ready' ? 'bg-teal-50' : 'bg-slate-100'}`} style={{ backgroundImage: 'repeating-linear-gradient(to right, transparent 0, transparent calc(8.333333% - 1px), #cbd5e1 calc(8.333333% - 1px), #cbd5e1 8.333333%)' }} aria-label={`${room} timeline for ${day}`}>
            {availabilityState === 'ready' && bookings.map((booking) => <TimelineBar key={`booked-${booking.id}`} item={booking} tone="rose" label="Confirmed booking" />)}
            {availabilityState === 'ready' && maintenance.map((item) => <TimelineBar key={`maintenance-${item.id}`} item={item} tone="amber" label="Under maintenance" />)}
          </div>
          {availabilityState === 'ready' && (bookings.length > 0 || maintenance.length > 0) && <div className="mt-1 flex flex-wrap gap-1">{bookings.map((booking) => <span key={`b-${booking.id}`} className="rounded bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-900">Booked {toAmPm(booking.start)}–{toAmPm(booking.end)}</span>)}{maintenance.map((item) => <span key={`m-${item.id}`} className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-900">Maintenance {toAmPm(item.start)}–{toAmPm(item.end)}</span>)}</div>}
        </div></div>)}</div>
      </div><div className="flex flex-wrap gap-4 border-t px-5 py-3 text-xs text-slate-600"><span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-teal-200" />Available</span><span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-rose-400" />Booked</span><span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-amber-400" />Under maintenance</span>{loading && <span className="ml-auto">Updating…</span>}</div></section>
    })}
  </div>
}

function TimelineBar({ item, tone, label }) {
  const start = timeToMinutes(item.start)
  const end = timeToMinutes(item.end)
  const left = ((start - 480) / 720) * 100
  const width = ((end - start) / 720) * 100
  const colors = tone === 'amber' ? 'bg-amber-400 text-amber-950 ring-amber-500' : 'bg-rose-400 text-rose-950 ring-rose-500'
  return <div title={`${toAmPm(item.start)}–${toAmPm(item.end)} IST · ${label}`} className={`absolute top-1 flex h-9 items-center justify-center overflow-visible rounded px-1 text-[10px] font-semibold ring-1 ${colors}`} style={{ left: `${left}%`, width: `${width}%`, minWidth: '2px' }}><span className="pointer-events-none whitespace-nowrap rounded bg-white/85 px-1">{toAmPm(item.start)}–{toAmPm(item.end)}</span></div>
}

function toAmPm(value) {
  const [hour, minute] = value.split(':').map(Number)
  return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${hour < 12 ? 'AM' : 'PM'}`
}

function LoginDrawer({ role, onClose, onLogin }) {
  const [credentials, setCredentials] = useState({ username: '', password: '' })
  const [error, setError] = useState('')
  const [collapsed, setCollapsed] = useState(false)
  async function submit(event) {
    event.preventDefault()
    setError('')
    const result = await onLogin(credentials, role)
    if (result) setError(result)
  }
  const roleName = role === 'FACULTY' ? 'Faculty' : 'Administrator'
  return <>
    {!collapsed && <button aria-label="Close sign in panel" className="fixed inset-0 z-40 cursor-default bg-slate-950/30" onClick={onClose} />}
    <aside className={`fixed inset-y-0 right-0 z-50 border-l border-slate-200 bg-white shadow-2xl transition-[width] duration-200 ${collapsed ? 'w-14' : 'w-full sm:w-1/4 sm:min-w-[320px] sm:max-w-[440px]'}`} aria-label={`${roleName} sign in`}>
      {collapsed ? <button className="flex h-full w-full flex-col items-center gap-3 bg-slate-900 py-5 text-white" onClick={() => setCollapsed(false)} aria-label="Expand sign in panel"><span className="text-xl">‹</span><span className="vertical-label text-xs font-semibold">{roleName} login</span></button> : <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b px-5 py-4"><div><p className="text-xs font-semibold uppercase tracking-wider text-teal-700">CCC Tracker</p><h2 className="mt-1 text-lg font-semibold">{roleName} login</h2></div><div className="flex gap-2"><button className="button-secondary px-3" title="Minimize panel" onClick={() => setCollapsed(true)}>−</button><button className="button-secondary px-3" title="Close panel" onClick={onClose}>×</button></div></div>
        <form onSubmit={submit} className="flex flex-1 flex-col gap-4 p-5"><p className="text-sm leading-6 text-slate-600">Sign in with your CCC Tracker {roleName.toLowerCase()} account.</p><label className="field-label">Username<input className="input" autoComplete="username" value={credentials.username} onChange={(e) => setCredentials({ ...credentials, username: e.target.value })} required autoFocus /></label><label className="field-label">Password<input className="input" type="password" autoComplete="current-password" value={credentials.password} onChange={(e) => setCredentials({ ...credentials, password: e.target.value })} required /></label>{error && <p role="alert" className="rounded-md bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}<button className="button-primary mt-1 w-full">Sign in as {roleName}</button><button type="button" className="mt-auto self-start text-sm text-slate-500 underline" onClick={onClose}>Back to schedule</button></form>
      </div>}
    </aside>
  </>
}

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem('ccc-token') || '')
  const [user, setUser] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [drawerRole, setDrawerRole] = useState(null)
  const [page, setPage] = useState(() => window.location.hash.slice(1) || 'availability')
  const [startDate, setStartDate] = useState(todayIST)
  const [rangeDays, setRangeDays] = useState(14)
  const [schedule, setSchedule] = useState([])
  const [syncStatus, setSyncStatus] = useState(null)
  const [availabilityLoading, setAvailabilityLoading] = useState(false)
  const [availabilityState, setAvailabilityState] = useState('loading')
  const [availabilityVersion, setAvailabilityVersion] = useState(0)
  const [adminVersion, setAdminVersion] = useState(0)
  const days = useMemo(() => Array.from({ length: rangeDays }, (_, index) => { const date = new Date(`${startDate}T12:00:00+05:30`); date.setDate(date.getDate() + index); return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(date) }), [startDate, rangeDays])
  const loadAvailability = useCallback(async () => {
    setAvailabilityLoading(true)
    setAvailabilityState('loading')
    try {
      const [scheduleData, syncData] = await Promise.all([
        request(`/rooms/availability?from=${startDate}&days=${rangeDays}`),
        request('/rooms/sync-status').catch(() => null),
      ])
      setSchedule(scheduleData)
      if (syncData) setSyncStatus(syncData)
      setAvailabilityState('ready')
      setError('')
    } catch (loadError) {
      setAvailabilityState('error')
      setError(loadError.message)
    } finally {
      setAvailabilityLoading(false)
    }
  }, [startDate, rangeDays])
  const refreshAvailability = useCallback(() => setAvailabilityVersion((version) => version + 1), [])
  const refreshAdmin = useCallback(() => setAdminVersion((version) => version + 1), [])
  const onError = useCallback((message) => { setError(message); setNotice('') }, [])
  const onNotice = useCallback((message) => { setNotice(message); setError(''); refreshAdmin() }, [refreshAdmin])
  const navigate = useCallback((nextPage) => { window.location.hash = nextPage; setPage(nextPage); setError('') }, [])
  useEffect(() => { loadAvailability() }, [loadAvailability, availabilityVersion])
  useEffect(() => { const updatePage = () => setPage(window.location.hash.slice(1) || 'availability'); window.addEventListener('hashchange', updatePage); return () => window.removeEventListener('hashchange', updatePage) }, [])
  useEffect(() => {
    if (!token) { setUser(null); return }
    request('/auth/me', { token }).then((currentUser) => { setUser(currentUser); const target = currentUser.role === 'ADMIN' ? 'admin' : currentUser.role === 'FACULTY' ? 'faculty' : 'availability'; if (window.location.hash.slice(1) !== target) navigate(target) }).catch(() => { sessionStorage.removeItem('ccc-token'); setToken(''); setUser(null) })
  }, [token, navigate])

  async function doLogin(credentials, expectedRole) {
    try {
      const result = await request('/auth/login', { method: 'POST', body: JSON.stringify(credentials) })
      if (result.user.role !== expectedRole) return `This account has the ${result.user.role.toLowerCase()} role. Choose the matching login option.`
      sessionStorage.setItem('ccc-token', result.access_token)
      setToken(result.access_token); setUser(result.user); setDrawerRole(null); setNotice(`Signed in as ${result.user.display_name}`); setError('')
      navigate(expectedRole === 'ADMIN' ? 'admin' : 'faculty')
      return null
    } catch (loginError) { return loginError.message }
  }
  function logout() { sessionStorage.removeItem('ccc-token'); setToken(''); setUser(null); navigate('availability'); setNotice('Signed out') }
  function shiftRange(direction) { const nextDate = new Date(`${startDate}T12:00:00+05:30`); nextDate.setDate(nextDate.getDate() + direction * rangeDays); setStartDate(new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(nextDate)) }
  const validPage = page === 'availability' || user?.role === 'ADMIN' && page === 'admin' || user?.role === 'FACULTY' && page === 'faculty'

  return <main className="min-h-screen bg-slate-50 text-slate-900"><header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur"><div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-5 py-4 lg:px-8"><button className="text-left" onClick={() => navigate('availability')}><p className="text-xs font-semibold uppercase tracking-[.17em] text-teal-700">National Institute of Technology Calicut</p><h1 className="mt-1 text-xl font-semibold">CCC Terminal Booking Tracker</h1></button><nav className="flex items-center gap-2">{user ? <><button className="button-secondary" onClick={() => navigate('availability')}>Schedule</button><button className="button-secondary" onClick={() => navigate(user.role.toLowerCase())}>Dashboard</button><span className="ml-2 hidden text-sm text-slate-600 sm:inline">{user.display_name} · {user.role}</span><button className="button-secondary" onClick={logout}>Sign out</button></> : <div className="group relative"><button className="button-primary px-5 py-2.5" aria-haspopup="true">Login <span aria-hidden="true">⌄</span></button><div className="invisible absolute right-0 top-full z-40 mt-2 w-52 translate-y-1 rounded-xl border border-slate-200 bg-white p-2 opacity-0 shadow-xl transition group-hover:visible group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:opacity-100"><button className="w-full rounded-lg px-3 py-2.5 text-left text-sm hover:bg-teal-50" onClick={() => setDrawerRole('FACULTY')}>Faculty login</button><button className="w-full rounded-lg px-3 py-2.5 text-left text-sm hover:bg-teal-50" onClick={() => setDrawerRole('ADMIN')}>Admin login</button></div></div>}</nav></div></header>
    <div className="mx-auto max-w-7xl space-y-7 px-5 py-8 lg:px-8">{(error || notice) && <div role={error ? 'alert' : 'status'} className={`rounded-lg px-4 py-3 text-sm ${error ? 'bg-rose-50 text-rose-800' : 'bg-teal-50 text-teal-900'}`}>{error || notice}<button className="float-right font-semibold" onClick={() => { setError(''); setNotice('') }}>×</button></div>}
      {validPage && page === 'availability' && <AvailabilityPage schedule={schedule} days={days} startDate={startDate} setStartDate={setStartDate} rangeDays={rangeDays} setRangeDays={setRangeDays} shiftRange={shiftRange} goToday={() => setStartDate(todayIST())} loading={availabilityLoading} availabilityState={availabilityState} syncStatus={syncStatus} />}
      {user?.role === 'FACULTY' && page === 'faculty' && <FacultyDashboard token={token} onError={onError} onNotice={onNotice} refreshAvailability={refreshAvailability} />}
      {user?.role === 'ADMIN' && page === 'admin' && <AdminDashboard token={token} schedule={schedule} onError={onError} onNotice={onNotice} refreshAdmin={adminVersion} refreshAvailability={refreshAvailability} />}
      {!validPage && user && <div className="rounded-xl border border-slate-200 bg-white p-6"><h2 className="text-lg font-semibold">Dashboard page unavailable</h2><button className="button-primary mt-4" onClick={() => navigate(user.role === 'ADMIN' ? 'admin' : user.role === 'FACULTY' ? 'faculty' : 'availability')}>Open my dashboard</button></div>}
      {!user && <p className="text-sm text-slate-500">Students can view the schedule without signing in. Faculty and administrators can sign in from the header.</p>}
    </div><footer className="border-t border-slate-200 px-5 py-5 text-center text-xs text-slate-500">NITC Central Computer Centre · Operating hours 08:00–20:00 IST · bookings in 30-minute increments</footer>
    {drawerRole && <LoginDrawer key={drawerRole} role={drawerRole} onClose={() => setDrawerRole(null)} onLogin={doLogin} />}
  </main>
}
