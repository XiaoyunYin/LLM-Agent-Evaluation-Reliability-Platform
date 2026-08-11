CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source_uri TEXT NOT NULL,
    title TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS eval_runs (
    run_id TEXT PRIMARY KEY,
    dataset_version TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (status IN ('pending', 'running', 'completed', 'failed'))
);

CREATE TABLE IF NOT EXISTS candidate_answers (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES eval_runs(run_id),
    case_id TEXT NOT NULL,
    generated_answer TEXT NOT NULL,
    trace_id TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('pending', 'running', 'completed', 'failed'))
);

CREATE TABLE IF NOT EXISTS judge_scores (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES eval_runs(run_id),
    case_id TEXT NOT NULL,
    candidate_answer_id TEXT NOT NULL REFERENCES candidate_answers(id),
    judge_name TEXT NOT NULL,
    judge_type TEXT NOT NULL,
    correctness DOUBLE PRECISION NOT NULL,
    faithfulness DOUBLE PRECISION NOT NULL,
    citation_quality DOUBLE PRECISION NOT NULL,
    passed BOOLEAN NOT NULL,
    explanation TEXT NOT NULL,
    trace_id TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (judge_type IN ('rule_based', 'gpt4o_mini', 'self_hosted_7b')),
    CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    CHECK (correctness >= 0.0 AND correctness <= 1.0),
    CHECK (faithfulness >= 0.0 AND faithfulness <= 1.0),
    CHECK (citation_quality >= 0.0 AND citation_quality <= 1.0)
);

CREATE TABLE IF NOT EXISTS review_cases (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES eval_runs(run_id),
    case_id TEXT NOT NULL,
    candidate_answer_id TEXT REFERENCES candidate_answers(id),
    judge_score_id TEXT REFERENCES judge_scores(id),
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    notes TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    CHECK (status IN ('open', 'in_review', 'resolved', 'dismissed'))
);