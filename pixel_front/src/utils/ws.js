class WSClient {
  constructor() {
    this.ws = null;
    this.listeners = {};
    this.url = null;
    this.reconnectAttempts = 0;
    this.maxReconnectDelay = 10000;
    this.manuallyClosed = false;
  }

  async connect(url) {
    this.url = url;
    this.manuallyClosed = false;
    try {
      // V2 requires this signed anonymous cookie before a socket is accepted.
      const response = await fetch('/api/v2/session', { credentials: 'same-origin' });
      if (!response.ok) throw new Error('无法创建匿名会话');
      this._open();
    } catch (error) {
      this.emit('error', error);
      this._scheduleReconnect();
    }
  }

  _open() {
    if (this.manuallyClosed || !this.url) return;
    this.ws = new WebSocket(this.url);
    this.ws.onopen = event => {
      this.reconnectAttempts = 0;
      this.emit('open', event);
    };
    this.ws.onmessage = event => {
      try {
        const message = JSON.parse(event.data);
        if (!message || typeof message.type !== 'string') return;
        this.emit(message.type, message);
        if (message.type === 'stats.updated') this.emit('stats', message.data);
        if (message.type === 'error') this.emit('server_error', message);
      } catch (error) {
        this.emit('error', error);
      }
    };
    this.ws.onclose = event => {
      this.emit('close', event);
      if (!this.manuallyClosed) this._scheduleReconnect();
    };
    this.ws.onerror = error => this.emit('error', error);
  }

  _scheduleReconnect() {
    if (this.manuallyClosed) return;
    const delay = Math.min(1000 * (2 ** this.reconnectAttempts), this.maxReconnectDelay);
    this.reconnectAttempts += 1;
    window.setTimeout(() => this.connect(this.url), delay);
  }

  send(type, data = {}, requestId = null) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    const payload = { type, data };
    if (requestId) payload.request_id = requestId;
    this.ws.send(JSON.stringify(payload));
    return true;
  }

  on(event, callback) {
    (this.listeners[event] ||= []).push(callback);
  }

  off(event, callback) {
    if (this.listeners[event]) this.listeners[event] = this.listeners[event].filter(item => item !== callback);
  }

  emit(event, value) {
    (this.listeners[event] || []).slice().forEach(callback => callback(value));
  }

  close() {
    this.manuallyClosed = true;
    if (this.ws) this.ws.close();
  }
}

export default new WSClient();
