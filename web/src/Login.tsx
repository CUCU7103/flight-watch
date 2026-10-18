import { useState, type FormEvent, type ReactNode } from 'react'
import { supabase } from './auth'

// Supabase가 영어로 주는 흔한 오류만 우리말로 바꾼다. 나머지는 원문을 보여 준다.
const AUTH_ERRORS: Record<string, string> = {
  'Invalid login credentials': '이메일 또는 비밀번호가 맞지 않습니다',
  'Email not confirmed': '메일함에서 확인 링크를 먼저 눌러 주세요',
  'New password should be different from the old password.': '이전과 다른 비밀번호를 입력해 주세요',
}

type Message = { text: string; isError: boolean } | null

function AuthPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <header className="topbar">
        <h1>flight-watch</h1>
        <p>Google Flights 왕복 최저가를 날짜별로 찾아 목표가와 비교합니다 · 예약은 하지 않습니다</p>
      </header>
      <main className="auth">
        <div className="panel">
          <h2 className="auth-title">{title}</h2>
          {children}
        </div>
      </main>
    </>
  )
}

function Notice({ message }: { message: Message }) {
  if (!message) return null
  return (
    <p className={message.isError ? 'error' : 'hint'} role={message.isError ? 'alert' : 'status'}>
      {message.text}
    </p>
  )
}

// 초대제라 가입 화면은 없다. 초대 메일 링크로 들어온 뒤 SetPassword에서 비밀번호를 정한다.
export function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState<Message>(null)
  const [isBusy, setIsBusy] = useState(false)

  async function signIn(event: FormEvent) {
    event.preventDefault()
    if (!supabase) return
    setIsBusy(true)
    setMessage(null)
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    setIsBusy(false)
    if (error) setMessage({ text: AUTH_ERRORS[error.message] ?? error.message, isError: true })
  }

  async function sendReset() {
    if (!supabase) return
    if (!email) {
      setMessage({ text: '이메일을 먼저 입력해 주세요', isError: true })
      return
    }
    setIsBusy(true)
    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: window.location.origin })
    setIsBusy(false)
    // 가입 여부를 드러내지 않도록 성공 문구는 같게 둔다.
    setMessage(error ? { text: error.message, isError: true } : { text: `${email}로 비밀번호 재설정 링크를 보냈습니다(회원인 경우)`, isError: false })
  }

  return (
    <AuthPage title="로그인">
      <form className="auth-form" onSubmit={signIn}>
        <p className="hint">초대받은 회원만 사용할 수 있습니다.</p>
        <div className="field">
          <label htmlFor="email">이메일</label>
          <input id="email" className="input" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="password">비밀번호</label>
          <input
            id="password"
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        <Notice message={message} />
        <button type="submit" className="primary-button" disabled={isBusy}>
          로그인
        </button>
        <button type="button" className="link-button" disabled={isBusy} onClick={sendReset}>
          비밀번호를 잊었나요?
        </button>
      </form>
    </AuthPage>
  )
}

// 초대·비밀번호 재설정 링크로 들어오면 세션은 생겼지만 비밀번호가 없거나 바꿔야 한다.
export function SetPassword({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState<Message>(null)
  const [isBusy, setIsBusy] = useState(false)

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!supabase) return
    setIsBusy(true)
    const { error } = await supabase.auth.updateUser({ password })
    setIsBusy(false)
    if (error) setMessage({ text: AUTH_ERRORS[error.message] ?? error.message, isError: true })
    else onDone()
  }

  return (
    <AuthPage title="비밀번호 설정">
      <form className="auth-form" onSubmit={save}>
        <p className="hint">다음부터 이 비밀번호로 로그인합니다.</p>
        <div className="field">
          <label htmlFor="new-password">새 비밀번호</label>
          <input
            id="new-password"
            className="input"
            type="password"
            autoComplete="new-password"
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <span className="hint">8자 이상</span>
        </div>
        <Notice message={message} />
        <button type="submit" className="primary-button" disabled={isBusy}>
          저장하고 시작하기
        </button>
      </form>
    </AuthPage>
  )
}
