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

type Config = { default_targets_krw: Record<string, number>; max_jobs: number }

const POLL_MS = 2000

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

// 목표가 대비 초과율. 음수면 목표가 이하다. 가격이 없으면 null.
function overTargetRatio(row: ResultRow): number | null {
  return row.selected ? row.selected.price_krw / row.job.target_price_krw - 1 : null
}

// 목표가 이하를 먼저, 그다음 목표가에 가까운 순으로 정렬한다. 가격이 없는 행은 맨 뒤.
function byClosenessToTarget(a: ResultRow, b: ResultRow): number {
  const ratioA = overTargetRatio(a)
  const ratioB = overTargetRatio(b)
  if (ratioA === null || ratioB === null) return ratioA === null ? (ratioB === null ? 0 : 1) : -1
  return ratioA - ratioB
}

function formatRatio(ratio: number): string {
  const percent = Math.round(Math.abs(ratio) * 100)
  return ratio <= 0 ? `목표가 이하 (−${percent}%)` : `+${percent}%`
}

class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    // HTTPException은 문자열 detail, 요청 형식 오류(pydantic)는 배열 detail을 준다.
    const message = typeof body.detail === 'string' ? body.detail : body.detail?.[0]?.msg
    throw new ApiError(message ?? `요청이 거부되었습니다 (HTTP ${response.status})`, response.status)
  }
  return body as T
}

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const [origin, setOrigin] = useState('ICN')
  const [destinations, setDestinations] = useState('FUK NRT')
  const [start, setStart] = useState(isoDateAfter(7))
  const [days, setDays] = useState(5)
  const [nights, setNights] = useState(3)
  const [targetPrice, setTargetPrice] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [scan, setScan] = useState<ScanSummary | null>(null)
  const [results, setResults] = useState<ResultRow[] | null>(null)

  // 백엔드도 목적지를 dict로 중복 제거하므로 화면의 검색 건수와 맞춘다.
  const destinationCodes = [...new Set(destinations.toUpperCase().split(/[\s,]+/).filter(Boolean))]
  const defaultTargets = config?.default_targets_krw ?? {}
  // 설정을 받기 전에는 판단하지 않는다(서버가 다시 검증한다).
  const needsTargetPrice = config !== null && destinationCodes.some((code) => !(code in defaultTargets))
  // 결과를 받기 전까지는 done이어도 폴링을 계속한다(결과 조회가 한 번 실패해도 다시 시도).
  const isPolling = scan !== null && scan.status !== 'failed' && results === null
  const scanId = scan?.id

  useEffect(() => {
    requestJson<Config>('/api/config')
      .then(setConfig)
      .catch(() => {
        // 설정이 없어도 검색은 가능하다. 안내 문구만 일반화된다.
      })
  }, [])

  useEffect(() => {
    if (!scanId || !isPolling) return
    let cancelled = false
    const timer = setInterval(async () => {
      try {
        const next = await requestJson<ScanSummary>(`/api/scans/${scanId}`)
        if (next.status === 'done') {
          const body = await requestJson<{ results: ResultRow[] }>(`/api/scans/${scanId}/results`)
          if (cancelled) return
          setResults(body.results)
        }
        if (!cancelled) setScan(next)
      } catch (error) {
        if (cancelled) return
        if (error instanceof ApiError && error.status === 404) {
          // 서버가 재시작되면 메모리의 검색 기록이 사라진다. 폴링을 멈추고 새 검색을 받을 수 있게 한다.
          setScan((current) => current && { ...current, status: 'failed', error: '서버가 다시 시작되어 검색 기록이 사라졌습니다' })
        }
        // 그 밖의 일시적인 연결 오류는 다음 폴링에서 다시 시도한다.
      }
    }, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [scanId, isPolling])

  const isRunning = scan?.status === 'queued' || scan?.status === 'running'

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
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
        </label>
        <label>
          출발일 수
          <input type="number" value={days} min={1} max={config?.max_jobs ?? 10} onChange={(e) => setDays(Number(e.target.value))} />
        </label>
        <label>
          박 수
          <input type="number" value={nights} min={1} max={30} onChange={(e) => setNights(Number(e.target.value))} />
        </label>
        <label>
          목표가 (원)
          {needsTargetPrice
            ? ` — ${Object.keys(defaultTargets).join('/')} 외 노선은 필수`
            : config &&
              ` — 비우면 ${Object.entries(defaultTargets)
                .map(([code, price]) => `${code} ${price.toLocaleString()}`)
                .join(' / ')}`}
          <input
            type="number"
            value={targetPrice}
            min={1}
            step={1}
            required={needsTargetPrice}
            onChange={(e) => setTargetPrice(e.target.value)}
          />
        </label>
        <p className="muted">
          검색 {days * destinationCodes.length}건 (최대 {config?.max_jobs ?? 10}건). 결과 페이지를 바로 확인하지 못했거나
          목표가 이하인 표를 평가할 때 유료 모델 API를 호출합니다.
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
            {scan.status === 'running' && `검색 중 — ${scan.job_count}건`}
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
                <th>목표가 대비</th>
                <th>판정</th>
                <th>링크</th>
              </tr>
            </thead>
            <tbody>
              {[...results].sort(byClosenessToTarget).map((row) => {
                const ratio = overTargetRatio(row)
                return (
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
                    <td className={ratio !== null && ratio <= 0 ? 'good' : undefined}>
                      {ratio === null ? '—' : formatRatio(ratio)}
                    </td>
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
                )
              })}
            </tbody>
          </table>
          <p className="muted">
            목표가 이하인 표를 먼저, 그다음 목표가에 가까운 순으로 정렬했습니다. 실시간 운임은 변동됩니다. 예약 전 가격·수하물·일정을 다시 확인하세요.
          </p>
        </section>
      )}
    </main>
  )
}
