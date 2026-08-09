import { createChatController } from '/assets/chat-app.js';

const config = globalThis.PLUGICT_PUBLIC_CONFIG;
const gate = document.querySelector('[data-auth-gate]');
const signInButton = document.querySelector('[data-google-signin]');
const dashboard = document.querySelector('[data-chat-dashboard]');
const userEmails = [...document.querySelectorAll('[data-user-email]')];
const signOutButtons = [...document.querySelectorAll('[data-signout]')];
const status = document.querySelector('[data-chat-status]');
const messages = document.querySelector('[data-messages]');
const form = document.querySelector('[data-chat-form]');
const questionInput = document.querySelector('[data-question]');
const submitButton = form?.querySelector('button[type="submit"]');
const creditLabels = [...document.querySelectorAll('[data-credits]')];
const planLabels = [...document.querySelectorAll('[data-plan]')];
let entitlementVersion = 0;

function setStatus(message = '', type = 'info') {
  if (!status) return;
  status.textContent = message;
  status.dataset.type = type;
  status.hidden = !message;
}

function clearNode(node) {
  while (node?.firstChild) node.removeChild(node.firstChild);
}

function appendText(parent, tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  parent.appendChild(element);
  return element;
}

function emptyState() {
  const wrapper = document.createElement('div');
  wrapper.className = 'empty';
  appendText(wrapper, 'h1', '', 'What did ICT actually teach?');
  appendText(
    wrapper,
    'p',
    '',
    'Ask a concept, model, or market-behaviour question. Every answer is grounded in the indexed ICT library.',
  );
  return wrapper;
}

function resetConversation() {
  clearNode(messages);
  messages?.appendChild(emptyState());
  if (questionInput) questionInput.value = '';
  for (const label of creditLabels) label.textContent = 'Checking allowance…';
  for (const label of planLabels) label.textContent = 'Checking…';
}

function renderEntitlement({ plan, remaining, limit, dailyReset } = {}) {
  const normalizedPlan = ['free', 'premium', 'pro'].includes(plan) ? plan : null;
  const planName = normalizedPlan
    ? normalizedPlan.charAt(0).toUpperCase() + normalizedPlan.slice(1)
    : 'Unavailable';
  for (const label of planLabels) label.textContent = planName;

  const safeRemaining = Number.isInteger(remaining) ? Math.max(0, remaining) : null;
  const safeLimit = Number.isInteger(limit) ? Math.max(0, limit) : null;
  let text = 'Allowance unavailable';
  if (safeRemaining !== null) {
    const suffix = dailyReset ? ' left today' : ' total remaining';
    text = safeLimit !== null ? `${safeRemaining} of ${safeLimit}${suffix}` : `${safeRemaining}${suffix}`;
  }
  for (const label of creditLabels) label.textContent = text;
}

function appendMessage(role, initialText = '') {
  messages?.querySelector('.empty')?.remove();
  const article = document.createElement('article');
  article.className = `message ${role}`;
  appendText(article, 'div', 'message-label', role === 'user' ? 'You' : 'PlugICT');
  const text = appendText(article, 'div', 'message-text', initialText);
  messages?.appendChild(article);
  messages?.scrollTo({ top: messages.scrollHeight, behavior: 'smooth' });
  return { article, text };
}

function safeSourceUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    const allowedHosts = new Set(['youtu.be', 'www.youtube.com', 'youtube.com']);
    return url.protocol === 'https:' && allowedHosts.has(url.hostname) ? url.href : null;
  } catch {
    return null;
  }
}

function renderSources(parent, sources) {
  const valid = (Array.isArray(sources) ? sources : [])
    .map((source) => ({ source, url: safeSourceUrl(source?.url) }))
    .filter(({ url }) => url);
  if (!valid.length) return;

  const wrapper = document.createElement('div');
  wrapper.className = 'sources';
  appendText(wrapper, 'div', 'sources-title', 'Sources');
  for (const { source, url } of valid) {
    const link = document.createElement('a');
    link.className = 'source-card';
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    appendText(link, 'span', 'source-title', source.title || source.playlist || 'ICT source');
    const detail = [source.playlist, source.timestamp].filter(Boolean).join(' · ');
    if (detail) appendText(link, 'span', 'source-meta', detail);
    if (typeof source.quote === 'string' && source.quote.trim()) {
      appendText(link, 'span', 'source-quote', `“${source.quote.trim()}”`);
    }
    wrapper.appendChild(link);
  }
  parent.appendChild(wrapper);
}

