import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Markdown } from './Markdown';

describe('Markdown', () => {
  it('renders basic markdown + gfm', () => {
    render(
      <Markdown>{`**bold**

- one
- two

tick: \`code\``}</Markdown>
    );

    expect(screen.getByText('bold').tagName.toLowerCase()).toBe('strong');
    expect(screen.getByText('one')).toBeInTheDocument();
    expect(screen.getByText('two')).toBeInTheDocument();
    expect(screen.getByText('code').tagName.toLowerCase()).toBe('code');
  });
});
