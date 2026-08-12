import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

// Avoid depending on WebCrypto availability in the test environment.
// The behavior under test is the cancel path after an abort.
vi.mock('./sha256For', () => ({
  sha256For: async () => 'a'.repeat(64)
}));

import { useDocuments } from './useDocuments';

type CancelCall = { id: string };
const cancelCalls: CancelCall[] = [];

const server = setupServer(
  http.get('*/documents', () => HttpResponse.json({ items: [] })),
  http.post('*/documents/upload-url', () =>
    HttpResponse.json({
      document: {
        id: 'doc-1',
        filename: 'notes.md',
        content_type: 'text/markdown',
        size: 1,
        sha256: 'a'.repeat(64),
        status: 'pending',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        chunk_count: 0
      },
      upload_url: 'http://upload.test/put'
    })
  ),
  http.post('*/documents/:id/cancel', ({ params }) => {
    cancelCalls.push({ id: String(params.id) });
    return HttpResponse.json({ status: 'canceled' });
  })
);

class FakeXhr {
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null };
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  onload: (() => void) | null = null;
  status = 0;

  open() {
    // no-op
  }

  setRequestHeader() {
    // no-op
  }

  send() {
    // no-op
  }

  abort() {
    this.onabort?.();
  }
}

describe('useDocuments', () => {
  beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
  afterEach(() => {
    server.resetHandlers();
    cancelCalls.length = 0;
  });
  afterAll(() => server.close());

  it('calls /documents/{id}/cancel when an upload is aborted', async () => {
    const user = userEvent.setup();

    const OriginalXhr = globalThis.XMLHttpRequest;
    // @ts-expect-error test stub
    globalThis.XMLHttpRequest = FakeXhr;

    function Harness() {
      const { uploadPhase, uploadFile, cancelUpload } = useDocuments('test-token');
      return (
        <div>
          <div data-testid="phase">{uploadPhase.status}</div>
          <button
            type="button"
            onClick={() => {
              const file = new File(['hello'], 'notes.md', { type: 'text/markdown' });
              uploadFile(file).catch(() => null);
            }}
          >
            Upload
          </button>
          <button type="button" onClick={cancelUpload}>
            Cancel
          </button>
        </div>
      );
    }

    try {
      render(<Harness />);

      await user.click(screen.getByRole('button', { name: 'Upload' }));
      await waitFor(() => expect(screen.getByTestId('phase')).toHaveTextContent('uploading'));

      await user.click(screen.getByRole('button', { name: 'Cancel' }));

      await waitFor(() => expect(cancelCalls).toEqual([{ id: 'doc-1' }]));
      await waitFor(() => expect(screen.getByTestId('phase')).toHaveTextContent('canceled'));
    } finally {
      globalThis.XMLHttpRequest = OriginalXhr;
    }
  });
});
