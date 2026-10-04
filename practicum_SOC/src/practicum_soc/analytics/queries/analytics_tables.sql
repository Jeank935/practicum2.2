CREATE TABLE IF NOT EXISTS soc_analytics_migrations(version integer PRIMARY KEY);
CREATE TABLE IF NOT EXISTS soc_analytics_policy(
    singleton integer PRIMARY KEY CHECK(singleton=1), timezone text NOT NULL,
    training_start timestamptz NOT NULL, training_end timestamptz NOT NULL,
    max_range_days integer NOT NULL, minimum_samples integer NOT NULL,
    minimum_day_events integer NOT NULL, minimum_day_hours integer NOT NULL
);
CREATE OR REPLACE FUNCTION soc_service_key(identifier text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
AS $$ SELECT encode(sha256(convert_to(identifier, 'UTF8')), 'hex') $$;

CREATE TABLE IF NOT EXISTS soc_service_buckets(
    source_name text NOT NULL, grain text NOT NULL CHECK(grain IN ('hour','day')),
    bucket_utc timestamptz NOT NULL, relying_party text NOT NULL,
    service_key text NOT NULL,
    total_events bigint NOT NULL, success_count bigint NOT NULL,
    failure_count bigint NOT NULL, lockout_count bigint NOT NULL,
    distinct_users bigint NOT NULL DEFAULT 0, distinct_ips bigint NOT NULL DEFAULT 0,
    PRIMARY KEY(source_name, grain, bucket_utc, relying_party)
);
CREATE INDEX IF NOT EXISTS idx_analytics_lookup
    ON soc_service_buckets(source_name, service_key, grain, bucket_utc);
CREATE TABLE IF NOT EXISTS soc_bucket_entities(
    source_name text NOT NULL, grain text NOT NULL, bucket_utc timestamptz NOT NULL,
    relying_party text NOT NULL, kind text NOT NULL, entity_key text NOT NULL,
    refs bigint NOT NULL CHECK(refs>=0),
    PRIMARY KEY(source_name, grain, bucket_utc, relying_party, kind, entity_key)
);
CREATE OR REPLACE FUNCTION soc_apply_analytics(item normalized_events, delta integer)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    g text; t timestamptz; z text; k text; entity text; remaining bigint; change integer;
BEGIN
    IF item.is_consistent <> 1 OR COALESCE(item.event_time_utc,'') = ''
       OR TRIM(COALESCE(item.relying_party,'')) = '' THEN RETURN; END IF;
    SELECT timezone INTO z FROM soc_analytics_policy WHERE singleton=1;
    FOREACH g IN ARRAY ARRAY['hour','day'] LOOP
        t := date_trunc(g, item.event_time_utc::timestamptz AT TIME ZONE z) AT TIME ZONE z;
        INSERT INTO soc_service_buckets(
            source_name,grain,bucket_utc,relying_party,service_key,total_events,
            success_count,failure_count,lockout_count
        ) VALUES (
            item.source_name,g,t,item.relying_party,soc_service_key(item.relying_party),
            delta*item.event_count,
            delta*CASE WHEN item.event_class='success' THEN item.event_count ELSE 0 END,
            delta*CASE WHEN item.event_class='failure' THEN item.event_count ELSE 0 END,
            delta*CASE WHEN item.event_class='lockout' THEN item.event_count ELSE 0 END
        ) ON CONFLICT(source_name,grain,bucket_utc,relying_party) DO UPDATE SET
            total_events=soc_service_buckets.total_events+excluded.total_events,
            success_count=soc_service_buckets.success_count+excluded.success_count,
            failure_count=soc_service_buckets.failure_count+excluded.failure_count,
            lockout_count=soc_service_buckets.lockout_count+excluded.lockout_count;
        -- El bloqueo del bucket serializa las referencias y conserva distintos exactos.
        FOREACH k IN ARRAY ARRAY['user','ip'] LOOP
            entity := CASE WHEN k='user' THEN item.user_key ELSE item.client_ip_key END;
            IF COALESCE(entity,'')='' THEN CONTINUE; END IF;
            change := 0;
            IF delta=1 THEN
                INSERT INTO soc_bucket_entities VALUES(item.source_name,g,t,item.relying_party,k,entity,1)
                ON CONFLICT(source_name,grain,bucket_utc,relying_party,kind,entity_key)
                DO UPDATE SET refs=soc_bucket_entities.refs+1 RETURNING refs INTO remaining;
                IF remaining=1 THEN change:=1; END IF;
            ELSE
                UPDATE soc_bucket_entities SET refs=refs-1
                WHERE source_name=item.source_name AND grain=g AND bucket_utc=t
                  AND relying_party=item.relying_party AND kind=k AND entity_key=entity
                RETURNING refs INTO remaining;
                IF remaining=0 THEN
                    DELETE FROM soc_bucket_entities WHERE source_name=item.source_name
                    AND grain=g AND bucket_utc=t AND relying_party=item.relying_party
                    AND kind=k AND entity_key=entity;
                    change:=-1;
                END IF;
            END IF;
            IF change<>0 THEN
                UPDATE soc_service_buckets SET
                    distinct_users=distinct_users+CASE WHEN k='user' THEN change ELSE 0 END,
                    distinct_ips=distinct_ips+CASE WHEN k='ip' THEN change ELSE 0 END
                WHERE source_name=item.source_name AND grain=g AND bucket_utc=t
                  AND relying_party=item.relying_party;
            END IF;
        END LOOP;
        DELETE FROM soc_service_buckets WHERE source_name=item.source_name AND grain=g
            AND bucket_utc=t AND relying_party=item.relying_party AND total_events=0;
    END LOOP;
END;
$$;
CREATE OR REPLACE FUNCTION soc_maintain_analytics() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE','UPDATE') THEN PERFORM soc_apply_analytics(OLD,-1); END IF;
    IF TG_OP IN ('INSERT','UPDATE') THEN PERFORM soc_apply_analytics(NEW,1); END IF;
    RETURN NULL;
END;
$$;
CREATE OR REPLACE TRIGGER soc_analytics_event AFTER INSERT OR UPDATE OR DELETE ON normalized_events
    FOR EACH ROW EXECUTE FUNCTION soc_maintain_analytics();
REVOKE ALL ON FUNCTION soc_apply_analytics(normalized_events,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION soc_maintain_analytics() FROM PUBLIC;
