-- sql/schema.sql
-- Multi-Agent Procurement Intelligence System
-- Milestone 2: Supabase Persistence

-- 1. Enable RLS
-- 2. Create Tables
-- 3. Set Policies

-- Requests Table
CREATE TABLE IF NOT EXISTS public.procurement_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id TEXT UNIQUE NOT NULL,
    requester TEXT NOT NULL,
    supplier_name TEXT NOT NULL,
    proposed_price DECIMAL(12, 2) NOT NULL,
    required_features JSONB NOT NULL,
    budget_ceiling DECIMAL(12, 2) NOT NULL,
    urgency TEXT NOT NULL,
    status TEXT DEFAULT 'pending', -- pending, researching, decided, error
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Reports Table
CREATE TABLE IF NOT EXISTS public.procurement_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id TEXT UNIQUE NOT NULL,
    request_id TEXT REFERENCES public.procurement_requests(request_id) ON DELETE CASCADE,
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    procurement_decision JSONB NOT NULL,
    competition_matrix JSONB NOT NULL,
    executive_summary TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    data_quality_notes JSONB DEFAULT '[]'::jsonb,
    pipeline_metadata JSONB DEFAULT '{}'::jsonb
);

-- Enable RLS
ALTER TABLE public.procurement_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.procurement_reports ENABLE ROW LEVEL SECURITY;

-- Policies (Milestone 2: Authenticated Access Only)
CREATE POLICY "Authenticated users can select requests" ON public.procurement_requests FOR SELECT USING (auth.role() = 'authenticated');
CREATE POLICY "Authenticated users can insert requests" ON public.procurement_requests FOR INSERT WITH CHECK (auth.role() = 'authenticated');
CREATE POLICY "Authenticated users can update requests" ON public.procurement_requests FOR UPDATE USING (auth.role() = 'authenticated');

CREATE POLICY "Authenticated users can select reports" ON public.procurement_reports FOR SELECT USING (auth.role() = 'authenticated');
CREATE POLICY "Authenticated users can insert reports" ON public.procurement_reports FOR INSERT WITH CHECK (auth.role() = 'authenticated');
