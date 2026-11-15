import { useCallback, useEffect, useState } from 'react'
import { minutesToTime, request, roomCodes, timeToMinutes, todayIST } from '../api'

const blankBooking = { room_code: 'T1', booking_date: todayIST(), start_time: '08:00', end_time: '09:00', purpose: '' }

function Panel({ title, children, action }) {
  return <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold">{title}</h2>{action}</div>{children}</section>
}

export default function FacultyDashboard({ token, onError, onNotice, refreshAvailability }) {
  const [form, setForm] = useState(blankBooking)
  const [requests, setRequests] = useState([])
  const [availability, setAvailability] = useState(null)
  const [availabilityError, setAvailabilityError] = useState('')
  const [availabilityLoading, setAvailabilityLoading] = useState(false)
  const load = useCallback(async () => {
    try { setRequests(await request('/booking-requests/mine', { token })) }
    catch (error) { onError(error.message) }
  }, [token, onError])
  useEffect(() => { load() }, [load])

  const loadSelectedAvailability = useCallback(async () => {
    setAvailabilityLoading(true)
    setAvailabilityError('')
    try {
      const rows = await request(`/rooms/availability?from=${form.booking_date}&days=1`)
      setAvailability(rows.find((row) => row.room_code === form.room_code) || null)
    } catch (error) {
      setAvailability(null)
      setAvailabilityError(error.message)
    } finally { setAvailabilityLoading(false) }
  }, [form.booking_date, form.room_code])
  useEffect(() => { loadSelectedAvailability() }, [loadSelectedAvailability])

  const startTimes = Array.from({ length: 24 }, (_, index) => minutesToTime(480 + index * 30))
  const endTimes = Array.from({ length: 24 }, (_, index) => minutesToTime(510 + index * 30))
    .filter((time) => timeToMinutes(time) > timeToMinutes(form.start_time))

  const overlapsUnavailable = (start, end) => availability?.slots?.some((slot) =>
    slot.status !== 'AVAILABLE' && timeToMinutes(slot.start) < timeToMinutes(end) && timeToMinutes(slot.end) > timeToMinutes(start)) ?? false

  useEffect(() => {
    if (!availability) return
    const startIsAvailable = !overlapsUnavailable(form.start_time, minutesToTime(timeToMinutes(form.start_time) + 30))
    const nextStart = startIsAvailable ? form.start_time : startTimes.find((time) =>
      !overlapsUnavailable(time, minutesToTime(timeToMinutes(time) + 30)))
    if (!nextStart) return
    const validEnd = endTimes.some((time) => time === form.end_time && !overlapsUnavailable(nextStart, time))
    if (!startIsAvailable || !validEnd) {
      const nextEnd = endTimes.find((time) => timeToMinutes(time) > timeToMinutes(nextStart) && !overlapsUnavailable(nextStart, time))
      setForm((current) => ({ ...current, start_time: nextStart, end_time: nextEnd || minutesToTime(timeToMinutes(nextStart) + 30) }))
    }
  }, [availability])

  async function submit(event) {
    event.preventDefault()
    if (availabilityLoading || availabilityError || !availability) { onError('Could not confirm live room availability. Refresh availability and try again.'); return }
    if (overlapsUnavailable(form.start_time, form.end_time)) { onError('That time is already booked, under maintenance, or pending approval. Choose an available interval.'); await loadSelectedAvailability(); return }
    try {
      await request('/booking-requests', { token, method: 'POST', body: JSON.stringify(form) })
      onNotice('Booking request submitted for administrator review.')
      setForm({ ...blankBooking, booking_date: todayIST() })
      await load()
      await loadSelectedAvailability()
      refreshAvailability()
    } catch (error) { onError(error.message) }
  }

  return <div className="space-y-6">
    <section className="rounded-2xl bg-slate-900 px-6 py-7 text-white sm:px-8"><p className="text-sm font-medium text-teal-300">Faculty workspace</p><h2 className="mt-2 text-3xl font-semibold">Booking dashboard</h2><p className="mt-2 text-sm text-slate-300">Request a room and track CCC approval.</p></section>
    <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
      <Panel title="Request a terminal"><form onSubmit={submit} className="space-y-3">
        <label className="field-label">Room<select className="input" value={form.room_code} onChange={(e) => setForm({ ...form, room_code: e.target.value })}>{roomCodes.map((room) => <option key={room}>{room}</option>)}</select></label>
        <label className="field-label">Date<input className="input" type="date" min={todayIST()} value={form.booking_date} onChange={(e) => setForm({ ...form, booking_date: e.target.value })} required /></label>
        <div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">{availabilityLoading ? 'Checking live schedule…' : availabilityError ? `Availability check failed: ${availabilityError}` : availability ? <><b>{form.room_code} · {form.booking_date}</b><div className="mt-2 flex flex-wrap gap-1">{availability.slots.map((slot) => <span key={slot.start} title={`${slot.start}–${slot.end}: ${slot.status}`} className={`rounded px-1.5 py-1 ${slot.status === 'AVAILABLE' ? 'bg-teal-100 text-teal-900' : slot.status === 'BOOKED' ? 'bg-rose-100 text-rose-900' : slot.status === 'PENDING' ? 'bg-blue-100 text-blue-900' : 'bg-amber-100 text-amber-900'}`}>{toAmPm(slot.start)}</span>)}</div><p className="mt-2">Green available · Red booked · Blue pending · Amber maintenance</p></> : 'Availability unavailable.'}</div>
        <div className="grid grid-cols-2 gap-3"><label className="field-label">Start (IST)<select className="input" value={form.start_time} onChange={(e) => { const start = e.target.value; const nextEnd = endTimes.find((time) => timeToMinutes(time) > timeToMinutes(start) && !overlapsUnavailable(start, time)) || minutesToTime(timeToMinutes(start) + 30); setForm({ ...form, start_time: start, end_time: nextEnd }) }}>{startTimes.map((time) => <option key={time} value={time} disabled={overlapsUnavailable(time, minutesToTime(timeToMinutes(time) + 30))}>{toAmPm(time)}{overlapsUnavailable(time, minutesToTime(timeToMinutes(time) + 30)) ? ' · unavailable' : ''}</option>)}</select></label><label className="field-label">End (IST)<select className="input" value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })}>{endTimes.map((time) => <option key={time} value={time} disabled={overlapsUnavailable(form.start_time, time)}>{toAmPm(time)}{overlapsUnavailable(form.start_time, time) ? ' · unavailable' : ''}</option>)}</select></label></div>
        <p className="-mt-2 text-xs text-slate-500">Times use 30-minute increments. Existing bookings, pending requests, and maintenance windows are loaded from the database and rechecked when you submit.</p>
        <label className="field-label">Purpose<textarea className="input min-h-24" maxLength={500} value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} required /></label><button className="button-primary w-full" disabled={availabilityLoading || Boolean(availabilityError) || !availability || overlapsUnavailable(form.start_time, form.end_time)}>Send for approval</button>
      </form></Panel>
      <Panel title="My booking requests" action={<button className="button-secondary" onClick={load}>Refresh</button>}><div className="divide-y">{requests.length ? requests.map((item) => <article key={item.id} className="flex flex-wrap justify-between gap-3 py-4 text-sm"><div><b>{item.room_code}</b> · {item.booking_date} · {item.start_time}–{item.end_time}<p className="mt-1 text-slate-600">{item.purpose}</p>{item.decision_note && <p className={`mt-2 rounded-md px-3 py-2 text-xs ${item.status === 'REJECTED' ? 'bg-rose-50 text-rose-800' : 'bg-slate-50 text-slate-600'}`}><b>{item.status === 'REJECTED' ? 'Reason for rejection:' : 'Admin note:'}</b> {item.decision_note}</p>}</div><span className="badge">{item.status}</span></article>) : <p className="py-5 text-sm text-slate-500">No requests yet.</p>}</div></Panel>
    </div>
  </div>
}

function toAmPm(value) {
  const [hour, minute] = value.split(':').map(Number)
  return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${hour < 12 ? 'AM' : 'PM'}`
}
