import { useEffect, useRef, useState } from 'react';

import { api, UnauthorizedError } from '../api';
import type { Document, UploadRequest } from '../types';
import { messageFor } from './messageFor';
import { sha256For } from './sha256For';

type UploadPhase =
  | { status: 'idle' }
  | { status: 'hashing' }
  | { status: 'requesting_url' }
  | { status: 'uploading'; percent: number; documentId: string; filename: string }
  | { status: 'ingesting'; percent: number; documentId: string; filename: string; stage?: string }
  | { status: 'canceled'; filename?: string }
  | { status: 'error'; message: string };

export function useDocuments(token: string | null) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [uploadPhase, setUploadPhase] = useState<UploadPhase>({ status: 'idle' });
  const [documentsError, setDocumentsError] = useState<string>();

  const xhrRef = useRef<XMLHttpRequest | null>(null);
  const pollAbortRef = useRef<AbortController | null>(null);
  const refreshingRef = useRef(false);

  async function refreshDocuments(nextToken?: string | null) {
    const active = nextToken ?? token;
    if (!active) {
      setDocuments([]);
      return;
    }
    if (refreshingRef.current) return;
    refreshingRef.current = true;
    try {
      setDocuments(await api.documents(active));
    } catch (reason) {
      if (reason instanceof UnauthorizedError) return;
      setDocumentsError(messageFor(reason));
    } finally {
      refreshingRef.current = false;
    }
  }

  useEffect(() => {
    refreshDocuments(token);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (!token) return;
    const needsPolling =
      uploadPhase.status === 'ingesting' ||
      documents.some((doc) => doc.status === 'pending' || doc.status === 'processing');
    if (!needsPolling) return;
    const id = window.setInterval(() => {
      refreshDocuments(token);
    }, 1500);
    return () => window.clearInterval(id);
  }, [token, uploadPhase.status, documents]);

  async function uploadFile(file: File) {
    if (!token || !file.name) return;
    setDocumentsError(undefined);
    setUploadPhase({ status: 'hashing' });

    let documentId: string | null = null;
    let filename: string | null = null;

    try {
      const sha256 = await sha256For(file);
      setUploadPhase({ status: 'requesting_url' });
      const payload: UploadRequest = {
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        size: file.size,
        sha256
      };
      const upload = await api.uploadUrl(payload, token);

      documentId = upload.document.id;
      filename = upload.document.filename;

      // Upload directly to S3 with progress + cancel support.
      const xhr = new XMLHttpRequest();
      xhrRef.current = xhr;
      setUploadPhase({ status: 'uploading', percent: 0, documentId, filename });

      const uploadDone = new Promise<void>((resolve, reject) => {
        xhr.upload.onprogress = (e) => {
          if (!e.lengthComputable) return;
          const percent = Math.max(0, Math.min(100, Math.round((e.loaded / e.total) * 100)));
          setUploadPhase((current) =>
            current.status === 'uploading' ? { ...current, percent } : current
          );
        };
        xhr.onerror = () => reject(new Error('Upload failed'));
        xhr.onabort = () => reject(new DOMException('Upload aborted', 'AbortError'));
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) resolve();
          else reject(new Error(`Upload failed (${xhr.status})`));
        };
      });

      xhr.open('PUT', upload.upload_url);
      xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
      xhr.send(file);
      await uploadDone;

      // Ingestion is asynchronous; in local dev we kick it off explicitly,
      // and in all environments we poll the document status for progress.
      setUploadPhase({ status: 'ingesting', percent: 0, documentId, filename, stage: 'starting' });

      if (import.meta.env.DEV) {
        api.ingestDocument(documentId, token).catch(() => null);
      }

      await pollUntilReady(token, documentId, filename);

      await refreshDocuments(token);
      setUploadPhase({ status: 'idle' });
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') {
        // Best-effort: mark the orphaned "pending" document as canceled.
        if (token && documentId) api.cancelDocument(documentId, token).catch(() => null);
        setUploadPhase({ status: 'canceled', filename: filename ?? file.name });
      } else if (!(reason instanceof UnauthorizedError)) {
        setUploadPhase({ status: 'error', message: messageFor(reason) });
        setDocumentsError(messageFor(reason));
      }
    } finally {
      xhrRef.current = null;
    }
  }

  async function pollUntilReady(token: string, documentId: string, filename: string) {
    pollAbortRef.current?.abort();
    const controller = new AbortController();
    pollAbortRef.current = controller;
    const startedAt = Date.now();

    const sleep = (ms: number) =>
      new Promise<void>((resolve, reject) => {
        const id = window.setTimeout(resolve, ms);
        controller.signal.addEventListener(
          'abort',
          () => {
            window.clearTimeout(id);
            reject(new DOMException('Polling aborted', 'AbortError'));
          },
          { once: true }
        );
      });

    while (true) {
      if (Date.now() - startedAt > 10 * 60 * 1000) {
        throw new Error('Ingestion timed out');
      }

      const doc = await api.document(documentId, token, controller.signal);
      if (doc.status === 'ready') return;
      if (doc.status === 'failed') {
        throw new Error(doc.error_code ? `Ingestion failed: ${doc.error_code}` : 'Ingestion failed');
      }

      const percent =
        typeof doc.ingest_percent === 'number'
          ? doc.ingest_percent
          : doc.status === 'processing'
            ? 50
            : 0;
      setUploadPhase({
        status: 'ingesting',
        percent,
        documentId,
        filename,
        stage: doc.ingest_stage
      });

      await sleep(600);
    }
  }

  function cancelUpload() {
    if (uploadPhase.status === 'uploading') {
      xhrRef.current?.abort();
      return;
    }
    if (uploadPhase.status === 'ingesting') {
      pollAbortRef.current?.abort();
      if (token) api.cancelDocument(uploadPhase.documentId, token).catch(() => null);
      setUploadPhase({ status: 'canceled', filename: uploadPhase.filename });
    }
  }

  return {
    documents,
    refreshDocuments,
    documentsError,
    setDocumentsError,
    uploadPhase,
    uploadFile,
    cancelUpload
  };
}
