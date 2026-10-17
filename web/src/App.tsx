import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent } from 'react'

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
  selected?: {
    price_krw: number
    search_url: string
    return_verified: boolean
    baggage_known: boolean
    max_layover_hours: number | null
    airport_change: boolean | null
  }
  evaluation?: { deal_quality: number }
  evaluation_error?: string
  cheapest_tab_krw: number | null
}

type Config = { default_targets_krw: Record<string, number>; max_jobs: number; max_days_ahead: number }

const POLL_MS = 2000
const MAX_NIGHTS = 30

// 판정은 색이 아니라 인쇄 표식으로 구분한다: 추천=채움, 검토 필요=윤곽, 제외=취소선.
// 알 수 없는 액션은 제외로 본다.
const VERDICTS = [
  { action: 'SEND_URGENT_ALERT', label: '추천', tone: 'pick' },
  { action: 'SAVE_TO_DAILY_DIGEST', label: '검토 필요', tone: 'review' },
  { action: 'DISCARD', label: '제외', tone: 'drop' },
] as const

type Verdict = (typeof VERDICTS)[number]

const STATUS_LABELS: Record<string, string> = {
  ERROR: '오류 — 검색 중 문제가 생겼습니다',
  TIMEOUT: '시간 초과 — 제한 시간 안에 결과를 받지 못했습니다',
  BLOCKED: '차단됨 — 사이트가 검색을 막았습니다',
  INVALID_RESULT: '검증 실패 — 가격과 조건을 확인하지 못했습니다',
}

// 좁은 달력 칸에 한 줄로 들어가는 문제 표기
const SHORT_STATUS_LABELS: Record<string, string> = {
  ERROR: '오류',
  TIMEOUT: '초과',
  BLOCKED: '차단',
  INVALID_RESULT: '실패',
}

const WEEKDAYS = '일월화수목금토'

