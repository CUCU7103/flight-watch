import { createClient, type Session } from '@supabase/supabase-js'
import { useEffect, useState } from 'react'

const url = import.meta.env.VITE_SUPABASE_URL
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

// 초대·비밀번호 재설정 메일 링크로 들어왔는지. supabase-js가 주소의 토큰을 지우기 전에 읽어야 한다.
export const arrivedToSetPassword = /[#&]type=(invite|recovery)\b/.test(window.location.hash)

// 두 값이 없으면 로그인 없이 로컬 백엔드(loopback 전용)에 붙는 개발 모드다.
export const supabase = url && key ? createClient(url, key) : null

// API 요청에 붙일 액세스 토큰. getSession()이 만료가 가까우면 갱신해서 돌려준다.
export async function accessToken(): Promise<string | null> {
  if (!supabase) return null
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token ?? null
}

// undefined: 아직 확인 중, null: 로그인 안 됨.
export function useSession(): Session | null | undefined {
  const [session, setSession] = useState<Session | null | undefined>(supabase ? undefined : null)
  useEffect(() => {
    if (!supabase) return
    supabase.auth.getSession().then(({ data }) => setSession(data.session))
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next))
    return () => data.subscription.unsubscribe()
  }, [])
  return session
}
