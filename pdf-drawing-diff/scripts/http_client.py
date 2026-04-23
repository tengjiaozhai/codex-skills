"""
内网 newapi 网关兼容：用 urllib 发 OpenAI 格式 chat/completions 与 responses。

背景：部分环境下 httpx/httpcore 对 POST /v1/chat/completions 会触发
      SSLEOFError，而同机 urllib 对同域 HTTPS 正常（TLS 栈/协商差异）。
"""
from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from typing import Any


def normalize_openai_base_url(url: str) -> str:
    u = url.rstrip("/")
    if u.endswith("/v1"):
        return u
    return u + "/v1"


def _env_ssl_verify() -> bool:
    return os.getenv("SSL_VERIFY", "1").strip() not in (
        "0",
        "false",
        "False",
        "no",
    )


def _ssl_context(verify: bool, tls12_only: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if tls12_only:
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        except (AttributeError, ValueError):
            pass
    if os.getenv("TINNO_SSL_LEGACY", "0").strip() in ("1", "true", "True", "yes"):
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        except (ssl.SSLError, ValueError):
            pass
    return ctx


def _is_transient_ssl_or_net(err: BaseException) -> bool:
    if isinstance(err, ssl.SSLError):
        return True
    if isinstance(err, (TimeoutError, ConnectionResetError, BrokenPipeError, OSError)):
        return True
    if isinstance(err, urllib.error.URLError) and err.reason is not None:
        if isinstance(err.reason, ssl.SSLError):
            return True
        msg = str(err.reason).upper()
        if "SSL" in msg or "EOF" in msg or "RESET" in msg:
            return True
    return False


def chat_completions_urllib(
    base_url_v1: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    timeout: float = 300.0,
    verify_ssl: bool | None = None,
    tls12_only: bool | None = None,
) -> dict[str, Any]:
    if verify_ssl is None:
        verify_ssl = _env_ssl_verify()
    if tls12_only is None:
        tls12_only = os.getenv("TINNO_HTTP_TLS12_ONLY", "0").strip() in (
            "1",
            "true",
            "True",
            "yes",
        )

    url = base_url_v1.rstrip("/") + "/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "pdf-drawing-diff-skill/1.0",
            "Accept": "application/json",
        },
    )
    ctx = _ssl_context(verify_ssl, tls12_only)
    retries = max(1, int(os.getenv("TINNO_HTTP_RETRIES", "4")))
    base_delay = float(os.getenv("TINNO_HTTP_RETRY_DELAY", "0.6"))
    last_err: BaseException | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:2000]
            raise RuntimeError(f"HTTP {e.code}: {err_body}") from e
        except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt + 1 < retries and _is_transient_ssl_or_net(e):
                time.sleep(base_delay * (2**attempt))
                continue
            raise
    assert last_err is not None
    raise last_err


def message_content(data: dict[str, Any]) -> str:
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"无法解析响应: {repr(data)[:500]}") from e


def responses_urllib(
    base_url_v1: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    timeout: float = 300.0,
    verify_ssl: bool | None = None,
    tls12_only: bool | None = None,
) -> dict[str, Any]:
    if verify_ssl is None:
        verify_ssl = _env_ssl_verify()
    if tls12_only is None:
        tls12_only = os.getenv("TINNO_HTTP_TLS12_ONLY", "0").strip() in (
            "1",
            "true",
            "True",
            "yes",
        )

    url = base_url_v1.rstrip("/") + "/responses"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "pdf-drawing-diff-skill/1.0",
            "Accept": "application/json",
        },
    )
    ctx = _ssl_context(verify_ssl, tls12_only)
    retries = max(1, int(os.getenv("TINNO_HTTP_RETRIES", "4")))
    base_delay = float(os.getenv("TINNO_HTTP_RETRY_DELAY", "0.6"))
    last_err: BaseException | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:2000]
            raise RuntimeError(f"HTTP {e.code}: {err_body}") from e
        except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt + 1 < retries and _is_transient_ssl_or_net(e):
                time.sleep(base_delay * (2**attempt))
                continue
            raise
    assert last_err is not None
    raise last_err


