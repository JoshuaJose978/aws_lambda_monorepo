export const API_ENDPOINTS = {
  me: '/me',
  conversations: '/conversations',
  conversationMessages: (id: string) => `/conversations/${id}/messages`,
  documents: '/documents',
  document: (id: string) => `/documents/${id}`,
  uploadUrl: '/documents/upload-url',
  cancelDocument: (id: string) => `/documents/${id}/cancel`,
  ingestDocument: (id: string) => `/documents/${id}/ingest`
} as const;
