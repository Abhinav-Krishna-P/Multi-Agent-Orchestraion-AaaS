import { useQuery } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { queryClient } from './queryClient'
import { supabase } from './supabase'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  // undefined while Supabase is still restoring the session, then a session or null.
  const [session, setSession] = useState(undefined)

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session))
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next)
      if (!next) queryClient.clear()
    })
    return () => data.subscription.unsubscribe()
  }, [])

  const userId = session?.user?.id
  const me = useQuery({ queryKey: ['me', userId], queryFn: () => api('/me'), enabled: Boolean(userId) })

  const signInWithGoogle = useCallback(async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.origin },
    })
    if (error) throw error
  }, [])

  const signOut = useCallback(async () => {
    await supabase.auth.signOut({ scope: 'local' })
  }, [])

  const value = useMemo(
    () => ({ session, user: me.data ?? null, loading: session === undefined, signInWithGoogle, signOut }),
    [session, me.data, signInWithGoogle, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react/only-export-components
export function useAuth() {
  return useContext(AuthContext)
}
