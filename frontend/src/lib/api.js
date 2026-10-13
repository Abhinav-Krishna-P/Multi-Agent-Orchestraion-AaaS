import { supabase } from './supabase'

export const API_URL = import.meta.env.VITE_API_URL

export const SESSION_EXPIRED_MESSAGE = 'Your session expired. Sign in again.'
const AUTH_MESSAGE_KEY = 'auth_message'

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message)
    this.status = status
    this.code = code
  }
}

export async function getAccessToken() {
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token ?? null
}

/** Turns a failed response into an ApiError, using the backend's {detail: {code, message}} body. */
export async function errorFromResponse(response) {
  const data = await response.json().catch(() => null)
  const detail = data?.detail
  const readable = detail && typeof detail === 'object' && !Array.isArray(detail)
  return new ApiError(
    response.status,
    readable ? detail.code : 'request_failed',
    (readable && detail.message) || 'Something went wrong. Try again.',
  )
}

/** A 401 means the sign-in is no longer valid: sign out, and tell the landing page why. */
export async function handleUnauthorized() {
  sessionStorage.setItem(AUTH_MESSAGE_KEY, SESSION_EXPIRED_MESSAGE)
  await supabase.auth.signOut({ scope: 'local' })
}

/** Reads (once) the message left for the landing page, if any. */
export function takeAuthMessage() {
  const message = sessionStorage.getItem(AUTH_MESSAGE_KEY)
  sessionStorage.removeItem(AUTH_MESSAGE_KEY)
  return message
}

export async function api(path, { method = 'GET', body } = {}) {
  const token = await getAccessToken()
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let response
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'network', "Can't reach the server. Check your connection and try again.")
  }

  if (response.status === 401) {
    await handleUnauthorized()
    throw new ApiError(401, 'unauthorized', SESSION_EXPIRED_MESSAGE)
  }
  if (!response.ok) throw await errorFromResponse(response)
  if (response.status === 204) return null
  return response.json()
}
