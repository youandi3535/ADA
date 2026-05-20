-- ============================================================
-- init.sql  -  Postgres 첫 기동 시 자동 실행
-- 위치: compose에서 ./init.sql:/docker-entrypoint-initdb.d/init.sql 마운트
-- 작업지시서 §7.1
-- ============================================================

-- 1) mlflow 백엔드용 DB 추가 (autoai DB 는 환경변수로 이미 만들어짐)
CREATE DATABASE mlflow;
GRANT ALL PRIVILEGES ON DATABASE autoai TO autoai;
GRANT ALL PRIVILEGES ON DATABASE mlflow TO autoai;

-- 2) autoai DB 확장 활성화
\c autoai
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";
CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector (Day02 v2)
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- 컬럼 암호화 (Day17)

-- 3) mlflow DB 확장
\c mlflow
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
