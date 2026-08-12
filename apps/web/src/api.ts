import type { Conversation, Document, Identity, Message, UploadRequest, UploadUrl } from './types';
import { API_ENDPOINTS } from './constants/apiEndpoints';

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

export function authorizationHeader(accessToken: string): HeadersInit {
  return { Authorization: `Bearer ${accessToken}` };
}

export class UnauthorizedError extends Error {
  name = 'UnauthorizedError';
}

async function request<T>(path: string, accessToken: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      ...authorizationHeader(accessToken),
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers
    }
  });
  if (!response.ok) {
    const error = (await response.json().catch(() => null)) as { message?: string } | null;
    if (response.status === 401) {
      throw new UnauthorizedError(error?.message ?? 'Unauthorized');
    }
    throw new Error(error?.message ?? `Request failed (${response.status})`);
  }

  const contentType = response.headers.get('content-type') ?? '';
  if (response.status === 204) return undefined as T;
  if (!contentType.includes('application/json')) {
    const text = await response.text();
    return (text ? (text as unknown as T) : (undefined as T));
  }
  const text = await response.text();
  return (text ? (JSON.parse(text) as T) : (undefined as T));
}

type Items<T> = { items: T[] };
type MessageResponse = { user_message: Message; assistant_message: Message };

export const api = {
  me: (token: string) => request<Identity>(API_ENDPOINTS.me, token),
  conversations: async (token: string) =>
    (await request<Items<Conversation>>(API_ENDPOINTS.conversations, token)).items,
  createConversation: (token: string) =>
    request<Conversation>(API_ENDPOINTS.conversations, token, { method: 'POST' }),
  messages: (id: string, token: string) =>
    request<Items<Message>>(API_ENDPOINTS.conversationMessages(id), token).then(
      (response) => response.items
    ),
  sendMessage: (id: string, text: string, token: string, signal?: AbortSignal) =>
    request<MessageResponse>(API_ENDPOINTS.conversationMessages(id), token, {
      method: 'POST',
      body: JSON.stringify({ text }),
      signal
    }).then((response) => response.assistant_message),
  documents: async (token: string) => (await request<Items<Document>>(API_ENDPOINTS.documents, token)).items,
  document: (id: string, token: string, signal?: AbortSignal) =>
    request<Document>(API_ENDPOINTS.document(id), token, { signal }),
  uploadUrl: (file: UploadRequest, token: string) =>
    request<UploadUrl>(API_ENDPOINTS.uploadUrl, token, {
      method: 'POST',
      body: JSON.stringify(file)
    }),
  cancelDocument: (id: string, token: string) =>
    request<{ status: string }>(API_ENDPOINTS.cancelDocument(id), token, { method: 'POST' }),
  ingestDocument: (id: string, token: string, signal?: AbortSignal) =>
    request<{ status: string }>(API_ENDPOINTS.ingestDocument(id), token, { method: 'POST', signal })
};
