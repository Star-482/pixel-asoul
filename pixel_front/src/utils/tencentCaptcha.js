const CAPTCHA_SCRIPT_ID = 'pixel-tencent-captcha-sdk';
const CAPTCHA_SCRIPT_URL = 'https://turing.captcha.qcloud.com/TJCaptcha.js';

let captchaConstructorPromise = null;

export class CaptchaCancelledError extends Error {
  constructor() {
    super('验证码已取消');
    this.name = 'CaptchaCancelledError';
  }
}

function loadTencentCaptcha() {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return Promise.reject(new Error('当前环境不支持验证码'));
  }
  if (typeof window.TencentCaptcha === 'function') {
    return Promise.resolve(window.TencentCaptcha);
  }
  if (captchaConstructorPromise) return captchaConstructorPromise;

  captchaConstructorPromise = new Promise((resolve, reject) => {
    const existing = document.getElementById(CAPTCHA_SCRIPT_ID);
    const script = existing || document.createElement('script');
    const resolveConstructor = () => {
      if (typeof window.TencentCaptcha === 'function') {
        resolve(window.TencentCaptcha);
      } else {
        reject(new Error('验证码脚本加载完成，但未找到 TencentCaptcha'));
      }
    };
    const rejectLoad = () => reject(new Error('验证码脚本加载失败，请检查网络后重试'));

    script.addEventListener('load', resolveConstructor, { once: true });
    script.addEventListener('error', rejectLoad, { once: true });
    if (!existing) {
      script.id = CAPTCHA_SCRIPT_ID;
      script.src = CAPTCHA_SCRIPT_URL;
      script.async = true;
      document.head.appendChild(script);
    }
  }).catch(error => {
    captchaConstructorPromise = null;
    throw error;
  });

  return captchaConstructorPromise;
}

export async function openTencentCaptcha(appId) {
  if (!appId) throw new Error('验证码应用未配置');
  const TencentCaptcha = await loadTencentCaptcha();

  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = callback => value => {
      if (settled) return;
      settled = true;
      callback(value);
    };
    const succeed = finish(resolve);
    const fail = finish(reject);

    try {
      const captcha = new TencentCaptcha(String(appId), result => {
        if (Number(result?.ret) === 0 && result?.ticket && result?.randstr) {
          succeed({ ticket: result.ticket, randstr: result.randstr });
          return;
        }
        if (Number(result?.ret) === 2) {
          fail(new CaptchaCancelledError());
          return;
        }
        fail(new Error(result?.errorMessage || '验证码未通过，请重试'));
      }, {
        userLanguage: 'zh-cn',
      });
      captcha.show();
    } catch (error) {
      fail(error instanceof Error ? error : new Error('验证码启动失败'));
    }
  });
}
