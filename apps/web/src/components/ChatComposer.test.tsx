import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import React from 'react';

import { ChatComposer } from './ChatComposer';

describe('ChatComposer', () => {
  it('submits on Enter and not on Shift+Enter', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    const onCancel = vi.fn();

    function Harness() {
      const [prompt, setPrompt] = React.useState('');
      return (
        <ChatComposer
          prompt={prompt}
          onPromptChange={setPrompt}
          disabled={false}
          busy={false}
          onCancel={onCancel}
          onSend={onSend}
        />
      );
    }

    render(<Harness />);

    const textbox = screen.getByLabelText('Your question');
    await user.type(textbox, 'hello');
    await user.keyboard('{Shift>}{Enter}{/Shift}');
    expect(onSend).toHaveBeenCalledTimes(0);

    await user.keyboard('{Enter}');
    expect(onSend).toHaveBeenCalledTimes(1);
  });
});
