CREATE OR REPLACE VIEW soc_service_analytics AS
SELECT b.source_name,b.grain,b.bucket_utc,b.service_key,
       COALESCE(l.display_name,'Servicio '||LEFT(b.service_key,10)) AS service,
       b.total_events,b.success_count,b.failure_count,b.lockout_count,
       b.distinct_users,b.distinct_ips,
       100.0*b.failure_count/NULLIF(b.total_events,0) AS failure_rate
FROM soc_service_buckets b LEFT JOIN service_labels l USING(relying_party);
CREATE OR REPLACE VIEW soc_service_hour_dashboard AS
SELECT * FROM soc_service_analytics WHERE grain='hour';
CREATE OR REPLACE VIEW soc_service_day_dashboard AS
SELECT * FROM soc_service_analytics WHERE grain='day';
CREATE OR REPLACE VIEW soc_analytics_policy_view AS SELECT * FROM soc_analytics_policy;
CREATE OR REPLACE VIEW soc_analytics_alerts AS
SELECT a.source_name,soc_service_key(s.service) AS service_key,a.alert_id,
       a.occurred_at_utc::timestamptz AS starts_at,a.last_seen_local::timestamptz AS ends_at,
       a.investigation_status,a.severity,a.risk_score,
       COALESCE(l.display_name,'Servicio '||LEFT(soc_service_key(s.service),10)) AS service
FROM alerts a JOIN alert_services s USING(alert_id)
LEFT JOIN service_labels l ON l.relying_party=s.service;
CREATE INDEX IF NOT EXISTS idx_alert_service_key ON alert_services(soc_service_key(service),alert_id);

CREATE OR REPLACE FUNCTION soc_service_oscillations(
    p_source text,p_key text,p_from timestamptz,p_to timestamptz,p_grain text
) RETURNS TABLE(
    bucket_utc timestamptz,service text,service_key text,
    total_events bigint,success_count bigint,failure_count bigint,lockout_count bigint,
    distinct_users bigint,distinct_ips bigint,failure_rate numeric,
    previous_events bigint,change_percent numeric,baseline_expected numeric,
    baseline_samples bigint,deviation_percent numeric,alert_count bigint,open_alert_count bigint,
    bucket_end timestamptz,partial_bucket boolean
) LANGUAGE plpgsql STABLE AS $$
DECLARE p record; start_at timestamptz; stop_at timestamptz; step interval;
BEGIN
    SELECT * INTO p FROM soc_analytics_policy_view WHERE singleton=1;
    IF p_grain NOT IN ('hour','day') OR p_from IS NULL OR p_to IS NULL
       OR p_to<=p_from OR p_to-p_from>make_interval(days=>p.max_range_days) THEN
        RAISE EXCEPTION 'Seleccione hora/dia y un intervalo positivo de hasta % dias',p.max_range_days;
    END IF;
    IF COALESCE(p_key,'') !~ '^[a-f0-9]{64}$' THEN RETURN; END IF;
    step:=CASE WHEN p_grain='hour' THEN interval '1 hour' ELSE interval '1 day' END;
    start_at:=date_trunc(p_grain,p_from AT TIME ZONE p.timezone) AT TIME ZONE p.timezone;
    stop_at:=date_trunc(p_grain,p_to AT TIME ZONE p.timezone) AT TIME ZONE p.timezone;
    IF stop_at<p_to THEN stop_at:=stop_at+step; END IF;
    RETURN QUERY
    WITH complete_days AS (
        -- Misma exigencia de completitud que config/baseline.json, por fuente.
        SELECT (h.bucket_utc AT TIME ZONE p.timezone)::date AS day
        FROM soc_service_hour_dashboard h
        WHERE h.source_name=p_source AND h.bucket_utc>=p.training_start
          AND h.bucket_utc<LEAST(p.training_end,start_at)
        GROUP BY 1 HAVING SUM(h.total_events)>=p.minimum_day_events
          AND COUNT(DISTINCT EXTRACT(hour FROM h.bucket_utc AT TIME ZONE p.timezone))>=p.minimum_day_hours
    ), training AS (
        SELECT h.* FROM soc_service_analytics h
        WHERE h.source_name=p_source AND h.service_key=p_key AND h.grain=p_grain
          AND h.bucket_utc>=p.training_start AND h.bucket_utc+step<=LEAST(p.training_end,start_at)
          AND (h.bucket_utc AT TIME ZONE p.timezone)::date IN (SELECT day FROM complete_days)
    )
    SELECT c.bucket_utc,c.service,c.service_key,c.total_events,c.success_count,c.failure_count,c.lockout_count,
           c.distinct_users,c.distinct_ips,c.failure_rate,
           prev.total_events,100.0*(c.total_events-prev.total_events)/NULLIF(prev.total_events,0),
           CASE WHEN base.n>=p.minimum_samples THEN base.expected END,base.n,
           CASE WHEN base.n>=p.minimum_samples THEN
               100.0*(c.total_events-base.expected)/NULLIF(base.expected,0) END,
           cases.total,cases.open,c.bucket_utc+step,c.bucket_utc+step>CURRENT_TIMESTAMP
    FROM soc_service_analytics c
    LEFT JOIN soc_service_analytics prev ON prev.source_name=c.source_name
      AND prev.service_key=c.service_key AND prev.grain=c.grain
      AND prev.bucket_utc=c.bucket_utc-(stop_at-start_at)
    LEFT JOIN LATERAL (
        SELECT COUNT(*) AS n,AVG(t.total_events) AS expected FROM training t
        WHERE p_grain='day' OR
          EXTRACT(hour FROM t.bucket_utc AT TIME ZONE p.timezone)=
          EXTRACT(hour FROM c.bucket_utc AT TIME ZONE p.timezone)
    ) base ON true
    LEFT JOIN LATERAL (
        SELECT COUNT(*) AS total,COUNT(*) FILTER(
            WHERE a.investigation_status IN ('new','notified','investigating')) AS open
        FROM soc_analytics_alerts a WHERE a.source_name=c.source_name AND a.service_key=c.service_key
          AND a.starts_at<c.bucket_utc+step AND a.ends_at>=c.bucket_utc
    ) cases ON true
    WHERE c.source_name=p_source AND c.service_key=p_key AND c.grain=p_grain
      AND c.bucket_utc>=start_at AND c.bucket_utc<stop_at
    ORDER BY c.bucket_utc;
