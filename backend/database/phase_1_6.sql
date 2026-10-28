-- Snapshot of the matched specialty and scores, including emergency cases.
ALTER TABLE public.emergency_intakes
    ADD COLUMN IF NOT EXISTS specialty jsonb;
