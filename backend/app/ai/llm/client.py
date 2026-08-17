"""LLMClient：DeepSeek（OpenAI 兼容）统一模型调用封装（architecture.md）。

职责：
- env 注入配置（DEEPSEEK_API_KEY / BASE_URL / MODEL），key 缺失时进入 fallback 模式
- 单次调用 ≤30s；429/5xx 指数退避重试（最多 3 次）
- JSON 输出模式 + 解析失败重试 1 次（输出格式异常）
- Token/成本追踪（token_tracker，）
- 同步 complete / 流式 stream 两种接口
"""
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.ai.llm.exceptions import (
    LLMFormatError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.ai.llm.token_tracker import get_token_tracker
from app.observability.tracer import record_llm_span

logger = logging.getLogger("careerai.ai.llm")

MODELS_YAML_PATH = Path(__file__).resolve().parent / "models.yaml"


@dataclass
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    latency_ms: int


def _escape_bare_newlines_in_strings(text: str) -> str:
    """把 JSON 字符串值内的裸换行转义为 ``\\n``（JSON 标准禁止字符串值内出现未转义换行）。

    GLM-4.6V-Flash 真实输出的 ``ocr_text`` 字符串值内含未转义裸换行，``json.loads`` 直接失败；
    本函数仅转义**字符串值内部**的 LF / CR / CRLF（结构外的换行是合法空白，保持不变），
    换行语义保留为 ``\\n``（不替换为空格、不删除、不拼接），保证下游 ``\\b`` 词边界 grounding 不劣化。
    """
    out: list[str] = []
    in_str = False
    escape = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if escape:
                out.append(ch)
                escape = False
            elif ch == "\\":
                out.append(ch)
                escape = True
            elif ch == '"':
                out.append(ch)
                in_str = False
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                # CRLF 折叠为单个换行；孤立 CR 也归一为换行
                if i + 1 < n and text[i + 1] == "\n":
                    out.append("\\n")
                    i += 1
                else:
                    out.append("\\n")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
        i += 1
    return "".join(out)


def _parse_json(text: str) -> dict | None:
    """宽松 JSON 解析：容忍 markdown 围栏与前后噪声。"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 去掉 ```json ... ``` 围栏
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 容忍字符串值内未转义裸换行（GLM-4.6V 真实输出 ocr_text 含裸换行，JSON 标准禁止）。
    # 仅作为 json.loads 失败后的兜底分支——正常 JSON 输入走上方快路径，路径零改动。
    tolerated = _escape_bare_newlines_in_strings(cleaned)
    if tolerated != cleaned:
        try:
            return json.loads(tolerated)
        except json.JSONDecodeError:
            pass
    # 提取首个平衡的 { ... } 块
    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                block = cleaned[start : i + 1]
                try:
                    return json.loads(block)
                except json.JSONDecodeError:
                    # 块内同样可能含裸换行（前后噪声场景），转义后重试一次
                    block_tolerated = _escape_bare_newlines_in_strings(block)
                    if block_tolerated != block:
                        try:
                            return json.loads(block_tolerated)
                        except json.JSONDecodeError:
                            return None
                    return None
    return None


@lru_cache(maxsize=1)
def _load_model_prices() -> dict:
    """读取 models.yaml（主/备模型 + 单价），env 覆盖模型名。"""
    import yaml

    settings = get_settings()
    raw = {}
    try:
        raw = yaml.safe_load(MODELS_YAML_PATH.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        logger.warning("models.yaml 缺失，使用空价格表")
    main = raw.get("main") or {}
    fallback = raw.get("fallback") or {}
    main_model = settings.DEEPSEEK_MODEL or main.get("model", "deepseek-v4-flash")
    fallback_model = settings.DEEPSEEK_FALLBACK_MODEL or fallback.get("model", main_model)
    prices: dict[str, dict] = {
        main_model: {
            "price_per_million_input": main.get("price_per_million_input", 2.0),
            "price_per_million_output": main.get("price_per_million_output", 4.0),
            "timeout_seconds": main.get("timeout_seconds", settings.DEEPSEEK_TIMEOUT_SECONDS),
            "max_retries": main.get("max_retries", settings.DEEPSEEK_MAX_RETRIES),
        },
        fallback_model: {
            "price_per_million_input": fallback.get("price_per_million_input", 1.0),
            "price_per_million_output": fallback.get("price_per_million_output", 2.0),
            "timeout_seconds": fallback.get("timeout_seconds", settings.DEEPSEEK_TIMEOUT_SECONDS),
            "max_retries": fallback.get("max_retries", 2),
        },
    }
    return prices


class LLMClient:
    """统一模型调用封装：超时 / 重试 / 错误映射 / 成本追踪（）。"""

    def __init__(self, settings=None) -> None:
        s = settings or get_settings()
        self.api_key = s.DEEPSEEK_API_KEY
        self.base_url = s.DEEPSEEK_BASE_URL
        self.model = s.DEEPSEEK_MODEL
        self.fallback_model = s.DEEPSEEK_FALLBACK_MODEL or s.DEEPSEEK_MODEL
        self.timeout = s.DEEPSEEK_TIMEOUT_SECONDS
        self.max_retries = s.DEEPSEEK_MAX_RETRIES
        self.temperature = s.DEEPSEEK_TEMPERATURE
        self.max_output_tokens = s.DEEPSEEK_MAX_OUTPUT_TOKENS
        self.tracker = get_token_tracker()
        self._prices = _load_model_prices()
        self._client = None

    @property
    def is_available(self) -> bool:
        """API key 缺失 → 不可用（调用方走规则模板/兜底输出，不崩溃）。"""
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise LLMUnavailableError("DEEPSEEK_API_KEY 未配置，无法调用 LLM")
            import openai

            self._client = openai.AsyncOpenAI(
                api_key=self.api_key, base_url=self.base_url, timeout=self.timeout
            )
        return self._client

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
        node_name: str = "llm",
    ) -> LLMResponse:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return await self._chat(
            messages=messages,
            json_mode=json_mode,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model,
            node_name=node_name,
        )

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
        node_name: str = "llm",
    ) -> dict:
        """JSON 模式调用；输出解析失败重试 1 次（输出格式异常）。

         真实 LLM 回归发现的缺陷修复：deepseek-v4-flash 在输出预算耗尽时
        （推理 token 消耗完或内容截断）会出现「空内容」或「残缺 JSON」
        （completion_tokens 触及 max_tokens 上限），导致首轮解析失败。
        重试时自动提高 max_tokens（上限 8192），避免截断导致整节点转规则兜底。
        """
        base_max = max_tokens or self.max_output_tokens
        resp = await self.complete(
            system_prompt,
            user_prompt,
            json_mode=True,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model,
            node_name=node_name,
        )
        data = _parse_json(resp.text)
        if data is not None:
            return data
        budget_exhausted = resp.completion_tokens >= base_max or not resp.text.strip()
        if not resp.text.strip():
            # 空内容 = 推理 token 耗尽预算（completion_tokens 触及上限），给更大余量
            retry_max = min(base_max * 4, 8192)
        elif resp.completion_tokens >= base_max:
            retry_max = min(base_max * 2, 8192)
        else:
            retry_max = base_max
        logger.warning(
            "llm_json_retry node=%s 首次输出非 JSON（tokens=%d/%d 空内容=%s），"
            "重试 1 次 max_tokens=%d",
            node_name, resp.completion_tokens, base_max, not resp.text.strip(), retry_max,
        )
        resp2 = await self.complete(
            system_prompt,
            user_prompt + "\n\n（重要：必须输出纯 JSON 对象，不要包含任何其他文字。）",
            json_mode=True,
            max_tokens=retry_max,
            temperature=temperature,
            model=model,
            node_name=f"{node_name}:json_retry",
        )
        data = _parse_json(resp2.text)
        if data is not None:
            return data
        raise LLMFormatError(f"{node_name}: LLM 输出无法解析为 JSON")

    async def _chat(
        self,
        messages: list[dict],
        *,
        json_mode: bool,
        max_tokens: int | None,
        temperature: float | None,
        model: str | None,
        node_name: str,
    ) -> LLMResponse:
        client = self._get_client()
        target_model = model or self.model
        last_error: Exception | None = None
        started = time.monotonic()
        for attempt in range(self.max_retries + 1):
            t0 = time.monotonic()
            try:
                kwargs: dict = {
                    "model": target_model,
                    "messages": messages,
                    "temperature": self.temperature if temperature is None else temperature,
                    "max_tokens": max_tokens or self.max_output_tokens,
                    "stream": False,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                # （QA-BUG-015 根治）：deepseek-v4-flash 默认推理，推理 token 计入
                # completion 上限会烧穿 4096 触发截断重试；禁用 thinking 后 reasoning 归零。
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                resp = await client.chat.completions.create(**kwargs)
                latency_ms = int((time.monotonic() - t0) * 1000)
                usage = getattr(resp, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                text = (resp.choices[0].message.content or "") if resp.choices else ""
                prices = self._prices.get(
                    target_model, self._prices.get(self.model, {})
                )
                cost = self.tracker.record(
                    model=target_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    price_per_million_input=prices.get("price_per_million_input", 0.0),
                    price_per_million_output=prices.get("price_per_million_output", 0.0),
                    latency_ms=latency_ms,
                )
                await record_llm_span(
                    name=node_name,
                    status="succeeded",
                    duration_ms=latency_ms,
                    tokens=prompt_tokens + completion_tokens,
                    cost=cost,
                )
                return LLMResponse(
                    text=text,
                    model=target_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_yuan=cost,
                    latency_ms=latency_ms,
                )
            except Exception as exc: # noqa: BLE001 统一错误映射
                last_error = exc
                if _is_retryable(exc):
                    backoff = min(2**attempt, 8) # 指数退避：1,2,4,8
                    logger.warning(
                        "llm_retry node=%s attempt=%d err=%s backoff=%ds",
                        node_name,
                        attempt + 1,
                        type(exc).__name__,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                break
            except BaseException: # noqa: BLE001 取消/超时（CancelledError 等 BaseException）：记录 failed 后继续抛出
                await record_llm_span(
                    name=node_name,
                    status="failed",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    tokens=0,
                    cost=0.0,
                    error_message="调用被取消（整图超时/任务取消）",
                )
                raise
        mapped = _map_error(last_error, node_name)
        await record_llm_span(
            name=node_name,
            status="failed",
            duration_ms=int((time.monotonic() - started) * 1000),
            tokens=0,
            cost=0.0,
            error_message=str(mapped),
        )
        raise mapped

    async def stream(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ):
        """流式接口（同步/流式两种接口；当前节点用 complete，流式预留给对话类场景）。"""
        client = self._get_client()
        stream = await client.chat.completions.create(
            model=model or self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=max_tokens or self.max_output_tokens,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta


def _is_retryable(exc: Exception) -> bool:
    """429 / 5xx / 网络错误可重试（重试策略）。"""
    import httpx
    import openai

    if isinstance(exc, (openai.RateLimitError, openai.APIConnectionError, httpx.TimeoutException)):
        return True
    if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
        return True
    return False


def _map_error(exc: Exception | None, node_name: str) -> Exception:
    import httpx
    import openai

    if exc is None:
        return LLMUnavailableError(f"{node_name}: LLM 调用失败（无错误详情）")
    if isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException)):
        return LLMTimeoutError(f"{node_name}: LLM 调用超时（>30s）")
    if isinstance(exc, openai.RateLimitError):
        return LLMRateLimitError(f"{node_name}: LLM 限流（429），重试后仍失败")
    if isinstance(exc, LLMFormatError):
        return exc
    return LLMUnavailableError(f"{node_name}: LLM 服务不可用（{type(exc).__name__}）")


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    return LLMClient()


class VisionClient:
    """GLM-4.6V-Flash 多模态视觉调用：简历图片/扫描件 OCR + 结构化提取。

    - 独立于 DeepSeek LLMClient（智谱 OpenAI 兼容接口，GLM_API_KEY / GLM_VISION_BASE_URL）；
    - image_url 消息（data URI）；复用 _is_retryable / _map_error 超时/重试/错误映射；
    - 返回模型原始文本（调用方解析 OCR 原文 + 结构化 JSON）。
    """

    def __init__(self, settings=None) -> None:
        s = settings or get_settings()
        self.api_key = s.GLM_API_KEY
        self.base_url = s.GLM_VISION_BASE_URL
        self.model = s.GLM_VISION_MODEL
        self.timeout = s.GLM_VISION_TIMEOUT_SECONDS
        self.max_retries = s.GLM_VISION_MAX_RETRIES
        self._client = None

    @property
    def is_available(self) -> bool:
        """GLM_API_KEY 缺失 → 不可用（图片/扫描件简历 mark_failed，不静默空画像）。"""
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise LLMUnavailableError("GLM_API_KEY 未配置，无法调用视觉模型")
            import openai

            self._client = openai.AsyncOpenAI(
                api_key=self.api_key, base_url=self.base_url, timeout=self.timeout
            )
        return self._client

    async def complete_vision(
        self,
        system_prompt: str,
        user_prompt: str,
        images: list[str],
        *,
        node_name: str = "vision",
    ) -> str:
        """多模态调用：返回模型文本（OCR 原文 + 结构化 JSON）。images 为 data URI 列表。"""
        client = self._get_client()
        content: list[dict] = [{"type": "text", "text": user_prompt}]
        for img in images:
            content.append({"type": "image_url", "image_url": {"url": img}})
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]
        last_error: Exception | None = None
        started = time.monotonic()
        for attempt in range(self.max_retries + 1):
            t0 = time.monotonic()
            try:
                resp = await client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    stream=False,
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                text = (resp.choices[0].message.content or "") if resp.choices else ""
                await record_llm_span(
                    name=node_name,
                    status="succeeded",
                    duration_ms=latency_ms,
                    tokens=0,
                    cost=0.0,
                )
                return text
            except Exception as exc: # noqa: BLE001 统一错误映射（与 _chat 一致）
                last_error = exc
                if _is_retryable(exc):
                    backoff = min(2**attempt, 8)
                    logger.warning(
                        "vision_retry node=%s attempt=%d err=%s backoff=%ds",
                        node_name, attempt + 1, type(exc).__name__, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                break
        mapped = _map_error(last_error, node_name)
        await record_llm_span(
            name=node_name,
            status="failed",
            duration_ms=int((time.monotonic() - started) * 1000),
            tokens=0,
            cost=0.0,
            error_message=str(mapped),
        )
        raise mapped


@lru_cache(maxsize=1)
def get_vision_client() -> VisionClient:
    return VisionClient()
