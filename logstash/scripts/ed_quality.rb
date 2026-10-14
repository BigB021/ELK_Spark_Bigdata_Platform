# =============================================================================
#  ed_quality.rb - data-quality rules of the ed-visits pipeline
#  (strategy documented in docs/anomaly_strategy.md)
#
#  Input : event after csv / translate / date filters
#  Output: typed + normalised event with
#            dq.status             valid | warning | rejected
#            dq.issues             ["out_of_range:heart_rate_bpm=-72", ...]
#            dq.anomaly_categories ["invalid_numeric", ...]
#            [@metadata][route]    "valid" (valid + warning) | "reject"
#
#  Severity policy
#    REJECT  : missing record_id / stay_id / arrival_datetime, unparseable or
#              future arrival date, departure before arrival, duplicate stay_id,
#              CSV parse failure
#    WARNING : record indexed, faulty field removed (null) or corrected, issue logged
#  The `test` blocks at the end run when the pipeline starts.
# =============================================================================
require 'time'

def register(params)
  @columns = %w[
    record_id patient_id stay_id arrival_datetime departure_datetime length_of_stay_hours
    gender age_years race_ethnicity arrival_transport triage_acuity_esi chief_complaint
    temperature_f heart_rate_bpm resp_rate_bpm spo2_pct systolic_bp_mmhg diastolic_bp_mmhg
    pain_score_0_10 primary_diagnosis_icd10 primary_diagnosis_title
    medication_reconciliation_count disposition admitted_flag
  ]
  @run_id        = params.fetch('run_id', 'main').to_s
  @max_los_hours = params.fetch('max_los_hours', 72).to_f
  @los_tolerance = params.fetch('los_tolerance_hours', 0.1).to_f

  # field => [min, max, type]  (clinically plausible bounds)
  @ranges = {
    'age_years'                       => [0, 120, :int],
    'temperature_f'                   => [90.0, 110.0, :float],
    'heart_rate_bpm'                  => [20, 250, :int],
    'resp_rate_bpm'                   => [4, 60, :int],
    'spo2_pct'                        => [50, 100, :int],
    'systolic_bp_mmhg'                => [50, 260, :int],
    'diastolic_bp_mmhg'               => [20, 160, :int],
    'pain_score_0_10'                 => [0, 10, :int],
    'medication_reconciliation_count' => [0, 60, :int]
  }
  @categorical = %w[gender race_ethnicity arrival_transport disposition]
  @critical    = %w[record_id stay_id arrival_datetime]
  @icd10_re    = /\A[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?\z/
  @ddmm_re     = %r{\A\d{2}/\d{2}/\d{4}}
  @dows        = %w[7-SUN 1-MON 2-TUE 3-WED 4-THU 5-FRI 6-SAT]

  # Process-wide state shared by all pipeline workers (duplicate detection)
  $ed_dq_lock ||= Mutex.new
  $ed_dq_seen ||= {}
end

def filter(event)
  issues  = []
  cats    = []
  rejects = []
  add = lambda { |cat, msg, reject = false|
    cats << cat unless cats.include?(cat)
    issues << msg
    rejects << msg if reject
  }

  if (event.get('tags') || []).include?('_csvparsefailure')
    add.call('parse_error', 'csv_parse_failure', true)
  end

  # ---- 1. missing fields -----------------------------------------------------
  @columns.each do |f|
    v = event.get(f)
    next unless v.nil? || (v.is_a?(String) && v.empty?)
    event.remove(f)
    add.call('missing_field', "missing:#{f}", @critical.include?(f))
  end

  # ---- 2. dates ----------------------------------------------------------------
  orig = event.get('[@metadata][original]') || {}
  now  = Time.now.utc
  arr  = check_date(event, 'arrival_datetime', orig, now, add, true)
  dep  = check_date(event, 'departure_datetime', orig, now, add, false)
  if arr && dep && dep < arr
    add.call('inconsistency', 'departure_before_arrival', true)
  end

  # ---- 3. numeric fields: type + plausible range --------------------------------
  @ranges.each do |f, (min, max, type)|
    raw = event.get(f)
    next if raw.nil?
    num = to_number(raw, type)
    if num.nil?
      event.remove(f)
      add.call('invalid_numeric', "not_numeric:#{f}=#{raw}")
    elsif num < min || num > max
      event.remove(f)
      add.call('invalid_numeric', "out_of_range:#{f}=#{raw}")
    else
      event.set(f, num)
    end
  end

  # ---- 4. length of stay: recomputed from the dates -----------------------------
  los_raw = event.get('length_of_stay_hours')
  los     = los_raw.nil? ? nil : to_number(los_raw, :float)
  if !los_raw.nil? && (los.nil? || los < 0)
    add.call('invalid_numeric', "invalid:length_of_stay_hours=#{los_raw}")
    los = nil
  end
  if arr && dep && dep >= arr
    computed = ((dep - arr) / 3600.0).round(2)
    event.set('los_computed_hours', computed)
    if los && (los - computed).abs > @los_tolerance
      add.call('inconsistency', "los_mismatch:declared=#{los_raw},computed=#{computed}")
    end
    los = computed
  end
  if los
    event.set('length_of_stay_hours', los)
    add.call('outlier', "los_over_#{@max_los_hours.to_i}h=#{los}") if los > @max_los_hours
  else
    event.remove('length_of_stay_hours')
  end

  # ---- 5. categories ------------------------------------------------------------
  @categorical.each do |f|
    v = event.get(f)
    next if v.nil?
    norm = event.get("[@metadata][norm][#{f}]")
    if norm.nil? || norm == '__INVALID__'
      event.set(f, 'UNKNOWN')
      add.call('unknown_category', "unknown_category:#{f}=#{v}")
    else
      event.set(f, norm)
    end
  end

  esi_raw = event.get('triage_acuity_esi')
  unless esi_raw.nil?
    esi = to_number(esi_raw, :int)
    if esi && esi.between?(1, 5)
      event.set('triage_acuity_esi', esi)
    else
      event.remove('triage_acuity_esi')
      add.call('unknown_category', "unknown_category:triage_acuity_esi=#{esi_raw}")
    end
  end

  icd = event.get('primary_diagnosis_icd10')
  if icd
    if icd =~ @icd10_re
      event.set('icd10_chapter', icd[0])
    else
      event.remove('primary_diagnosis_icd10')
      add.call('unknown_category', "invalid_code:primary_diagnosis_icd10=#{icd}")
    end
  end

  # ---- 6. admitted_flag must agree with disposition -----------------------------
  flag_raw = event.get('admitted_flag')
  flag = case flag_raw when 'true' then true when 'false' then false end
  if !flag_raw.nil? && flag.nil?
    add.call('unknown_category', "unknown_category:admitted_flag=#{flag_raw}")
  end
  disp = event.get('disposition')
  if disp && disp != 'UNKNOWN'
    derived = (disp == 'ADMITTED')
    if !flag.nil? && flag != derived
      add.call('inconsistency', "admitted_flag_mismatch:flag=#{flag},disposition=#{disp}")
    end
    flag = derived
  end
  flag.nil? ? event.remove('admitted_flag') : event.set('admitted_flag', flag)

  # ---- 7. duplicates (same stay_id already seen in this run) --------------------
  stay = event.get('stay_id')
  if stay && rejects.empty?
    first = $ed_dq_lock.synchronize { $ed_dq_seen.key?("#{@run_id}|#{stay}") ? false : ($ed_dq_seen["#{@run_id}|#{stay}"] = true) }
    add.call('duplicate', "duplicate:stay_id=#{stay}", true) unless first
  end

  # ---- 8. derived fields --------------------------------------------------------
  derive(event, arr)

  # ---- 9. status & routing ------------------------------------------------------
  status = rejects.any? ? 'rejected' : (issues.any? ? 'warning' : 'valid')
  event.set('[dq][status]', status)
  event.set('[dq][issues]', issues)
  event.set('[dq][issue_count]', issues.size)
  event.set('[dq][anomaly_categories]', cats)
  event.set('[ingest][ingested_at]', LogStash::Timestamp.new(now))

  if status == 'rejected'
    build_reject(event, orig, rejects, now)
  else
    event.set('[@metadata][route]', 'valid')
    event.set('@timestamp', LogStash::Timestamp.new(arr))
  end
  [event]
end

# Returns a Time, or nil (field removed) ; records anomalies.
def check_date(event, field, orig, now, add, critical)
  v = event.get(field)
  return nil if v.nil?
  if v.is_a?(LogStash::Timestamp)
    t = v.time.utc
    if t > now
      event.remove(field)
      add.call('invalid_date', "future_date:#{field}=#{orig[field]}", critical)
      return nil
    end
    if orig[field].is_a?(String) && orig[field] =~ @ddmm_re
      add.call('format_variant', "date_format_normalized:#{field}=#{orig[field]}")
    end
    t
  else
    event.remove(field)
    add.call('invalid_date', "invalid_date:#{field}=#{v}", critical)
    nil
  end
end

def to_number(v, type)
  return v if v.is_a?(Numeric) && type == :float
  f = Float(v.to_s.strip)
  return nil if f.nan? || f.infinite?
  type == :int ? f.round : f.round(2)
rescue ArgumentError, TypeError
  nil
end

def derive(event, arr)
  age = event.get('age_years')
  if age.is_a?(Numeric)
    event.set('age_group', case age
                           when 0..17  then '0-17'
                           when 18..34 then '18-34'
                           when 35..49 then '35-49'
                           when 50..64 then '50-64'
                           when 65..79 then '65-79'
                           else '80+'
                           end)
  end
  if arr
    event.set('arrival_hour', arr.hour)
    event.set('arrival_dow', @dows[arr.wday])
    event.set('arrival_month', arr.strftime('%Y-%m'))
  end
  esi = event.get('triage_acuity_esi')
  event.set('is_high_acuity', esi <= 2) if esi.is_a?(Numeric)
  temp = event.get('temperature_f')
  event.set('fever_flag', temp >= 100.4) if temp.is_a?(Numeric)
  hr, sbp = event.get('heart_rate_bpm'), event.get('systolic_bp_mmhg')
  event.set('shock_index', (hr.to_f / sbp).round(2)) if hr.is_a?(Numeric) && sbp.is_a?(Numeric) && sbp > 0
end

# Rejected event: business fields moved to `original` (stored, not indexed)
def build_reject(event, orig, rejects, now)
  raw = event.get('[@metadata][raw_line]')
  (@columns + %w[icd10_chapter age_group arrival_hour arrival_dow arrival_month
                   los_computed_hours is_high_acuity fever_flag shock_index message host]).each { |f| event.remove(f) }
  %w[record_id stay_id patient_id].each { |f| event.set(f, orig[f]) if orig[f] }
  event.set('original', orig)
  event.set('raw_line', raw)
  event.set('reject_reasons', rejects)
  event.set('@timestamp', LogStash::Timestamp.new(now))
  # occurrence counter => identical lines still get distinct _ids in ed-rejects-*
  n = $ed_dq_lock.synchronize { $ed_dq_seen["#{@run_id}|raw|#{raw}"] = ($ed_dq_seen["#{@run_id}|raw|#{raw}"] || 0) + 1 }
  event.set('[@metadata][reject_key]', "#{raw}##{n}")
  event.set('[@metadata][route]', 'reject')
end

# =============================================================================
#  Unit tests (executed by Logstash at pipeline start-up)
#  `test` blocks run in a separate TestContext: helpers are global lambdas.
# =============================================================================
$ed_ts = lambda { |s| LogStash::Timestamp.new(Time.parse(s + ' UTC')) }

$ed_base_event = lambda do |extra = {}|
  ts = $ed_ts
  {
    'record_id' => 'T1', 'patient_id' => 'P1', 'stay_id' => "S-#{rand(1_000_000_000)}",
    'arrival_datetime' => ts.call('2025-03-01 10:00:00'), 'departure_datetime' => ts.call('2025-03-01 13:00:00'),
    'length_of_stay_hours' => '3.0', 'gender' => 'F', 'age_years' => '40', 'race_ethnicity' => 'WHITE',
    'arrival_transport' => 'AMBULANCE', 'triage_acuity_esi' => '2', 'chief_complaint' => 'Chest pain',
    'temperature_f' => '98.6', 'heart_rate_bpm' => '80', 'resp_rate_bpm' => '16', 'spo2_pct' => '98',
    'systolic_bp_mmhg' => '120', 'diastolic_bp_mmhg' => '80', 'pain_score_0_10' => '5',
    'primary_diagnosis_icd10' => 'R07.9', 'primary_diagnosis_title' => 'Chest pain, unspecified',
    'medication_reconciliation_count' => '3', 'disposition' => 'HOME', 'admitted_flag' => 'false',
    '@metadata' => { 'norm' => { 'gender' => 'F', 'race_ethnicity' => 'WHITE',
                                 'arrival_transport' => 'AMBULANCE', 'disposition' => 'HOME' },
                     'raw_line' => 'T1,...', 'original' => {} }
  }.merge(extra)
end

test 'clean record is valid and typed' do
  parameters { { 'run_id' => 'unittest' } }
  in_event { $ed_base_event.call }
  expect('status valid')   { |e| e.first.get('[dq][status]') == 'valid' }
  expect('route valid')    { |e| e.first.get('[@metadata][route]') == 'valid' }
  expect('typed integer')  { |e| e.first.get('heart_rate_bpm') == 80 }
  expect('derived fields') { |e| e.first.get('is_high_acuity') == true && e.first.get('los_computed_hours') == 3.0 }
end

test 'out-of-range vital is removed, record kept as warning' do
  parameters { { 'run_id' => 'unittest' } }
  in_event { $ed_base_event.call('heart_rate_bpm' => '-72') }
  expect('warning')    { |e| e.first.get('[dq][status]') == 'warning' }
  expect('hr removed') { |e| e.first.get('heart_rate_bpm').nil? }
  expect('category')   { |e| e.first.get('[dq][anomaly_categories]').include?('invalid_numeric') }
end

test 'unknown category becomes UNKNOWN' do
  parameters { { 'run_id' => 'unittest' } }
  in_event { $ed_base_event.call('arrival_transport' => 'TELEPORT',
                        '@metadata' => { 'norm' => { 'arrival_transport' => '__INVALID__', 'gender' => 'F',
                                                     'race_ethnicity' => 'WHITE', 'disposition' => 'HOME' } }) }
  expect('UNKNOWN') { |e| e.first.get('arrival_transport') == 'UNKNOWN' }
  expect('issue')   { |e| e.first.get('[dq][issues]').include?('unknown_category:arrival_transport=TELEPORT') }
end

test 'invalid arrival date is rejected' do
  parameters { { 'run_id' => 'unittest' } }
  in_event { $ed_base_event.call('arrival_datetime' => '2025-02-30 10:12:00') }
  expect('rejected') { |e| e.first.get('[dq][status]') == 'rejected' }
  expect('route')    { |e| e.first.get('[@metadata][route]') == 'reject' }
  expect('reason')   { |e| e.first.get('reject_reasons').include?('invalid_date:arrival_datetime=2025-02-30 10:12:00') }
end

test 'missing stay_id is rejected' do
  parameters { { 'run_id' => 'unittest' } }
  in_event { $ed_base_event.call('stay_id' => nil) }
  expect('rejected') { |e| e.first.get('reject_reasons').include?('missing:stay_id') }
end

test 'departure before arrival is rejected' do
  parameters { { 'run_id' => 'unittest' } }
  in_event { $ed_base_event.call('departure_datetime' => $ed_ts.call('2025-03-01 08:00:00')) }
  expect('rejected') { |e| e.first.get('reject_reasons').include?('departure_before_arrival') }
end

test 'admitted_flag is corrected from disposition' do
  parameters { { 'run_id' => 'unittest' } }
  in_event { $ed_base_event.call('admitted_flag' => 'true') }
  expect('corrected') { |e| e.first.get('admitted_flag') == false }
  expect('warning')   { |e| e.first.get('[dq][anomaly_categories]').include?('inconsistency') }
end
