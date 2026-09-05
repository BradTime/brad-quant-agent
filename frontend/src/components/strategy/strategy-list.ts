export function pageAfterDeletingItem(page: number, itemsOnPage: number): number {
  return page > 1 && itemsOnPage === 1 ? page - 1 : page;
}
