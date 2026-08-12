import type { FormEvent } from 'react';

type Props = {
  prompt: string;
  onPromptChange: (next: string) => void;
  disabled: boolean;
  busy: boolean;
  onCancel: () => void;
  onSend: () => void;
};

export function ChatComposer({
  prompt,
  onPromptChange,
  disabled,
  busy,
  onCancel,
  onSend
}: Props) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSend();
  }

  return (
    <form className="composer" onSubmit={submit}>
      <label className="eyebrow" htmlFor="prompt">
        Your question
      </label>
      <textarea
        id="prompt"
        placeholder="Ask something about your documents..."
        value={prompt}
        onChange={(event) => onPromptChange(event.target.value)}
        disabled={disabled}
        onKeyDown={(event) => {
          if (event.key !== 'Enter') return;
          if (event.shiftKey) return;
          event.preventDefault();
          event.currentTarget.form?.requestSubmit();
        }}
      />
      <div className="composer-actions">
        {busy ? (
          <button className="secondary-button" type="button" onClick={onCancel}>
            Cancel
          </button>
        ) : null}
        <button className="primary-button" disabled={busy || !prompt.trim()}>
          {busy ? 'Sending…' : 'Send'}
        </button>
      </div>
    </form>
  );
}
