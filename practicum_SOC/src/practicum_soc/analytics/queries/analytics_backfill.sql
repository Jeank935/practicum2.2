-- Instalación inicial únicamente. No borra ni modifica eventos/casos.
INSERT INTO soc_service_buckets
SELECT e.source_name,g.grain,
       date_trunc(g.grain,e.event_time_utc::timestamptz AT TIME ZONE p.timezone) AT TIME ZONE p.timezone,
       e.relying_party,soc_service_key(e.relying_party),SUM(e.event_count),
       SUM(CASE WHEN e.event_class='success' THEN e.event_count ELSE 0 END),
       SUM(CASE WHEN e.event_class='failure' THEN e.event_count ELSE 0 END),
       SUM(CASE WHEN e.event_class='lockout' THEN e.event_count ELSE 0 END),
       COUNT(DISTINCT NULLIF(e.user_key,'')),COUNT(DISTINCT NULLIF(e.client_ip_key,''))
FROM normalized_events e CROSS JOIN (VALUES('hour'),('day')) g(grain)
CROSS JOIN soc_analytics_policy p
WHERE e.is_consistent=1 AND COALESCE(e.event_time_utc,'')<>''
  AND TRIM(COALESCE(e.relying_party,''))<>''
GROUP BY 1,2,3,4,5;
INSERT INTO soc_bucket_entities
SELECT e.source_name,g.grain,
       date_trunc(g.grain,e.event_time_utc::timestamptz AT TIME ZONE p.timezone) AT TIME ZONE p.timezone,
       e.relying_party,k.kind,
       CASE WHEN k.kind='user' THEN e.user_key ELSE e.client_ip_key END,COUNT(*)
FROM normalized_events e CROSS JOIN (VALUES('hour'),('day')) g(grain)
CROSS JOIN (VALUES('user'),('ip')) k(kind) CROSS JOIN soc_analytics_policy p
WHERE e.is_consistent=1 AND COALESCE(e.event_time_utc,'')<>''
  AND TRIM(COALESCE(e.relying_party,''))<>''
  AND COALESCE(CASE WHEN k.kind='user' THEN e.user_key ELSE e.client_ip_key END,'')<>''
GROUP BY 1,2,3,4,5,6;
