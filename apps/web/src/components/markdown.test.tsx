import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { Markdown } from './markdown';

describe('Markdown (guide content renderer)', () => {
  it('renders paragraphs, lists, emphasis and safe links', () => {
    const { container } = render(<Markdown source={'Hello **world**.\n\n- one\n- *two*\n\n[OSM](https://www.openstreetmap.org)'} />);
    expect(container.querySelector('strong')?.textContent).toBe('world');
    expect(container.querySelectorAll('li')).toHaveLength(2);
    expect(container.querySelector('em')?.textContent).toBe('two');
    const link = container.querySelector('a');
    expect(link?.getAttribute('href')).toBe('https://www.openstreetmap.org');
    expect(link?.getAttribute('rel')).toContain('noopener');
  });

  it('never renders HTML or unsafe link schemes', () => {
    const { container } = render(<Markdown source={'<img src=x onerror=alert(1)> [click](javascript:alert(1))'} />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('a')).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>');
  });
});