def response_output_text(data: dict[str, Any]) -> str:
    err = data.get("error")
    if err is not None:
        raise RuntimeError(f"Responses API error: {err!r}")
    ot = data.get("output_text")
    if isinstance(ot, str) and ot.strip():
        return ot
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for c in item.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "output_text":
                    t = c.get("text")
                    if t:
                        parts.append(str(t))
        elif item.get("type") == "output_text":
            t = item.get("text")
            if t:
                parts.append(str(t))
    return "".join(parts)


def responses_requests(
    base_url_v1: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    timeout: float = 300.0,
) -> dict[str, Any]:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    url = base_url_v1.rstrip("/") + "/responses"
    verify = _env_ssl_verify()
    session = requests.Session()
    retries = Retry(
        total=max(1, int(os.getenv("TINNO_HTTP_RETRIES", "4"))),
        backoff_factor=float(os.getenv("TINNO_HTTP_RETRY_DELAY", "0.6")),
        status_forcelist=(502, 503, 504),
        allowed_methods=("POST",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    r = session.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "pdf-drawing-diff-skill/1.1-requests",
            "Accept": "application/json",
        },
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=timeout,
        verify=verify,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:2000]}")
    return r.json()


def responses_with_fallback(
    base_url_v1: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    timeout: float = 300.0,
) -> dict[str, Any]:
    insecure_first = not _env_ssl_verify()
    base_combos = [
        (True, False),
        (True, True),
        (False, False),
        (False, True),
    ]
    combos = (
        [(False, False), (False, True), (True, False), (True, True)]
        if insecure_first
        else base_combos
    )
    last: Exception | None = None
    for verify, tls12 in combos:
        try:
            return responses_urllib(
                base_url_v1,
                api_key,
                payload,
                timeout=timeout,
                verify_ssl=verify,
                tls12_only=tls12,
            )
        except Exception as e:
            last = e
            continue
    if os.getenv("TINNO_HTTP_NO_REQUESTS", "0").strip() not in ("1", "true", "yes"):
        try:
            return responses_requests(base_url_v1, api_key, payload, timeout=timeout)
        except ImportError as e:
            if last is not None:
                raise last from e
            raise
        except Exception as e:
            last = e
    assert last is not None
    raise last


def chat_completions_requests(
    base_url_v1: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    timeout: float = 300.0,
) -> dict[str, Any]:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    url = base_url_v1.rstrip("/") + "/chat/completions"
    verify = _env_ssl_verify()
    session = requests.Session()
    retries = Retry(
        total=max(1, int(os.getenv("TINNO_HTTP_RETRIES", "4"))),
        backoff_factor=float(os.getenv("TINNO_HTTP_RETRY_DELAY", "0.6")),
        status_forcelist=(502, 503, 504),
        allowed_methods=("POST",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    r = session.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "pdf-drawing-diff-skill/1.1-requests",
            "Accept": "application/json",
        },
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=timeout,
        verify=verify,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:2000]}")
    return r.json()


def chat_completions_with_fallback(
    base_url_v1: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    timeout: float = 300.0,
) -> dict[str, Any]:
    insecure_first = not _env_ssl_verify()
    base_combos = [
        (True, False),
        (True, True),
        (False, False),
        (False, True),
    ]
    combos = (
        [(False, False), (False, True), (True, False), (True, True)]
        if insecure_first
        else base_combos
    )
    last: Exception | None = None
    for verify, tls12 in combos:
        try:
            return chat_completions_urllib(
                base_url_v1,
                api_key,
                payload,
                timeout=timeout,
                verify_ssl=verify,
                tls12_only=tls12,
            )
        except Exception as e:
            last = e
            continue
    if os.getenv("TINNO_HTTP_NO_REQUESTS", "0").strip() not in ("1", "true", "yes"):
        try:
            return chat_completions_requests(base_url_v1, api_key, payload, timeout=timeout)
        except ImportError as e:
            if last is not None:
                raise last from e
            raise
        except Exception as e:
            last = e
    assert last is not None
    raise last


