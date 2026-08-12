import type { FormEvent } from 'react';
import { useEffect, useState } from 'react';

import { ChatComposer } from './components/ChatComposer';
import { Markdown } from './components/Markdown';
import { messageFor } from './hooks/messageFor';
import { useAuth } from './hooks/useAuth';
import { useConversations } from './hooks/useConversations';
import { useDocuments } from './hooks/useDocuments';

export function App() {
  const [prompt, setPrompt] = useState('');
  const [error, setError] = useState<string>();

  const { token, identity, authError, setAuthError, login, logout } = useAuth();
  const {
    conversations,
    conversationId,
    setConversationId,
    messages,
    createConversation,
    sendMessage,
    cancelChat,
    chatBusy,
    chatError,
    setChatError
  } = useConversations(token);
  const {
    documents,
    documentsError,
    setDocumentsError,
    uploadPhase,
    uploadFile,
    cancelUpload
  } = useDocuments(token);

  useEffect(() => {
    setError(authError ?? chatError ?? documentsError);
  }, [authError, chatError, documentsError]);

  function clearErrors() {
    setError(undefined);
    setAuthError(undefined);
    setChatError(undefined);
    setDocumentsError(undefined);
  }

  if (!token) {
    return (
      <main className="login">
        <section className="login-card">
          <p className="eyebrow">Private document search · secure workspace</p>
          <h1>Ask your documents.</h1>
          <p className="login-copy">
            Search, question, and trace the knowledge held in your private document library.
          </p>
          <span className="title-rule" aria-hidden="true" />
          {error && <p className="error">{error}</p>}
          <button
            className="primary-button"
            onClick={() =>
              login().catch((reason: unknown) => {
                setAuthError(messageFor(reason));
              })
            }
          >
            Sign in
          </button>
          <p className="login-note">Your conversations and source files remain private.</p>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="identity">
          <p className="eyebrow">Research desk</p>
          <strong>{identity?.name ?? identity?.email ?? identity?.sub ?? 'Loading user...'}</strong>
          <button
            className="text-button"
            onClick={() =>
              logout().catch((reason: unknown) => {
                setAuthError(messageFor(reason));
              })
            }
          >
            Sign out
          </button>
        </div>

        <button
          className="primary-button new-conversation"
          onClick={() => {
            clearErrors();
            createConversation().catch((reason: unknown) => setChatError(messageFor(reason)));
          }}
          disabled={chatBusy || uploadPhase.status !== 'idle'}
        >
          <span aria-hidden="true">+</span> New conversation
        </button>

        <div className="section-heading">
          <p className="eyebrow">Conversations</p>
          <span>{conversations.length}</span>
        </div>

        <nav aria-label="Conversations">
          {conversations.map((conversation) => (
            <button
              className={conversation.id === conversationId ? 'conversation selected' : 'conversation'}
              key={conversation.id}
              onClick={() => {
                clearErrors();
                setConversationId(conversation.id);
              }}
            >
              {conversation.title || 'Untitled conversation'}
            </button>
          ))}
          {!conversations.length && <p className="quiet-note">Your conversations will appear here.</p>}
        </nav>
      </aside>

      <section className="chat-panel">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">Private retrieval</p>
            <h1>{conversationId ? 'Conversation' : 'Document intelligence'}</h1>
          </div>
          <span className="workspace-status" aria-live="polite">
            {chatBusy || uploadPhase.status !== 'idle' ? 'Working' : 'Ready'}
          </span>
        </header>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        {conversationId ? (
          <>
            <div className="messages">
              {messages.map((message) => (
                <article className={`message ${message.role}`} key={message.id}>
                  <p className="message-label">{message.role === 'user' ? 'You' : 'Assistant'}</p>
                  <div className="markdown">
                    <Markdown>{message.text}</Markdown>
                  </div>
                  {message.citations?.map((citation) => (
                    <details className="citation" key={`${citation.document_id}-${citation.chunk_index}`}>
                      <summary>{citation.filename}</summary>
                      <div className="markdown">
                        <Markdown>{citation.excerpt}</Markdown>
                      </div>
                    </details>
                  ))}
                </article>
              ))}
            </div>

            <ChatComposer
              prompt={prompt}
              onPromptChange={(next) => {
                setPrompt(next);
                if (error) clearErrors();
              }}
              disabled={!conversationId || chatBusy}
              busy={chatBusy}
              onCancel={cancelChat}
              onSend={() => {
                const text = prompt;
                if (!text.trim()) return;
                setPrompt('');
                clearErrors();
                sendMessage(text).catch((reason: unknown) => setChatError(messageFor(reason)));
              }}
            />
          </>
        ) : (
          <div className="empty-state">
            <p className="eyebrow">Start a thread</p>
            <h2>Give your documents a question.</h2>
            <p>
              Create a conversation, then ask for an answer grounded in the files held in your
              library.
            </p>
            <span className="title-rule" aria-hidden="true" />
          </div>
        )}
      </section>

      <aside className="documents">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Source library</p>
            <h2>Documents</h2>
          </div>
          <span>{documents.length}</span>
        </div>

        <form
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            const form = event.currentTarget;
            const file = new FormData(event.currentTarget).get('document');
            if (!(file instanceof File) || !file.name) return;
            clearErrors();
            uploadFile(file)
              .then(() => form.reset())
              .catch((reason: unknown) => setDocumentsError(messageFor(reason)));
          }}
        >
          <label htmlFor="document">Upload a document</label>
          <input
            id="document"
            name="document"
            type="file"
            accept=".pdf,.docx,.md,.txt,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          />
          <div className="upload-actions">
            {(uploadPhase.status === 'uploading' || uploadPhase.status === 'ingesting') && (
              <button className="secondary-button" type="button" onClick={cancelUpload}>
                Cancel
              </button>
            )}
            <button
              className="primary-button"
              disabled={
                chatBusy ||
                uploadPhase.status === 'hashing' ||
                uploadPhase.status === 'requesting_url' ||
                uploadPhase.status === 'uploading' ||
                uploadPhase.status === 'ingesting'
              }
            >
              {uploadPhase.status === 'hashing'
                ? 'Hashing…'
                : uploadPhase.status === 'requesting_url'
                  ? 'Preparing…'
                  : uploadPhase.status === 'uploading'
                    ? `Uploading ${uploadPhase.percent}%`
                    : uploadPhase.status === 'ingesting'
                      ? uploadPhase.stage
                        ? `Ingesting (${uploadPhase.stage}) ${uploadPhase.percent}%`
                        : `Ingesting ${uploadPhase.percent}%`
                      : 'Upload document'}
            </button>
          </div>

          {(uploadPhase.status === 'uploading' || uploadPhase.status === 'ingesting') && (
            <div
              className="progress"
              role="progressbar"
              aria-label={uploadPhase.status === 'uploading' ? 'Upload progress' : 'Ingestion progress'}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={uploadPhase.percent}
            >
              <div className="progress-bar" style={{ width: `${uploadPhase.percent}%` }} />
            </div>
          )}
          {uploadPhase.status === 'canceled' && <p className="quiet-note">Upload canceled.</p>}
          {uploadPhase.status === 'error' && (
            <p className="quiet-note">Upload failed: {uploadPhase.message}</p>
          )}
        </form>

        <ul>
          {documents.map((document) => (
            <li key={document.id}>
              <strong>{document.filename}</strong>
              <div className="document-meta">
                <span>
                  {document.status}
                  {document.error_code ? `: ${document.error_code}` : ''}
                  {document.status === 'processing' && document.ingest_stage
                    ? ` (${document.ingest_stage})`
                    : ''}
                </span>
                {document.status === 'processing' ? (
                  <div
                    className={
                      typeof document.ingest_percent === 'number'
                        ? 'document-progress'
                        : 'document-progress indeterminate'
                    }
                    role="progressbar"
                    aria-label="Ingestion progress"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={
                      typeof document.ingest_percent === 'number' ? document.ingest_percent : undefined
                    }
                    aria-valuetext={
                      typeof document.ingest_percent === 'number'
                        ? `${document.ingest_percent}%`
                        : 'In progress'
                    }
                    title={
                      typeof document.ingest_percent === 'number'
                        ? `Ingesting ${document.ingest_percent}%${document.ingest_stage ? ` (${document.ingest_stage})` : ''}`
                        : `Ingesting${document.ingest_stage ? ` (${document.ingest_stage})` : ''}`
                    }
                  >
                    <div
                      className="document-progress-bar"
                      style={{
                        width:
                          typeof document.ingest_percent === 'number'
                            ? `${document.ingest_percent}%`
                            : undefined
                      }}
                    />
                  </div>
                ) : null}
              </div>
            </li>
          ))}
          {!documents.length && <li className="quiet-note">No documents have been uploaded yet.</li>}
        </ul>
      </aside>
    </main>
  );
}