function renderSession(session) {
  entitlementVersion += 1;
  const signedIn = Boolean(session?.user && session?.access_token);
  if (gate) gate.hidden = signedIn;
  if (dashboard) dashboard.hidden = !signedIn;
  for (const label of userEmails) {
    label.textContent = signedIn ? (session.user.email || 'Signed in') : '';
  }
  if (!signedIn) resetConversation();
  else {
    for (const label of creditLabels) label.textContent = 'Checking allowance…';
    for (const label of planLabels) label.textContent = 'Checking…';
  }
  setStatus('');
  if (signedIn) questionInput?.focus();
}

function setComposerBusy(busy) {
  if (questionInput) questionInput.disabled = busy;
  if (submitButton) {
    submitButton.disabled = busy;
    submitButton.textContent = busy ? 'Searching…' : 'Ask';
  }
}

function fatalSetupError(message) {
  renderSession(null);
  setStatus(message, 'error');
  if (signInButton) signInButton.disabled = true;
}

async function boot() {
  if (!config?.supabaseUrl || !config?.supabasePublishableKey) {
    fatalSetupError('Sign-in is not configured. Please try again later.');
    return;
  }
  if (!globalThis.supabase?.createClient) {
    fatalSetupError('Sign-in service failed to load. Refresh and try again.');
    return;
  }

  const supabaseClient = globalThis.supabase.createClient(
    config.supabaseUrl,
    config.supabasePublishableKey,
    {
      auth: {
        flowType: 'pkce',
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    },
  );

  let controller;

  async function handleSession(session) {
    renderSession(session);
    if (!session?.user || !session?.access_token) return;
    const version = entitlementVersion;
    try {
      const entitlement = await controller.getEntitlement();
      if (version === entitlementVersion) renderEntitlement(entitlement);
    } catch (error) {
      if (version === entitlementVersion) renderEntitlement();
      if (/sign in required|invalid or expired session/i.test(error?.message || '')) renderSession(null);
    }
  }

  controller = createChatController({
    auth: supabaseClient.auth,
    location: globalThis.location,
    fetchImpl: globalThis.fetch.bind(globalThis),
    onSession: (session) => { void handleSession(session); },
  });

  signInButton?.addEventListener('click', async () => {
    signInButton.disabled = true;
    setStatus('Opening Google sign-in…');
    try {
      await controller.signIn();
    } catch (error) {
      signInButton.disabled = false;
      setStatus(error?.message || 'Could not start Google sign-in.', 'error');
    }
  });

  for (const button of signOutButtons) {
    button.addEventListener('click', async () => {
      for (const item of signOutButtons) item.disabled = true;
      setStatus('Signing out…');
      try {
        await controller.signOut();
      } catch (error) {
        setStatus(error?.message || 'Could not sign out. Try again.', 'error');
      } finally {
        for (const item of signOutButtons) item.disabled = false;
      }
    });
  }

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const question = questionInput?.value.trim() || '';
    if (!question) {
      setStatus('Enter a question first.', 'error');
      questionInput?.focus();
      return;
    }

    setStatus('Searching the ICT library…');
    setComposerBusy(true);
    appendMessage('user', question);
    const assistant = appendMessage('assistant');
    if (questionInput) questionInput.value = '';
    let streamed = false;

    try {
      const result = await controller.ask(question, (delta) => {
        streamed = true;
        assistant.text.textContent += delta;
        messages?.scrollTo({ top: messages.scrollHeight, behavior: 'smooth' });
      });
      if (!streamed) assistant.text.textContent = result.answer || 'No answer was returned.';
      renderSources(assistant.article, result.sources);
      renderEntitlement(result);
      setStatus('');
    } catch (error) {
      assistant.article.classList.add('error');
      assistant.text.textContent = error?.message || 'Something went wrong. Try again.';
      setStatus('Question failed. Please retry.', 'error');
      if (/sign in required|invalid or expired session/i.test(error?.message || '')) renderSession(null);
      else if (error?.status === 429) {
        // The quota display may be stale (e.g. exhausted in another tab).
        // Refresh the authoritative entitlement before the next attempt.
        try {
          const entitlement = await controller.getEntitlement();
          renderEntitlement(entitlement);
        } catch { /* entitlement refresh is best-effort */ }
      }
    } finally {
      setComposerBusy(false);
      questionInput?.focus();
    }
  });

  controller.watchSession();
  try {
    await controller.restoreSession();
  } catch (error) {
    fatalSetupError(error?.message || 'Could not restore your session.');
  }
}

boot();