def strip_thinking_tags(text: str) -> str:
    text = re.sub(
        r"<redacted_thinking>[\s\S]*?</redacted_thinking>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _normalize_vlm_backend_name(name: str | None) -> str:
    v = (name or "").strip().lower()
    if v in ("chat", "completions", "chat_completions", "chat-completions", "chat/completions"):
        return "chat"
    if v in ("responses", "response"):
        return "responses"
    return "auto"


def infer_vlm_backend(model: str, preferred: str | None = None) -> str:
    pref = _normalize_vlm_backend_name(preferred)
    if pref in ("chat", "responses"):
        return pref
    m = (model or "").strip().lower()
    if not m:
        return "responses"

    chat_hints = (
        "qwen",
        "qvq",
        "internvl",
        "minicpm",
        "glm",
        "claude",
        "gemini",
    )
    if any(k in m for k in chat_hints):
        return "chat"

    responses_hints = (
        "gpt-5",
        "o1",
        "o3",
        "o4",
    )
    if any(k in m for k in responses_hints):
        return "responses"

    return "responses"


def chat_completion_text(
    base_url_v1: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1000,
    timeout: float = 300.0,
    strip_thinking: bool = True,
) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = chat_completions_with_fallback(base_url_v1, api_key, payload, timeout=timeout)
    text = message_content(data)
    if strip_thinking:
        text = strip_thinking_tags(text)
    return text


def chat_completion_from_payload(
    base_url_v1: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    timeout: float = 600.0,
    strip_thinking: bool = True,
) -> str:
    data = chat_completions_with_fallback(base_url_v1, api_key, payload, timeout=timeout)
    text = message_content(data)
    if strip_thinking:
        text = strip_thinking_tags(text)
    return text


def _chat_content_part_to_responses_block(part: dict[str, Any]) -> dict[str, Any] | None:
    ptype = part.get("type")
    if ptype == "text":
        t = part.get("text", "")
        if not t:
            return None
        return {"type": "input_text", "text": t}
    if ptype == "image_url":
        iu = part.get("image_url", {})
        url = iu if isinstance(iu, str) else (iu.get("url") if isinstance(iu, dict) else "")
        if not url:
            return None
        block_kind = os.getenv("TINNO_RESPONSES_IMAGE_BLOCK", "input_image").strip()
        if block_kind == "image_url":
            return {"type": "image_url", "image_url": {"url": url}}
        return {"type": "input_image", "image_url": url}
    return None


def chat_messages_to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue
        blocks: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            b = _chat_content_part_to_responses_block(part)
            if b is not None:
                blocks.append(b)
        if blocks:
            out.append({"role": role, "content": blocks})
    return out


def chat_payload_to_responses_body(payload: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": payload["model"],
        "input": chat_messages_to_responses_input(payload["messages"]),
    }
    if "temperature" in payload:
        body["temperature"] = payload["temperature"]
    mt = payload.get("max_output_tokens", payload.get("max_tokens"))
    if mt is not None:
        body["max_output_tokens"] = int(mt)
    return body


def response_completion_from_payload(
    base_url_v1: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    timeout: float = 600.0,
    strip_thinking: bool = True,
) -> str:
    model = str(payload.get("model", "") or "")
    preferred = os.getenv("VLM_API_STYLE", os.getenv("VL_BACKEND", "auto"))
    backend = infer_vlm_backend(model, preferred)
    pref_norm = _normalize_vlm_backend_name(preferred)
    auto_mode = pref_norm == "auto"

    def _run_chat() -> str:
        return chat_completion_from_payload(
            base_url_v1, api_key, payload, timeout=timeout, strip_thinking=strip_thinking
        )

    def _run_responses() -> str:
        rpayload = chat_payload_to_responses_body(payload)
        data = responses_with_fallback(base_url_v1, api_key, rpayload, timeout=timeout)
        text = response_output_text(data)
        if strip_thinking:
            text = strip_thinking_tags(text)
        return text

    if backend == "chat":
        try:
            return _run_chat()
        except Exception as e1:
            if not auto_mode:
                raise
            try:
                return _run_responses()
            except Exception as e2:
                raise RuntimeError(
                    f"chat/completions 与 responses 均失败。chat err={e1}; responses err={e2}"
                ) from e2

    try:
        return _run_responses()
    except Exception as e1:
        if not auto_mode:
            raise
        try:
            return _run_chat()
        except Exception as e2:
            raise RuntimeError(
                f"responses 与 chat/completions 均失败。responses err={e1}; chat err={e2}"
            ) from e2
