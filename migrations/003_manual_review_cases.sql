ALTER TABLE review_cases
RENAME COLUMN reason TO disagreement_reason;

ALTER TABLE review_cases
ADD COLUMN IF NOT EXISTS answer TEXT,
ADD COLUMN IF NOT EXISTS judge_a_score DOUBLE PRECISION,
ADD COLUMN IF NOT EXISTS judge_b_score DOUBLE PRECISION,
ADD COLUMN IF NOT EXISTS human_label TEXT,
ADD COLUMN IF NOT EXISTS final_decision TEXT;

ALTER TABLE review_cases
DROP CONSTRAINT IF EXISTS review_cases_status_check;

UPDATE review_cases
SET status = 'pending'
WHERE status IN ('open', 'in_review');

UPDATE review_cases
SET status = 'resolved'
WHERE status IN ('dismissed', 'resolved');

ALTER TABLE review_cases
ALTER COLUMN status SET DEFAULT 'pending';

ALTER TABLE review_cases
ADD CONSTRAINT review_cases_status_check
CHECK (status IN ('pending', 'reviewed', 'resolved'));

ALTER TABLE review_cases
ADD CONSTRAINT review_cases_judge_a_score_check
CHECK (judge_a_score >= 0.0 AND judge_a_score <= 1.0);

ALTER TABLE review_cases
ADD CONSTRAINT review_cases_judge_b_score_check
CHECK (judge_b_score >= 0.0 AND judge_b_score <= 1.0);