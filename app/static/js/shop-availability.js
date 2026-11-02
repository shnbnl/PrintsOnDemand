"use strict";
(() => {
  const url = document.currentScript.dataset.availabilityUrl;
  let pending = false;
  async function refresh() {
    if (pending || document.hidden || !document.querySelector('[data-shop-status]')) return;
    pending = true;
    try {
      const response = await fetch(url, { cache: 'no-store', headers: { Accept: 'application/json' } });
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return;
      const { shops } = await response.json();
      const byId = new Map(shops.map(shop => [String(shop.id), shop]));
      document.querySelectorAll('[data-shop-status]').forEach(badge => {
        const status = byId.get(badge.dataset.shopStatus);
        badge.textContent = status?.label || 'Closed';
        badge.className = `status-badge ${status?.badge_class || 'status-muted'}`;
      });
      const workspace = document.querySelector('[data-shop-workspace]');
      const selected = workspace?.querySelector('[data-current-shop]')?.dataset.currentShop;
      const status = byId.get(selected);
      const footer = workspace?.querySelector('[data-ordering-open]');
      if (footer && selected) {
        const open = status?.code === 'AVAILABLE';
        footer.dataset.orderingOpen = String(open);
        const button = footer.querySelector('[data-workspace-proceed]');
        if (!open) button.disabled = true;
        else {
          const content = workspace.querySelector('[data-workspace-content]');
          if (!content.inert && content.getAttribute('aria-busy') !== 'true'
              && workspace.querySelector('[name="shop_id"]').value === selected) {
            button.disabled = footer.dataset.quoteValid !== 'true';
          }
        }
        const notice = workspace.querySelector('[data-ordering-status]');
        notice.textContent = status?.ordering_error || (open ? 'Open now. Shop hours use Philippine time.' : 'This shop is unavailable. Choose another shop.');
        notice.className = open ? 'hint' : 'notice notice-warning';
      }
    } catch (_) {
      // Keep the last displayed state; the server always rechecks submission.
    } finally {
      pending = false;
    }
  }
  window.setInterval(refresh, 15000);
  document.addEventListener('visibilitychange', refresh);
  document.addEventListener('pod:shop-selected', refresh);
  refresh();
})();