// 'YYYY-MM-DD'를 로컬 자정으로 읽는다(new Date(iso)는 UTC로 읽어 날짜가 밀릴 수 있다).
function parseIsoDate(iso: string): Date {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function toIsoDate(date: Date): string {
  return date.toLocaleDateString('sv-SE') // YYYY-MM-DD (로컬 시간대)
}

function addDays(iso: string, days: number): string {
  const date = parseIsoDate(iso)
  date.setDate(date.getDate() + days)
  return toIsoDate(date)
}

function isoDateAfter(days: number): string {
  return addDays(toIsoDate(new Date()), days)
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

// 좁은 달력 칸용 표기: 252,400 → 25.2만
function manwon(amount: number): string {
  return `${(amount / 10_000).toFixed(1).replace(/\.0$/, '')}만`
}

function parseCodes(text: string): string[] {
  return text.toUpperCase().split(/[\s,]+/).filter(Boolean)
}

function verdictOf(row: ResultRow): Verdict {
  return VERDICTS.find((verdict) => verdict.tone !== 'drop' && verdict.action === row.action) ?? VERDICTS[2]
}

function rowId(row: ResultRow): string {
  return `fare-${row.job.destination}-${row.job.departure_date}`
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

// 코드가 확인한 항공권 조건. 목표가와 상관없이 모든 행에 보여 준다.
// 가는 편은 확인된 항공권만 결과에 남으므로 오는 편만 따로 표시한다.
function conditionsOf(selected: NonNullable<ResultRow['selected']>): string {
  const minutes = selected.max_layover_hours === null ? null : Math.round(selected.max_layover_hours * 60)
  const layover =
    minutes === null
      ? '경유 미확인'
      : minutes === 0
        ? '직항'
        : `최대 경유 ${Math.floor(minutes / 60)}시간${minutes % 60 ? ` ${minutes % 60}분` : ''}`
  return [
    selected.return_verified ? '왕복 일정 확인' : '오는 편 미확인',
    selected.baggage_known ? '위탁 수하물 포함' : '수하물 미확인',
    layover,
    ...(selected.airport_change === false ? [] : [selected.airport_change ? '공항 변경 있음' : '공항 변경 미확인']),
  ].join(' · ')
}

// 결과 행의 문제를 한 줄로. 정상 결과면 null.
function problemOf(row: ResultRow): string | null {
  if (row.status !== 'DONE') return STATUS_LABELS[row.status] ?? row.status
  return row.selected ? null : '표시된 항공편이 없습니다'
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

// 달력에 그릴 내용. fares가 없으면 아직 가격이 없는 검색 범위 미리보기다.
type Fare = { id: string; route: string; tone: Verdict['tone'] | 'problem'; label: string; shortLabel: string; price: number | null }
// returns는 오는 날 → 그 일정의 가는 날. 같은 일정은 같은 색으로 묶는다.
type CalendarPlan = { departures: Set<string>; returns: Map<string, string>; fares: Map<string, Fare[]> | null }

const TRIP_COLOR_COUNT = 6

function rangePlan(start: string, days: number, nights: number): CalendarPlan {
  const departures = Array.from({ length: days }, (_, index) => addDays(start, index))
  return { departures: new Set(departures), returns: new Map(departures.map((date) => [addDays(date, nights), date])), fares: null }
}

function resultPlan(results: ResultRow[]): CalendarPlan {
  const fares = new Map<string, Fare[]>()
  for (const row of results) {
    const verdict = verdictOf(row)
    const problem = problemOf(row)
    const fare: Fare = {
      id: rowId(row),
      route: row.job.destination,
      tone: problem ? 'problem' : verdict.tone,
      // 칸에는 문제의 앞부분(예: '검증 실패')만 적는다.
      label: problem ? problem.split(' — ')[0] : verdict.label,
      shortLabel: row.status !== 'DONE' ? (SHORT_STATUS_LABELS[row.status] ?? '오류') : row.selected ? verdict.label : '없음',
      price: row.selected?.price_krw ?? null,
    }
    fares.set(row.job.departure_date, [...(fares.get(row.job.departure_date) ?? []), fare])
  }
  return {
    departures: new Set(results.map((row) => row.job.departure_date)),
    returns: new Map(results.map((row) => [row.job.return_date, row.job.departure_date])),
    fares,
  }
}

function Stepper(props: { label: string; unit: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  const { label, unit, value, min, max, onChange } = props
  return (
    <div className="field">
      <span className="sublabel">{label}</span>
      <div className="stepper" role="group" aria-label={label}>
        <button type="button" aria-label={`${label} 줄이기`} disabled={value <= min} onClick={() => onChange(value - 1)}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M5 12h14" />
          </svg>
        </button>
        <output aria-live="polite">
          {value}
          {unit}
        </output>
        <button type="button" aria-label={`${label} 늘리기`} disabled={value >= max} onClick={() => onChange(value + 1)}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M5 12h14M12 5v14" />
          </svg>
        </button>
      </div>
    </div>
  )
}

// 출발일 칸에 적는 오는 날. 달이 바뀌면 월도 적는다.
function returnLabel(departure: string, returnDate: string) {
  const [, month, day] = returnDate.split('-').map(Number)
  return returnDate.slice(0, 7) === departure.slice(0, 7) ? { wide: `${day}일`, narrow: `${day}` } : { wide: `${month}월 ${day}일`, narrow: `${month}/${day}` }
}

type MonthProps = {
  month: string
  plan: CalendarPlan
  focusRoute: string | null
  // 가리킨 일정의 가는 날. 이 일정만 진하게 두고 나머지 표시는 흐린다.
  activeTrip: string | null
  onActiveTripChange: (trip: string | null) => void
}

function Month({ month, plan, focusRoute, activeTrip, onActiveTripChange }: MonthProps) {
  const [year, monthNumber] = month.split('-').map(Number)
  const offset = new Date(year, monthNumber - 1, 1).getDay()
  const dayCount = new Date(year, monthNumber, 0).getDate()
  const departureOrder = [...plan.departures].sort()
  const returnOf = new Map([...plan.returns].map(([returnDate, departure]) => [departure, returnDate]))
  return (
    <section className="month" aria-label={`${year}년 ${monthNumber}월`}>
      <div className="month-head">
        <span className="month-number">{monthNumber}</span>
        <span className="month-label">
          {year}년 {monthNumber}월
        </span>
      </div>
      <div className="weekdays" aria-hidden="true">
        {[...WEEKDAYS].map((weekday, index) => (
          <span key={weekday} className={index === 0 ? 'sun' : index === 6 ? 'sat' : undefined}>
            {weekday}
          </span>
        ))}
      </div>
      <ol className="days">
        {Array.from({ length: offset }, (_, index) => (
          <li key={`blank-${index}`} className="blank" aria-hidden="true" />
        ))}
        {Array.from({ length: dayCount }, (_, index) => {
          const day = index + 1
          const iso = `${month}-${String(day).padStart(2, '0')}`
          const weekday = (offset + index) % 7
          const isDeparture = plan.departures.has(iso)
          const isReturn = plan.returns.has(iso)
          const classes = ['day', weekday === 0 && 'sun', weekday === 6 && 'sat', isDeparture && 'is-departure', isReturn && 'is-return']
          const fares = plan.fares?.get(iso) ?? []
          const order = departureOrder.indexOf(iso)
          const returnOrder = isReturn ? departureOrder.indexOf(plan.returns.get(iso) ?? '') : -1
          const style = {
            ...(isDeparture && { '--order': order, '--departure-color': `var(--trip-${order % TRIP_COLOR_COUNT})` }),
            ...(isReturn && { '--return-color': `var(--trip-${returnOrder % TRIP_COLOR_COUNT})` }),
          } as CSSProperties
          // 가는 날이면서 다른 일정의 오는 날인 칸은 가는 날 일정을 대표로 삼는다.
          const trip = isDeparture ? iso : (plan.returns.get(iso) ?? null)
          const returnDate = returnOf.get(iso)
          const label = isDeparture && returnDate ? returnLabel(iso, returnDate) : null
          return (
            <li
              key={iso}
              className={classes.filter(Boolean).join(' ')}
              style={style}
              data-dim-departure={activeTrip !== null && isDeparture && iso !== activeTrip ? true : undefined}
              data-dim-return={activeTrip !== null && isReturn && plan.returns.get(iso) !== activeTrip ? true : undefined}
              // 마우스는 가리키는 동안, 터치는 탭한 칸이 바뀔 때까지 유지한다.
              onPointerEnter={(event) => event.pointerType === 'mouse' && onActiveTripChange(trip)}
              onPointerLeave={(event) => event.pointerType === 'mouse' && onActiveTripChange(null)}
              onClick={() => onActiveTripChange(trip)}
              onFocus={() => onActiveTripChange(trip)}
              onBlur={() => onActiveTripChange(null)}
            >
              <span className="day-number">
                {day}
                {(isDeparture || isReturn) && (
                  <span className="sr-only">
                    일{isDeparture && ' 가는 날'}
                    {isReturn && ' 오는 날'}
                  </span>
                )}
              </span>
              {label && (
                <span className="trip-return">
                  <span className="sr-only">오는 날 </span>
                  <span className="wide" aria-hidden="true">→ {label.wide}</span>
                  <span className="narrow" aria-hidden="true">→{label.narrow}</span>
                  <span className="sr-only">{label.wide}</span>
                </span>
              )}
              {fares.map((fare) => (
                <a
                  key={fare.id}
                  href={`#${fare.id}`}
                  className={`fare ${fare.tone}`}
                  data-dim={focusRoute !== null && focusRoute !== fare.route ? true : undefined}
                >
                  <span className="fare-route">{fare.route}</span>
                  {fare.price === null ? (
                    <span className="fare-price">
                      <span className="wide">{fare.label}</span>
                      <span className="narrow">{fare.shortLabel}</span>
                    </span>
                  ) : (
                    <span className="fare-price">
                      <span className="wide">{won(fare.price)}</span>
                      <span className="narrow">{manwon(fare.price)}</span>
                      <span className="sr-only"> {fare.label}</span>
                    </span>
                  )}
                </a>
              ))}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function Calendar({ plan, focusRoute }: { plan: CalendarPlan; focusRoute: string | null }) {
  const [activeTrip, setActiveTrip] = useState<string | null>(null)
  // 검색 범위가 바뀌어 사라진 일정은 무시한다.
  const visibleTrip = activeTrip !== null && plan.departures.has(activeTrip) ? activeTrip : null
  // 가격은 출발일 칸에 적히므로 출발일이 걸친 달만 그린다.
  const months = [...new Set([...plan.departures].map((date) => date.slice(0, 7)))].sort()
  return (
    <div className="months">
      {months.map((month) => (
        <Month key={month} month={month} plan={plan} focusRoute={focusRoute} activeTrip={visibleTrip} onActiveTripChange={setActiveTrip} />
      ))}
    </div>
  )
}

// 같은 노선·날짜·성인 1명·일반석의 네이버 항공권 검색 결과 주소.
// ponytail: 국제선 경로만 만든다. 국내선(GMP-CJU 등)을 검색하게 되면 /flights/domestic/ 경로가 필요하다.
function naverSearchUrl(job: ResultRow['job']) {
  const compact = (date: string) => date.replaceAll('-', '')
  return `https://flight.naver.com/flights/international/${job.origin}-${job.destination}-${compact(job.departure_date)}/${job.destination}-${job.origin}-${compact(job.return_date)}?adult=1&fareType=Y`
}

function ResultRowView({ row }: { row: ResultRow }) {
  const { job, selected } = row
  const verdict = verdictOf(row)
  const problem = problemOf(row)
  const isUnderTarget = selected !== undefined && selected.price_krw <= job.target_price_krw
  return (
    <li id={rowId(row)} className={`row ${verdict.tone}`}>
      <div className="row-route">
        <strong>
          {job.origin} → {job.destination}
        </strong>
        <span className={`mark ${verdict.tone}`}>{verdict.label}</span>
      </div>
      <div className="row-dates">
        <span className="date-range">
          {formatShortDate(job.departure_date)} – {formatShortDate(job.return_date)}
        </span>
        <span className="secondary">
          {nightsBetween(job.departure_date, job.return_date)}박
          {row.evaluation && ` · 평가 ${row.evaluation.deal_quality.toFixed(1)} / 5`}
        </span>
      </div>
      {selected ? (
        <div className="row-price">
          <span className="price">{won(selected.price_krw)}</span>
          {/* 막대 길이 = 가격 ÷ 목표가. 가운데 눈금이 목표가, 목표가의 2배에서 자른다. */}
          <span className={isUnderTarget ? 'delta-bar under' : 'delta-bar over'} aria-hidden="true">
            <span style={{ width: `${Math.min(selected.price_krw / job.target_price_krw, 2) * 50}%` }} />
          </span>
          <span className={isUnderTarget ? 'delta under' : 'delta over'}>{formatDelta(selected.price_krw, job.target_price_krw)}</span>
          <span className="secondary">목표가 {won(job.target_price_krw)}</span>
          <span className="secondary">{conditionsOf(selected)}</span>
        </div>
      ) : (
        <div className="row-price" />
      )}
      <div className="row-links">
        {selected && (
          <a className={`link-button ${verdict.tone}`} href={selected.search_url} target="_blank" rel="noreferrer">
            Google Flights에서 확인
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M7 17 17 7M9 7h8v8" />
            </svg>
          </a>
        )}
        {/* 네이버는 수집하지 않고(robots.txt·봇 차단) 같은 조건의 검색 결과를 직접 열어 비교만 한다. */}
        <a className="link-button" href={naverSearchUrl(job)} target="_blank" rel="noreferrer">
          네이버에서 보기
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M7 17 17 7M9 7h8v8" />
            </svg>
        </a>
      </div>
      {(problem || row.evaluation_error || (selected && row.cheapest_tab_krw !== null && row.cheapest_tab_krw < selected.price_krw)) && (
        <div className="row-notes">
          {problem && (
            <p className="problem">
              {problem}
              {row.error && <span className="secondary"> ({row.error})</span>}
            </p>
          )}
          {/* Cheapest 탭 가격은 조건을 확인하지 못한 참고값이라 판정에 쓰지 않고 안내만 한다. */}
          {selected && row.cheapest_tab_krw !== null && row.cheapest_tab_krw < selected.price_krw && (
            <p className="secondary">Cheapest 탭에는 {won(row.cheapest_tab_krw)}도 있습니다. 경유·수하물 조건이 다를 수 있어요.</p>
          )}
          {row.evaluation_error && <p className="secondary">모델 평가에 실패해 코드 규칙으로만 판정했습니다.</p>}
        </div>
      )}
    </li>
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
  // 검색 중에는 폼을 바꿔도 달력이 실제로 검색하는 범위를 보여 주도록 제출한 값을 따로 둔다.
  const [submittedPlan, setSubmittedPlan] = useState<CalendarPlan | null>(null)
  const [results, setResults] = useState<ResultRow[] | null>(null)
  const [focusRoute, setFocusRoute] = useState<string | null>(null)
  const boardTitleRef = useRef<HTMLHeadingElement>(null)

  // 칩으로 확정하지 않은 입력도 검색에 포함한다. 백엔드도 목적지를 dict로 중복 제거하므로 화면의 검색 건수와 맞춘다.
  const destinationCodes = [...new Set([...destinationChips, ...parseCodes(destinationDraft)])]
  const defaultTargets = config?.default_targets_krw ?? {}
  const maxJobs = config?.max_jobs ?? 30
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

  // 결과나 실패가 도착했는데 달력이 화면 아래쪽에 있으면(좁은 화면) 달력으로 옮기고 제목에 포커스를 준다.
  const hasSettled = results !== null || scan?.status === 'failed'
  useEffect(() => {
    const title = boardTitleRef.current
    if (!hasSettled || !title) return
    if (title.getBoundingClientRect().top > window.innerHeight / 2) title.scrollIntoView({ block: 'start' })
    title.focus({ preventScroll: true })
  }, [hasSettled])

  const isRunning = isPolling
  const canSubmit = !isRunning && destinationCodes.length > 0 && !isOverLimit
  const plan = results ? resultPlan(results) : isRunning ? submittedPlan : start ? rangePlan(start, days, nights) : null
  const resultRoutes = results ? [...new Set(results.map((row) => row.job.destination))] : []
  const visibleRows = results ? [...results].sort(byClosenessToTarget).filter((row) => focusRoute === null || row.job.destination === focusRoute) : []

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
      setFocusRoute(null)
      setSubmittedPlan(rangePlan(start, days, nights))
      setScan(started)
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <>
      <header className="topbar">
        <h1>flight-watch</h1>
        <p>Google Flights 왕복 최저가를 날짜별로 찾아 목표가와 비교합니다 · 예약은 하지 않습니다</p>
      </header>

      <main className="workspace">
        <form id="search" className="panel" onSubmit={submit}>
          <h2 className="sr-only">검색 조건</h2>

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
                  {config && !(code in defaultTargets) && <span className="chip-note">목표가 필요</span>}
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
              <dl className="date-preview">
                <dt>가는 날</dt>
                <dd>
                  {formatShortDate(start)}
                  {days > 1 && ` ~ ${formatShortDate(addDays(start, days - 1))}`}
                </dd>
                <dt>오는 날</dt>
                <dd>
                  {formatShortDate(addDays(start, nights))}
                  {days > 1 && ` ~ ${formatShortDate(addDays(start, days - 1 + nights))}`}
                </dd>
              </dl>
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
            <div className="budget-head">
              <span>검색할 조합</span>
              <span>
                <strong className={isOverLimit ? 'job-count over' : 'job-count'}>{jobCount}</strong>
                <span className="secondary"> / {maxJobs}건</span>
              </span>
            </div>
            {/* 한 번에 검색할 수 있는 칸 수가 정해져 있다. 조합이 칸을 채우고, 넘치면 모두 빨갛게. */}
            <div className={isOverLimit ? 'slots over' : 'slots'} aria-hidden="true">
              {Array.from({ length: maxJobs }, (_, index) => (
                <i key={index} className={index < jobCount ? 'on' : undefined} />
              ))}
            </div>
            {isOverLimit && (
              <p className="hint warning">한 번에 {maxJobs}건까지 검색할 수 있습니다. 공항이나 출발일 범위를 줄여 주세요.</p>
            )}
            <button type="submit" className="primary-button" disabled={!canSubmit}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-3.5-3.5" />
              </svg>
              {isRunning ? '검색 중…' : `${jobCount}건 검색`}
            </button>
            {!isOverLimit && (
              <p className="hint">
                공항 {destinationCodes.length}곳 × 출발일 {days}일. 대부분 결과 페이지를 바로 읽어 모델을 부르지 않습니다. 바로 읽지 못하면 Jev(유료)가 검색 폼을 조작하고, 목표가 이하이면서 수하물까지 모든 조건이 확인된 표만 Jev가 한 번 더 평가합니다.
              </p>
            )}
            {formError && (
              <p className="error" role="alert">
                {formError}
              </p>
            )}
          </div>
        </form>

        <section className={isRunning ? 'board is-searching' : 'board'} aria-labelledby="board-title" aria-busy={isRunning}>
          <div className="board-head">
            <div className="board-title">
              <h2 id="board-title" ref={boardTitleRef} tabIndex={-1}>
                {results
                  ? `결과 ${results.length}건`
                  : isRunning && scan
                    ? scan.status === 'queued'
                      ? '검색 대기 중'
                      : `${scan.job_count}건 검색 중`
                    : '출발일 달력'}
              </h2>
              {results ? (
                <p className="counts">
                  {VERDICTS.map((verdict) => (
                    <span key={verdict.tone}>
                      <span className={`mark ${verdict.tone}`}>{verdict.label}</span> {results.filter((row) => verdictOf(row) === verdict).length}
                    </span>
                  ))}
                </p>
              ) : (
                <p className="secondary" role={isRunning ? 'status' : undefined}>
                  {isRunning
                    ? '조합 하나에 최대 2분까지 걸립니다. 모든 검색이 끝나면 칸마다 가격이 한 번에 적힙니다. 이 창을 열어 두세요.'
                    : '검색하면 출발일 칸마다 노선별 왕복 최저가가 적힙니다.'}
                </p>
              )}
            </div>
            <div className="legend" aria-hidden="true">
              <span>
                <i className="key-departure" /> 가는 날
              </span>
              <span>
                <i className="key-return" /> 오는 날
              </span>
              <span>같은 색끼리 한 일정</span>
            </div>
          </div>

          {isRunning && (
            <div className="progress" aria-hidden="true">
              <div />
            </div>
          )}

          {scan?.status === 'failed' && (
            <div className="failed" role="alert">
              <h3>검색에 실패했습니다</h3>
              <p>{scan.error ?? '알 수 없는 오류'}. 조건을 확인하고 다시 검색해 주세요.</p>
            </div>
          )}

          {resultRoutes.length > 1 && (
            <div className="route-filter" role="group" aria-label="노선 골라 보기">
              {[null, ...resultRoutes].map((route) => (
                <button key={route ?? 'all'} type="button" aria-pressed={focusRoute === route} onClick={() => setFocusRoute(route)}>
                  {route ?? '전체'}
                </button>
              ))}
            </div>
          )}

          {plan ? <Calendar plan={plan} focusRoute={focusRoute} /> : <p className="secondary">첫 출발일을 고르면 달력에 검색 범위가 표시됩니다.</p>}
        </section>

        {results && (
          <section className="details" aria-labelledby="details-title">
            <h2 id="details-title">목표가에 가까운 순</h2>
            <ol className="rows">
              {visibleRows.map((row) => (
                <ResultRowView key={rowId(row)} row={row} />
              ))}
            </ol>
            <p className="secondary">
              목표가 이하를 먼저, 그다음 목표가에 가까운 순으로 정렬했습니다. 실시간 운임은 변동됩니다. 예약 전에 가격·수하물·일정을 다시 확인하세요.
            </p>
          </section>
        )}
      </main>
    </>
  )
}