END;
$$;
REVOKE ALL ON FUNCTION soc_service_oscillations(text,text,timestamptz,timestamptz,text) FROM PUBLIC;

-- No expone usuarios, IP ni cadenas de conexión. Cero filas nuevas no significa fallo.
CREATE OR REPLACE VIEW soc_monitor_health AS
SELECT DISTINCT ON (source_name) source_name,started_at_utc::timestamptz AS started_at,
       finished_at_utc::timestamptz AS finished_at,status,fetched_count,
       inserted_event_count,alert_count
FROM service_runs ORDER BY source_name,run_id DESC;

CREATE OR REPLACE FUNCTION soc_services_overview(
    p_source text,p_keys text[],p_from timestamptz,p_to timestamptz,p_grain text
) RETURNS TABLE(
    bucket_utc timestamptz,service text,service_key text,
    total_events bigint,success_count bigint,failure_count bigint,lockout_count bigint,
    failure_rate numeric,alert_count bigint,open_alert_count bigint,critical_open_count bigint,
    high_open_count bigint,bucket_end timestamptz
) LANGUAGE plpgsql STABLE AS $$
DECLARE p record; start_at timestamptz; stop_at timestamptz; step interval;
BEGIN
    SELECT * INTO p FROM soc_analytics_policy_view WHERE singleton=1;
    IF p_grain NOT IN ('hour','day') OR p_from IS NULL OR p_to IS NULL
       OR p_to<=p_from OR p_to-p_from>make_interval(days=>p.max_range_days) THEN
        RAISE EXCEPTION 'Seleccione hora/dia y un intervalo positivo de hasta % dias',p.max_range_days;
    END IF;
    IF COALESCE(cardinality(p_keys),0)=0 THEN RETURN; END IF;
    step:=CASE WHEN p_grain='hour' THEN interval '1 hour' ELSE interval '1 day' END;
    start_at:=date_trunc(p_grain,p_from AT TIME ZONE p.timezone) AT TIME ZONE p.timezone;
    stop_at:=date_trunc(p_grain,p_to AT TIME ZONE p.timezone) AT TIME ZONE p.timezone;
    IF stop_at<p_to THEN stop_at:=stop_at+step; END IF;
    RETURN QUERY
    WITH selected AS (
        SELECT c.bucket_utc,c.service,c.service_key,c.total_events,c.success_count,
               c.failure_count,c.lockout_count,c.failure_rate
        FROM soc_service_analytics c WHERE c.source_name=p_source
          AND c.grain=p_grain AND c.bucket_utc>=start_at AND c.bucket_utc<stop_at
          AND ('__all'=ANY(p_keys) OR c.service_key=ANY(p_keys))
    ), cases AS (
        -- Cada caso se cuenta una vez por servicio en el final de su evidencia.
        -- Puede estar asociado a varios servicios: sus totales no se suman globalmente.
        SELECT date_trunc(p_grain,a.ends_at AT TIME ZONE p.timezone) AT TIME ZONE p.timezone AS t,
               a.service_key AS k,MAX(a.service) AS name,COUNT(DISTINCT a.alert_id) AS total,
               COUNT(DISTINCT a.alert_id) FILTER(WHERE a.investigation_status IN ('new','notified','investigating')) AS open,
               COUNT(DISTINCT a.alert_id) FILTER(WHERE a.investigation_status IN ('new','notified','investigating') AND a.severity='critical') AS critical,
               COUNT(DISTINCT a.alert_id) FILTER(WHERE a.investigation_status IN ('new','notified','investigating') AND a.severity='high') AS high
        FROM soc_analytics_alerts a WHERE a.source_name=p_source AND a.ends_at>=p_from AND a.ends_at<p_to
          AND ('__all'=ANY(p_keys) OR a.service_key=ANY(p_keys)) GROUP BY 1,2
    )
    SELECT COALESCE(c.bucket_utc,a.t),COALESCE(c.service,a.name),COALESCE(c.service_key,a.k),
           c.total_events,c.success_count,c.failure_count,c.lockout_count,c.failure_rate,
           COALESCE(a.total,0),COALESCE(a.open,0),COALESCE(a.critical,0),COALESCE(a.high,0),
           COALESCE(c.bucket_utc,a.t)+step
    FROM selected c FULL JOIN cases a ON a.t=c.bucket_utc AND a.k=c.service_key
    ORDER BY 1,2;
END;
$$;
REVOKE ALL ON FUNCTION soc_services_overview(text,text[],timestamptz,timestamptz,text) FROM PUBLIC;
