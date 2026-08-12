export type Identity = { sub: string; email?: string; name?: string };

export type Conversation = { id: string; title?: string; created_at: string; updated_at?: string };

export type Citation = {
  document_id: string;
  filename: string;
  chunk_index: number;
  excerpt: string;
};

export type Message = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  created_at: string;
  citations?: Citation[];
};

export type Document = {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  status: 'pending' | 'processing' | 'ready' | 'failed';
  error_code?: string;
  chunk_count?: number;
  created_at?: string;
  updated_at?: string;
  ingest_stage?: string;
  ingest_percent?: number;
  ingest_processed_chunks?: number;
  ingest_total_chunks?: number;
};

export type UploadRequest = {
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
};

export type UploadUrl = { document: Document; upload_url: string };
