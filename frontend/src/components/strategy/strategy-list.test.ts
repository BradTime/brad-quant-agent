import { describe, expect, it } from 'vitest';

import { pageAfterDeletingItem } from './strategy-list';

describe('pageAfterDeletingItem', () => {
  it('moves back when deleting the only item on a later page', () => {
    expect(pageAfterDeletingItem(2, 1)).toBe(1);
  });

  it('keeps the current page when other items remain', () => {
    expect(pageAfterDeletingItem(2, 3)).toBe(2);
  });

  it('never moves before the first page', () => {
    expect(pageAfterDeletingItem(1, 1)).toBe(1);
  });
});
