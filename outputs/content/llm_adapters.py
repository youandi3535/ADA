"""outputs.content.llm_adapters - LLM caller adapters for SlideContentGenerator.

Provides ready-to-use llm_caller functions matching:
    Callable[[system_prompt: str, user_prompt: str], str]

Supported backends:
    - make_ollama_caller    : Local Ollama server (qwen2.5:7b default - matches ADA stack)
    - make_anthropic_caller : Anthropic API (Claude)
    - make_openai_caller    : OpenAI-compatible (works with vLLM, llama.cpp server too)
    - make_ada_caller       : Wraps an ADA BaseAgent's _call_llm
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Optional


def make_ollama_caller(
    model: str = "qwen2.5:7b",
    base_url: str = "http://localhost:11434",
    *,
    temperature: float = 0.3,
    max_tokens: int = 800,
    timeout_sec: int = 120,
    num_gpu: int = 0,
    num_thread: int = 14,
) -> Callable[[str, str], str]:
    """Ollama HTTP /api/chat 호출 어댑터.

    Defaults match ADA's existing Ollama config (qwen2.5:7b, CPU-only on 14 threads).
    See api/routes/kb_search.py _ollama_answer_sync for reference.
    """
    base = base_url.rstrip("/")

    def caller(system_prompt: str, user_prompt: str) -> str:
        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": 0.9,
                    "num_gpu": num_gpu,
                    "num_thread": num_thread,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read())
            return data.get("message", {}).get("content", "") or ""
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return ""

    return caller


def make_openai_caller(
    model: str = "gpt-4o-mini",
    base_url: str = "https://api.openai.com/v1",
    api_key: Optional[str] = None,
    *,
    temperature: float = 0.3,
    max_tokens: int = 800,
    timeout_sec: int = 60,
) -> Callable[[str, str], str]:
    """OpenAI-compatible /v1/chat/completions 어댑터.

    vLLM, llama.cpp server, LM Studio, OpenRouter 등 호환 가능.
    """
    base = base_url.rstrip("/")

    def caller(system_prompt: str, user_prompt: str) -> str:
        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(f"{base}/chat/completions", data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read())
            choices = data.get("choices") or []
            if choices:
                return choices[0].get("message", {}).get("content", "") or ""
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            pass
        return ""

    return caller


def make_anthropic_caller(
    model: str = "claude-sonnet-4-6",
    api_key: Optional[str] = None,
    *,
    temperature: float = 0.3,
    max_tokens: int = 800,
) -> Callable[[str, str], str]:
    """Anthropic SDK 어댑터. anthropic 패키지 필요."""
    try:
        import anthropic
    except ImportError:

        def _noop(_s, _u):
            return ""

        return _noop

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def caller(system_prompt: str, user_prompt: str) -> str:
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            out = ""
            for blk in resp.content:
                if getattr(blk, "type", None) == "text":
                    out += blk.text
            return out
        except Exception:
            return ""

    return caller


def make_ada_caller(agent: Any) -> Callable[[str, str], str]:
    """ADA BaseAgent 의 _call_llm 을 동기 어댑터로 wrap.

    BaseAgent._call_llm 은 async — 동기 호출이 필요한 SlideContentGenerator
    를 위해 asyncio.run 으로 감쌈. agent 가 이미 event loop 안에 있으면 사용 X.
    """
    import asyncio

    def caller(system_prompt: str, user_prompt: str) -> str:
        try:
            coro = agent._call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=800,
                temperature=0.3,
            )
            return asyncio.run(coro) if not asyncio.get_event_loop().is_running() else ""
        except Exception:
            return ""

    return caller
