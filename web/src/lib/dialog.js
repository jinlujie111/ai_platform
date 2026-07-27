import { escapeHtml } from './utils.js';

/** Lightweight toast (also used by Vue shell) */
export function showAppToast(message, type = 'ok', duration = 3200) {
  let host = document.getElementById('appToastHost');
  if (!host) {
    host = document.createElement('div');
    host.id = 'appToastHost';
    host.className = 'app-toast-host';
    document.body.appendChild(host);
  }
  const el = document.createElement('div');
  el.className = 'app-toast ' + (type || 'ok');
  el.textContent = String(message || '');
  host.appendChild(el);
  window.setTimeout(() => {
    el.classList.add('is-leaving');
    window.setTimeout(() => el.remove(), 220);
  }, duration);
}

const CHAT_NOTICE_ICONS = {
  info: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  warn: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  error: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
  danger: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
};

let chatNoticeActionHandler = null;
let chatNoticeDismissHandler = null;

export function closeChatNotice(result = false) {
  const modal = document.getElementById('chatNoticeModal');
  if (modal) modal.classList.remove('open');
  const dismiss = chatNoticeDismissHandler;
  chatNoticeActionHandler = null;
  chatNoticeDismissHandler = null;
  if (typeof dismiss === 'function') dismiss(result);
}

export function showChatNotice(options = {}) {
  const {
    title = '提示',
    subtitle = '',
    message = '',
    metaHtml = '',
    type = 'info',
    actionLabel = '',
    onAction = null,
    onDismiss = null,
    cancelLabel = '知道了',
    danger = false,
  } = options;
  const modal = document.getElementById('chatNoticeModal');
  const dialog = modal?.querySelector('.chat-notice-dialog');
  const iconEl = document.getElementById('chatNoticeIcon');
  const titleEl = document.getElementById('chatNoticeTitle');
  const subtitleEl = document.getElementById('chatNoticeSubtitle');
  const messageEl = document.getElementById('chatNoticeMessage');
  const metaEl = document.getElementById('chatNoticeMeta');
  const actionBtn = document.getElementById('chatNoticeAction');
  const cancelBtn = document.getElementById('chatNoticeCancel');
  if (!modal || !messageEl) {
    showAppToast(message || title, type === 'error' || danger ? 'error' : 'ok');
    return;
  }
  if (titleEl) titleEl.textContent = title;
  if (subtitleEl) {
    subtitleEl.textContent = subtitle || '';
    subtitleEl.hidden = !subtitle;
  }
  messageEl.textContent = message;
  if (metaEl) {
    if (metaHtml) {
      metaEl.hidden = false;
      metaEl.innerHTML = metaHtml;
    } else {
      metaEl.hidden = true;
      metaEl.innerHTML = '';
    }
  }
  if (dialog) dialog.classList.toggle('is-danger', Boolean(danger));
  if (iconEl) {
    const iconType = danger ? 'danger' : (type === 'warn' || type === 'error' ? type : 'info');
    iconEl.className = 'chat-notice-icon' + (iconType === 'info' ? '' : ' ' + (iconType === 'danger' ? 'error' : iconType));
    iconEl.innerHTML = CHAT_NOTICE_ICONS[iconType] || CHAT_NOTICE_ICONS.info;
  }
  if (cancelBtn) cancelBtn.textContent = cancelLabel;
  chatNoticeActionHandler = typeof onAction === 'function' ? onAction : null;
  chatNoticeDismissHandler = typeof onDismiss === 'function' ? onDismiss : null;
  if (actionBtn) {
    const hasAction = Boolean(actionLabel && chatNoticeActionHandler);
    actionBtn.hidden = !hasAction;
    actionBtn.textContent = actionLabel || '确认';
    actionBtn.className = danger ? 'btn-danger' : 'btn-primary';
  }
  modal.classList.add('open');
}

export function confirmAppDialog(options = {}) {
  return new Promise((resolve) => {
    showChatNotice({
      type: options.type || 'warn',
      danger: options.danger !== false,
      title: options.title || '确认删除',
      subtitle: options.subtitle || '此操作不可撤销',
      message: options.message || '确定继续吗？',
      metaHtml: options.metaHtml || '',
      cancelLabel: options.cancelLabel || '取消',
      actionLabel: options.actionLabel || '删除',
      onAction: () => {},
      onDismiss: (confirmed) => resolve(Boolean(confirmed)),
    });
  });
}

export function bindChatNoticeButtons() {
  document.getElementById('chatNoticeCancel')?.addEventListener('click', () => closeChatNotice(false));
  document.getElementById('chatNoticeAction')?.addEventListener('click', () => {
    const action = chatNoticeActionHandler;
    closeChatNotice(true);
    if (typeof action === 'function') action();
  });
  document.getElementById('chatNoticeModal')?.addEventListener('click', (e) => {
    if (e.target?.id === 'chatNoticeModal') closeChatNotice(false);
  });
}

export { escapeHtml };
