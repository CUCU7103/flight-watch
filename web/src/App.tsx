import { useEffect, useState, type FormEvent } from 'react'

// 백엔드 API 계약(backend/src/flight_scanner/api.py)과 맞춘 타입.
type ScanSummary = {
  id: string
  status: 'queued' | 'running' | 'done' | 'failed'
  job_count: number
  error: string | null
}

type ResultRow = {
  job: { origin: string; destination: string; departure_date: string; return_date: string; target_price_krw: number }
  status: string
  error: string | null
  action: string
  selected?: { price_krw: number; search_url: string }
  evaluation?: { deal_quality: number }
  evaluation_error?: string
}

const POLL_MS = 2000
const DEFAULT_DESTINATIONS = ['FUK', 'NRT']

const ACTION_LABELS: Record<string, string> = {
  SEND_URGENT_ALERT: '추천',
  SAVE_TO_DAILY_DIGEST: '검토 필요',
  DISCARD: '제외',
}

const STATUS_LABELS: Record<string, string> = {
  DONE: '완료',
  ERROR: '오류',
  TIMEOUT: '시간 초과',
  BLOCKED: '차단됨',
  INVALID_RESULT: '검증 실패',
}

function isoDateAfter(days: number): string {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date.toLocaleDateString('sv-SE') // YYYY-MM-DD (로컬 시간대)
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    // HTTPException은 문자열 detail, 요청 형식 오류(pydantic)는 배열 detail을 준다.
    throw new Error(typeof body.detail === 'string' ? body.detail : `요청이 거부되었습니다 (HTTP ${response.status})`)
  }
  return body as T
}

export default function App() {
  const [origin, setOrigin] = useState('ICN')
  const [destinations, setDestinations] = useState(DEFAULT_DESTINATIONS.join(' '))
  const [start, setStart] = useState(isoDateAfter(7))
  const [days, setDays] = useState(5)
  const [nights, setNights] = useState(3)
  const [targetPrice, setTargetPrice] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [scan, setScan] = useState<ScanSummary | null>(null)
  const [results, setResults] = useState<ResultRow[] | null>(null)

  const destinationCodes = destinations.toUpperCase().split(/[\s,]+/).filter(Boolean)
  const needsTargetPrice = destinationCodes.some((code) => !DEFAULT_DESTINATIONS.includes(code))
  const isRunning = scan?.status === 'queued' || scan?.status === 'running'

  useEffect(() => {
    if (!scan || !isRunning) return
    const timer = setInterval(async () => {
      try {
        const next = await requestJson<ScanSummary>(`/api/scans/${scan.id}`)
        setScan(next)
        if (next.status === 'done') {
          const body = await requestJson<{ results: ResultRow[] }>(`/api/scans/${scan.id}/results`)
          setResults(body.results)
        }
      } catch {
        // 일시적인 연결 오류는 다음 폴링에서 다시 시도한다.
      }
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [scan, isRunning])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setFormError(null)
    setResults(null)
    try {
      const started = await requestJson<ScanSummary>('/api/scans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          origin,
          destinations: destinationCodes,
          start,
          days,
          nights,
          target_price_krw: targetPrice ? Number(targetPrice) : null,
        }),
      })
      setScan(started)
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <main>
      <h1>flight-watch</h1>
      <p className="muted">왕복 항공권 최저가를 Google Flights에서 검색합니다. 예약은 하지 않습니다.</p>

      <form onSubmit={submit}>
        <label>
          출발 공항
          <input value={origin} onChange={(e) => setOrigin(e.target.value)} required maxLength={3} />
        </label>
        <label>
          도착 공항 (공백으로 구분)
          <input value={destinations} onChange={(e) => setDestinations(e.target.value)} required />
        </label>
        <label>
          첫 출발일
          <input type="date" value={start} min={isoDateAfter(1)} onChange={(e) => setStart(e.target.value)} required />
        </label>
        <label>
          출발일 수
          <input type="number" value={days} min={1} max={10} onChange={(e) => setDays(Number(e.target.value))} />
        </label>
        <label>
          박 수
          <input type="number" value={nights} min={1} max={30} onChange={(e) => setNights(Number(e.target.value))} />
        </label>
        <label>
          목표가 (원){needsTargetPrice ? ' — FUK/NRT 외 노선은 필수' : ' — 비우면 FUK 180,000 / NRT 250,000'}
          <input
            type="number"
            value={targetPrice}
            min={1}
            required={needsTargetPrice}
            onChange={(e) => setTargetPrice(e.target.value)}
          />
        </label>
        <p className="muted">
          검색 {days * destinationCodes.length}건 (최대 10건). 검색마다 유료 모델 API를 호출합니다.
        </p>
        <button type="submit" disabled={isRunning}>
          {isRunning ? '검색 중…' : '검색'}
        </button>
        {formError && <p className="error">{formError}</p>}
      </form>

      {scan && (
        <section>
          <h2>진행 상태</h2>
          <p>
            {scan.status === 'queued' && '대기 중'}
            {scan.status === 'running' && `검색 중 — ${scan.job_count}건, 건당 최대 2분 걸릴 수 있습니다`}
            {scan.status === 'done' && `완료 — ${scan.job_count}건`}
            {scan.status === 'failed' && <span className="error">실패 ({scan.error})</span>}
          </p>
        </section>
      )}

      {results && (
        <section>
          <h2>결과</h2>
          <table>
            <thead>
              <tr>
                <th>노선</th>
                <th>일정</th>
                <th>상태</th>
                <th>최저가</th>
                <th>목표가</th>
                <th>판정</th>
                <th>링크</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row) => (
                <tr key={`${row.job.destination}-${row.job.departure_date}`}>
                  <td>
                    {row.job.origin} → {row.job.destination}
                  </td>
                  <td>
                    {row.job.departure_date} ~ {row.job.return_date}
                  </td>
                  <td>
                    {STATUS_LABELS[row.status] ?? row.status}
                    {row.error && <span className="muted"> ({row.error})</span>}
                  </td>
                  <td>{row.selected ? `${row.selected.price_krw.toLocaleString()}원` : '—'}</td>
                  <td>{row.job.target_price_krw.toLocaleString()}원</td>
                  <td>
                    {ACTION_LABELS[row.action] ?? row.action}
                    {row.evaluation && <span className="muted"> ({row.evaluation.deal_quality.toFixed(1)}/5)</span>}
                    {row.evaluation_error && <span className="muted"> (평가 실패)</span>}
                  </td>
                  <td>
                    {row.selected && (
                      <a href={row.selected.search_url} target="_blank" rel="noreferrer">
                        Google Flights
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">실시간 운임은 변동됩니다. 예약 전 가격·수하물·일정을 다시 확인하세요.</p>
        </section>
      )}
    </main>
  )
}
