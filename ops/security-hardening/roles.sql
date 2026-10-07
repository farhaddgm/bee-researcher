-- Run by the database operator, never by the HTTP process.
-- Credentials are supplied separately through stdin by the release tool.
ALTER SCHEMA market_intelligence OWNER TO bee_researcher_migrator;
DO $$ DECLARE item record; BEGIN
  FOR item IN SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='market_intelligence' AND c.relkind IN ('r','p','S','v','m','f')
      ORDER BY CASE WHEN c.relkind='S' THEN 1 ELSE 0 END
  LOOP
    EXECUTE format('ALTER %s market_intelligence.%I OWNER TO bee_researcher_migrator',
      CASE item.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW'
      WHEN 'f' THEN 'FOREIGN TABLE' ELSE 'TABLE' END, item.relname);
  END LOOP;
END $$;
REVOKE ALL ON SCHEMA market_intelligence FROM PUBLIC;
GRANT USAGE ON SCHEMA market_intelligence TO bee_researcher_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA market_intelligence TO bee_researcher_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA market_intelligence TO bee_researcher_runtime;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA market_intelligence FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE bee_researcher_migrator IN SCHEMA market_intelligence
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO bee_researcher_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE bee_researcher_migrator IN SCHEMA market_intelligence
    GRANT USAGE, SELECT ON SEQUENCES TO bee_researcher_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE bee_researcher_migrator IN SCHEMA market_intelligence
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON market_intelligence.alembic_version FROM bee_researcher_runtime;
