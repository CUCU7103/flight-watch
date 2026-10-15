import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react'

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
  cheapest_tab_krw: number | null
}

type Config = { default_targets_krw: Record<string, number>; max_jobs: number; max_days_ahead: number }

const POLL_MS = 2000
const MAX_NIGHTS = 30

// 판정 그룹은 이 순서로 보여 준다. 알 수 없는 액션은 제외 그룹에 넣는다.
const VERDICTS = [
  { action: 'SEND_URGENT_ALERT', label: '추천', tone: 'pick' },
  { action: 'SAVE_TO_DAILY_DIGEST', label: '검토 필요', tone: 'review' },
  { action: 'DISCARD', label: '제외', tone: 'drop' },
] as const

const STATUS_LABELS: Record<string, string> = {
  ERROR: '오류 — 검색 중 문제가 생겼습니다',
  TIMEOUT: '시간 초과 — 제한 시간 안에 결과를 받지 못했습니다',
  BLOCKED: '차단됨 — 사이트가 검색을 막았습니다',
  INVALID_RESULT: '검증 실패 — 가격과 조건을 확인하지 못했습니다',
}

const WEEKDAYS = '일월화수목금토'

// 'YYYY-MM-DD'를 로컬 자정으로 읽는다(new Date(iso)는 UTC로 읽어 날짜가 밀릴 수 있다).
function parseIsoDate(iso: string): Date {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function addDays(iso: string, days: number): string {
  const date = parseIsoDate(iso)
  date.setDate(date.getDate() + days)
  return date.toLocaleDateString('sv-SE') // YYYY-MM-DD (로컬 시간대)
}

function isoDateAfter(days: number): string {
  return addDays(new Date().toLocaleDateString('sv-SE'), days)
}

function formatShortDate(iso: string): string {
  const date = parseIsoDate(iso)
  return `${date.getMonth() + 1}/${date.getDate()} (${WEEKDAYS[date.getDay()]})`
}

function nightsBetween(departure: string, arrival: string): number {
  return Math.round((parseIsoDate(arrival).getTime() - parseIsoDate(departure).getTime()) / 86_400_000)
}

function won(amount: number): string {
  return `${amount.toLocaleString()}원`
}

function parseCodes(text: string): string[] {
  return text.toUpperCase().split(/[\s,]+/).filter(Boolean)
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

function formatDelta(price: number, target: number): string {
  const difference = price - target
  if (difference === 0) return '목표가와 같음'
  // 반올림하면 0.0%가 되는 차이도 방향은 보이게 최소 0.1%로 표시한다.
  const percent = Math.max((Math.abs(difference) / target) * 100, 0.1).toFixed(1)
  return difference < 0
    ? `목표가보다 ${won(-difference)} 낮음 (−${percent}%)`
    : `목표가보다 ${won(difference)} 높음 (+${percent}%)`
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

const PLANE_PATH =
  'M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z'

function PlaneIcon({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PLANE_PATH} />
    </svg>
  )
}

function Stepper(props: { label: string; unit: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  const { label, unit, value, min, max, onChange } = props
  return (
    <div className="field">
      <span className="sublabel">{label}</span>
      <div className="stepper" role="group" aria-label={label}>
        <button type="button" aria-label={`${label} 줄이기`} disabled={value <= min} onClick={() => onChange(value - 1)}>
          −
        </button>
        <output aria-live="polite">
          {value}
          {unit}
        </output>
        <button type="button" aria-label={`${label} 늘리기`} disabled={value >= max} onClick={() => onChange(value + 1)}>
          +
        </button>
      </div>
    </div>
  )
}

function ResultCard({ row, verdict }: { row: ResultRow; verdict: (typeof VERDICTS)[number] }) {
  const { job, selected } = row
  const problem = row.status !== 'DONE' ? (STATUS_LABELS[row.status] ?? row.status) : !selected && '표시된 항공편이 없습니다'
  return (
    <article className="card">
      <div className="card-body">
        <div className="card-title">
          <span className="code">
            {job.origin} → {job.destination}
          </span>
          <span className={`badge ${verdict.tone}`}>{verdict.label}</span>
          {row.evaluation && <span className="hint">평가 {row.evaluation.deal_quality.toFixed(1)} / 5</span>}
        </div>
        <div className="secondary">
          {formatShortDate(job.departure_date)} – {formatShortDate(job.return_date)} · {nightsBetween(job.departure_date, job.return_date)}박
        </div>
        {selected && (
          <div className="price-line">
            <span className="price">{won(selected.price_krw)}</span>
            <span className={selected.price_krw <= job.target_price_krw ? 'delta under' : 'delta over'}>
              {formatDelta(selected.price_krw, job.target_price_krw)}
            </span>
            <span className="hint">목표가 {won(job.target_price_krw)}</span>
          </div>
        )}
        {problem && (
          <div className="problem">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 8v5M12 16.5v.01" />
            </svg>
            <span>
              {problem}
              {row.error && <span className="hint"> ({row.error})</span>}
            </span>
          </div>
        )}
        {/* Cheapest 탭 가격은 조건을 확인하지 못한 참고값이라 판정에 쓰지 않고 안내만 한다. */}
        {selected && row.cheapest_tab_krw !== null && row.cheapest_tab_krw < selected.price_krw && (
          <div className="hint">Cheapest 탭에는 {won(row.cheapest_tab_krw)}도 있습니다. 경유·수하물 조건이 다를 수 있어요.</div>
        )}
        {row.evaluation_error && <div className="hint">모델 평가에 실패해 코드 규칙으로만 판정했습니다.</div>}
      </div>
      {selected && (
        <a className={`link-button ${verdict.tone}`} href={selected.search_url} target="_blank" rel="noreferrer">
          Google Flights에서 확인
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M7 17 17 7M9 7h8v8" />
          </svg>
        </a>
      )}
    </article>
  )
}

function Results({ results }: { results: ResultRow[] }) {
  const sorted = [...results].sort(byClosenessToTarget)
  const groups = VERDICTS.map((verdict) => ({
    verdict,
    rows: sorted.filter((row) =>
      verdict.tone === 'drop' ? !VERDICTS.some((known) => known.tone !== 'drop' && known.action === row.action) : row.action === verdict.action,
    ),
  }))
  const routes = [...new Set(results.map((row) => row.job.destination))].join(' · ')
  return (
    <>
      <div className="results-head">
        <div className="row-between">
          <h2>결과 {results.length}건</h2>
          {results.length > 0 && (
            <span className="secondary">
              {results[0].job.origin} → {routes}
            </span>
          )}
        </div>
        <div className="pills">
          {groups.map(({ verdict, rows }) => (
            <span key={verdict.tone} className={`badge pill ${verdict.tone}`}>
              {verdict.label} {rows.length}
            </span>
          ))}
        </div>
      </div>
      {groups
        .filter(({ rows }) => rows.length > 0)
        .map(({ verdict, rows }) => (
          <div key={verdict.tone} className="group">
            <h3>{verdict.label}</h3>
            {rows.map((row) => (
              <ResultCard key={`${row.job.destination}-${row.job.departure_date}`} row={row} verdict={verdict} />
            ))}
          </div>
        ))}
      <p className="hint">
        목표가 이하를 먼저, 그다음 목표가에 가까운 순으로 정렬했습니다. 실시간 운임은 변동됩니다. 예약 전에 가격·수하물·일정을 다시 확인하세요.
      </p>
    </>
  )
}

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const [origin, setOrigin] = useState('ICN')
  const [destinationChips, setDestinationChips] = useState<string[]>(['FUK', 'NRT'])
  const [destinationDraft, setDestinationDraft] = useState('')
  const [start, setStart] = useState(isoDateAfter(7))
  const [days, setDays] = useState(5)
  const [nights, setNights] = useState(3)
  const [targetPrice, setTargetPrice] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [scan, setScan] = useState<ScanSummary | null>(null)
  const [results, setResults] = useState<ResultRow[] | null>(null)

  // 칩으로 확정하지 않은 입력도 검색에 포함한다. 백엔드도 목적지를 dict로 중복 제거하므로 화면의 검색 건수와 맞춘다.
  const destinationCodes = [...new Set([...destinationChips, ...parseCodes(destinationDraft)])]
  const defaultTargets = config?.default_targets_krw ?? {}
  const maxJobs = config?.max_jobs ?? 10
  const jobCount = days * destinationCodes.length
  const isOverLimit = jobCount > maxJobs
  // 설정을 받기 전에는 판단하지 않는다(서버가 다시 검증한다).
  const codesWithoutDefault = config === null ? [] : destinationCodes.filter((code) => !(code in defaultTargets))
  const needsTargetPrice = codesWithoutDefault.length > 0
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

  const isRunning = isPolling
  const canSubmit = !isRunning && destinationCodes.length > 0 && !isOverLimit

  function commitDraft() {
    setDestinationChips(destinationCodes)
    setDestinationDraft('')
  }

  function onDestinationKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return
    if (event.key === 'Enter' || event.key === ',' || event.key === ' ') {
      event.preventDefault()
      commitDraft()
    } else if (event.key === 'Backspace' && destinationDraft === '') {
      setDestinationChips((chips) => chips.slice(0, -1))
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setFormError(null)
    commitDraft()
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
      // 이전 결과는 새 검색이 접수된 뒤에만 지운다(요청이 거부되면 이전 결과를 그대로 둔다).
      setResults(null)
      setScan(started)
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <>
      <header className="app-header">
        <div className="container header-row">
          <div className="brand">
            <PlaneIcon size={26} />
            <span>flight-watch</span>
          </div>
          <p className="secondary">Google Flights 왕복 최저가를 찾아 목표가와 비교합니다 · 예약은 하지 않습니다</p>
        </div>
      </header>

      <div className="container layout">
        <form className="panel" onSubmit={submit}>
          <h2>검색 조건</h2>

          <div className="field">
            <label htmlFor="origin">출발 공항</label>
            <input
              id="origin"
              className="input code"
              value={origin}
              onChange={(e) => setOrigin(e.target.value.toUpperCase())}
              required
              maxLength={3}
            />
          </div>

          <div className="field">
            <label htmlFor="destination">도착 공항</label>
            <div className="chips">
              {destinationChips.map((code) => (
                <span key={code} className={code in defaultTargets || config === null ? 'chip' : 'chip needs-target'}>
                  <span className="code">{code}</span>
                  {config && <span className="chip-note">{code in defaultTargets ? `기본 ${won(defaultTargets[code])}` : '목표가 필요'}</span>}
                  <button type="button" aria-label={`${code} 삭제`} onClick={() => setDestinationChips((chips) => chips.filter((chip) => chip !== code))}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                      <path d="M6 6l12 12M18 6 6 18" />
                    </svg>
                  </button>
                </span>
              ))}
              <input
                id="destination"
                value={destinationDraft}
                placeholder="코드 입력 후 Enter"
                onChange={(e) => setDestinationDraft(e.target.value.toUpperCase())}
                onKeyDown={onDestinationKeyDown}
                onBlur={commitDraft}
              />
            </div>
            {config && (
              <p className="hint">{Object.keys(defaultTargets).join('·')} 외 공항을 넣으면 목표가를 직접 입력해야 합니다.</p>
            )}
          </div>

          <fieldset className="field">
            <legend>일정</legend>
            <div className="field">
              <label htmlFor="start" className="sublabel">
                첫 출발일
              </label>
              <input
                id="start"
                type="date"
                className="input"
                value={start}
                // 서버는 가장 늦은 귀국일이 max_days_ahead 이내인지 본다(첫 출발일 + 출발일 수 - 1 + 박 수).
                max={config ? isoDateAfter(config.max_days_ahead - (days - 1) - nights) : undefined}
                onChange={(e) => setStart(e.target.value)}
                required
              />
            </div>
            <div className="two-columns">
              <Stepper label="출발일 범위" unit="일" value={days} min={1} max={maxJobs} onChange={setDays} />
              <Stepper label="머무는 기간" unit="박" value={nights} min={1} max={MAX_NIGHTS} onChange={setNights} />
            </div>
            {start && (
              <div className="date-preview">
                <div className="row-between">
                  <span className="secondary">가는 날</span>
                  <strong>
                    {formatShortDate(start)}
                    {days > 1 && ` ~ ${formatShortDate(addDays(start, days - 1))}`}
                  </strong>
                </div>
                <div className="row-between">
                  <span className="secondary">오는 날</span>
                  <strong>
                    {formatShortDate(addDays(start, nights))}
                    {days > 1 && ` ~ ${formatShortDate(addDays(start, days - 1 + nights))}`}
                  </strong>
                </div>
              </div>
            )}
          </fieldset>

          <div className="field">
            <label htmlFor="target">
              목표가 <span className={needsTargetPrice ? 'required' : 'secondary'}>{needsTargetPrice ? '(필수)' : '(선택)'}</span>
            </label>
            <div className="input with-unit">
              <input
                id="target"
                type="number"
                value={targetPrice}
                min={1}
                step={1}
                required={needsTargetPrice}
                placeholder={needsTargetPrice ? '목표가 입력' : '노선별 기본값 사용'}
                onChange={(e) => setTargetPrice(e.target.value)}
              />
              <span className="secondary">원</span>
            </div>
            {needsTargetPrice ? (
              <p className="hint">{codesWithoutDefault.join('·')} 공항은 기본 목표가가 없어 직접 입력해야 합니다.</p>
            ) : (
              config && (
                <p className="hint">
                  비우면{' '}
                  {Object.entries(defaultTargets)
                    .map(([code, price]) => `${code} ${won(price)}`)
                    .join(' · ')}
                  으로 판정합니다.
                </p>
              )
            )}
          </div>

          <div className="submit-area">
            <div className="row-between">
              <span className="secondary">검색할 조합</span>
              <span>
                <strong className={isOverLimit ? 'job-count over' : 'job-count'}>{jobCount}건</strong>{' '}
                <span className="hint">/ 최대 {maxJobs}건</span>
              </span>
            </div>
            <div className="meter" aria-hidden="true">
              <div className={isOverLimit ? 'over' : undefined} style={{ width: `${Math.min(jobCount / maxJobs, 1) * 100}%` }} />
            </div>
            <p className={isOverLimit ? 'hint warning' : 'hint'}>
              {isOverLimit
                ? `한 번에 ${maxJobs}건까지 검색할 수 있습니다. 공항이나 출발일 범위를 줄여 주세요.`
                : `공항 ${destinationCodes.length}곳 × 출발일 ${days}일. 결과 페이지를 바로 읽지 못하거나 목표가 이하인 표를 평가할 때 유료 모델 API를 호출합니다.`}
            </p>
            <button type="submit" className="primary-button" disabled={!canSubmit}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-3.5-3.5" />
              </svg>
              {isRunning ? '검색 중…' : `${jobCount}건 검색`}
            </button>
            {formError && (
              <p className="error" role="alert">
                {formError}
              </p>
            )}
          </div>
        </form>

        <section className="content">
          {!scan && (
            <div className="empty-state">
              <PlaneIcon size={56} />
              <div>
                <h2>조건을 정하고 검색을 눌러 주세요</h2>
                <p className="secondary">날짜 조합마다 왕복 최저가를 찾아 목표가와 비교해 드립니다.</p>
              </div>
              <ol className="steps">
                <li>
                  <strong>01</strong>공항과 날짜 범위 고르기
                </li>
                <li>
                  <strong>02</strong>조합당 1~2분 검색
                </li>
                <li>
                  <strong>03</strong>추천 표를 Google Flights에서 확인
                </li>
              </ol>
            </div>
          )}

          {isRunning && scan && (
            <>
              <div className="status-panel" role="status">
                <h2>{scan.status === 'queued' ? '검색 대기 중' : `${scan.job_count}건 검색 중`}</h2>
                <div className="progress" aria-hidden="true">
                  <div />
                </div>
                <p className="secondary">조합 하나에 최대 2분까지 걸립니다. 모든 검색이 끝나면 결과를 한 번에 보여 드려요. 이 창을 열어 두세요.</p>
              </div>
              <div className="skeletons" aria-hidden="true">
                <div />
                <div />
                <div />
              </div>
            </>
          )}

          {scan?.status === 'failed' && (
            <div className="status-panel failed" role="alert">
              <h2>검색에 실패했습니다</h2>
              <p className="secondary">{scan.error ?? '알 수 없는 오류'}. 조건을 확인하고 다시 검색해 주세요.</p>
            </div>
          )}

          {results && <Results results={results} />}
        </section>
      </div>
    </>
  )
}
