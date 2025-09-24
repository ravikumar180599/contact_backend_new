-- public.call_mapping definition

-- Drop table

-- DROP TABLE public.call_mapping;

CREATE TABLE public.call_mapping (
	id uuid DEFAULT gen_random_uuid() NOT NULL,
	agent_status text DEFAULT 'READY'::text NULL,
	call_id text NULL,
	agent_id text NULL,
	sock_url text NOT NULL,
	created_at timestamptz DEFAULT now() NULL,
	updated_at timestamptz DEFAULT now() NULL,
	end_time timestamp NULL,
	transcribed_text text NULL,
	CONSTRAINT call_mapping_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_call_mapping_agent_id ON public.call_mapping USING btree (agent_id);
CREATE INDEX idx_call_mapping_call_id ON public.call_mapping USING btree (call_id);
CREATE INDEX idx_call_mapping_created_at ON public.call_mapping USING btree (created_at);
CREATE INDEX idx_call_mapping_updated_at ON public.call_mapping USING btree (updated_at);