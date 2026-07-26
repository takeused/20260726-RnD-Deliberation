/**
 * Encrypt a self-contained HTML report into a single password-protected
 * index.html. The deployment directory must contain only the output file.
 *
 * Usage:
 *   node tools/protect_report.mjs <source.html> <output/index.html> <password>
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { randomBytes, webcrypto } from "node:crypto";

const [sourcePath, outputPath, password] = process.argv.slice(2);
if (!sourcePath || !outputPath || !password) {
  throw new Error("Usage: node tools/protect_report.mjs <source.html> <output/index.html> <password>");
}

const encoder = new TextEncoder();
const source = await readFile(sourcePath, "utf8");
const salt = randomBytes(16);
const iv = randomBytes(12);
const keyMaterial = await webcrypto.subtle.importKey(
  "raw", encoder.encode(password), "PBKDF2", false, ["deriveKey"],
);
const key = await webcrypto.subtle.deriveKey(
  { name: "PBKDF2", salt, iterations: 210_000, hash: "SHA-256" },
  keyMaterial,
  { name: "AES-GCM", length: 256 },
  false,
  ["encrypt"],
);
const cipher = await webcrypto.subtle.encrypt({ name: "AES-GCM", iv }, key, encoder.encode(source));
const toBase64 = (value) => Buffer.from(value).toString("base64");
const payload = JSON.stringify({
  salt: toBase64(salt),
  iv: toBase64(iv),
  cipher: toBase64(cipher),
});

const html = `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#12334a">
  <title>보호된 심의결과 보고서</title>
  <style>
    :root { color-scheme: light; --navy:#12334a; --teal:#08756f; --ink:#17212b; --muted:#5d6b76; --line:#d8e1e5; --bg:#eef3f4; --error:#a52525; }
    * { box-sizing:border-box; } body { min-height:100vh; margin:0; display:grid; place-items:center; background:linear-gradient(145deg,#e5eef0,#f7f8f7); color:var(--ink); font:16px/1.6 "Noto Sans KR","Malgun Gothic",system-ui,sans-serif; }
    main { width:min(100% - 32px,500px); padding:36px; background:#fff; border-top:6px solid var(--teal); box-shadow:0 14px 36px #12334a1a; }
    .kicker { margin:0 0 10px; color:var(--teal); font-size:13px; font-weight:800; letter-spacing:.08em; } h1 { margin:0; color:var(--navy); font-size:28px; line-height:1.3; text-wrap:balance; }
    p { color:var(--muted); } label { display:block; margin:26px 0 7px; color:var(--ink); font-weight:800; } input { width:100%; min-height:48px; padding:11px 13px; border:1px solid #93a5ad; border-radius:4px; color:var(--ink); font:inherit; } input:focus-visible, button:focus-visible { outline:3px solid #4d9dc2; outline-offset:2px; }
    button { width:100%; min-height:48px; margin-top:14px; border:0; border-radius:4px; background:var(--navy); color:#fff; font:inherit; font-weight:800; cursor:pointer; } button:hover { background:#0d506f; } button:disabled { cursor:wait; opacity:.65; }
    #message { min-height:24px; margin:12px 0 0; color:var(--error); font-size:14px; } .note { margin-top:26px; padding-top:16px; border-top:1px solid var(--line); font-size:13px; }
    #report { position:fixed; inset:0; width:100%; height:100%; border:0; background:#fff; }
    [hidden] { display:none !important; }
  </style>
</head>
<body>
  <main id="unlock-panel">
    <p class="kicker">접근 제한 문서</p>
    <h1>국가연구개발사업 심의결과 보고서</h1>
    <p>배포본은 암호화되어 있습니다. 권한을 부여받은 경우에만 암호를 입력하세요.</p>
    <form id="unlock-form">
      <label for="password">문서 암호</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button id="unlock-button" type="submit">보고서 열기</button>
      <p id="message" role="status" aria-live="polite"></p>
    </form>
    <p class="note">복호화는 이 브라우저에서만 수행됩니다. 암호는 배포 링크와 분리해 전달하세요.</p>
  </main>
  <iframe id="report" title="심의결과 보고서" sandbox="allow-same-origin" hidden></iframe>
  <script>
    const payload = ${payload};
    const fromBase64 = (value) => Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
    const form = document.querySelector('#unlock-form');
    const input = document.querySelector('#password');
    const button = document.querySelector('#unlock-button');
    const message = document.querySelector('#message');
    const report = document.querySelector('#report');
    const unlockPanel = document.querySelector('#unlock-panel');

    const bindInternalNavigation = () => {
      const reportDocument = report.contentDocument;
      if (!reportDocument) return;
      reportDocument.addEventListener('click', (event) => {
        const link = event.target?.closest?.('a[href^="#"]');
        if (!link) return;
        event.preventDefault();
        const targetId = decodeURIComponent(link.getAttribute('href').slice(1));
        const target = targetId
          ? reportDocument.getElementById(targetId)
          : reportDocument.documentElement;
        if (!target) return;
        const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
        if (target !== reportDocument.documentElement) {
          const hadTabindex = target.hasAttribute('tabindex');
          if (!hadTabindex) target.setAttribute('tabindex', '-1');
          target.focus({ preventScroll: true });
          if (!hadTabindex) {
            target.addEventListener('blur', () => target.removeAttribute('tabindex'), { once: true });
          }
        }
      }, true);
    };
    report.addEventListener('load', bindInternalNavigation);

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      button.disabled = true;
      message.textContent = '암호를 확인하는 중…';
      try {
        const keyMaterial = await crypto.subtle.importKey('raw', new TextEncoder().encode(input.value), 'PBKDF2', false, ['deriveKey']);
        const key = await crypto.subtle.deriveKey(
          { name:'PBKDF2', salt:fromBase64(payload.salt), iterations:210000, hash:'SHA-256' },
          keyMaterial, { name:'AES-GCM', length:256 }, false, ['decrypt'],
        );
        const plain = await crypto.subtle.decrypt({ name:'AES-GCM', iv:fromBase64(payload.iv) }, key, fromBase64(payload.cipher));
        report.srcdoc = new TextDecoder().decode(plain);
        input.value = '';
        unlockPanel.hidden = true;
        report.hidden = false;
      } catch {
        message.textContent = '암호가 일치하지 않거나 문서가 손상되었습니다. 다시 확인하세요.';
        input.select();
        button.disabled = false;
      }
    });
  </script>
</body>
</html>`;

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, html, "utf8");
console.log(`Encrypted report written: ${outputPath}`);
