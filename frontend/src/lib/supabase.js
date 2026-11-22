import { createClient } from '@supabase/supabase-js'

// Supabase is used only for Google sign-in. All app data comes from our own backend.
export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
)
