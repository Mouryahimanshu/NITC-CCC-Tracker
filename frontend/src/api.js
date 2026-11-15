const defaultApi = typeof window !== 'undefined' && window.location.hostname.endsWith('vercel.app')
  ? 'https://nitc-ccc-tracker.vercel.app/api/v1'
  : '/api/v1'

const API = (import.meta.env.VITE_API_BASE_URL || defaultApi).replace(/\/$/, '')

export async function request(path, { token, ...options } = {}) {
  const url = `${API}${path}`
  let response
  try {
    response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options?.headers,
      },
    })
  } catch (err) {
    throw new Error(`Could not reach backend API (${err.message}). Check network connection.`)
  }
  const data = response.status === 204 ? null : await response.json().catch(() => null)
  if (!response.ok) throw new Error(data?.detail || `Request failed (${response.status})`)
  return data
}

export const roomCodes = ['T1', 'T2', 'T3', 'T4', 'T5', 'T6']
export function todayIST() { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date()) }
export function timeToMinutes(value) { const [hour, minute] = value.split(':').map(Number); return hour * 60 + minute }
export function minutesToTime(minutes) { return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}` }
