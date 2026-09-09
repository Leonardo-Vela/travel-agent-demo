import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import os

from dotenv import load_dotenv
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

load_dotenv(Path(__file__).resolve().parent / ".env")

try:
    from .token_usage import log_token_usage
except ImportError:  # pragma: no cover - top-level import fallback
    from token_usage import log_token_usage


MODULE_DIR = Path(__file__).resolve().parent
# runtime_config.json is kept at the genai_core project root (outside the
# importable package), i.e. two levels up from this module in src/genai_core/.
PACKAGE_ROOT = MODULE_DIR.parents[1]
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "runtime_config.json"
PROXY_BYPASS_SUFFIXES = (
    ".intranet.commerzbank.com",
    ".intranet.commerzbank.de",
)


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _decode_base64_config_secrets(cfg: dict[str, Any]) -> dict[str, Any]:
    if cfg.get("secret_fields_encoding") != "base64":
        return cfg
    for key in cfg.get("encoded_secret_fields") or ():
        value = cfg.get(key)
        if value:
            cfg[key] = base64.b64decode(str(value).encode("ascii"), validate=True).decode("utf-8")
    cfg["token_secrets_are_base64"] = False
    return cfg


def load_runtime_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    selected = Path(path).expanduser()
    if not selected.exists():
        return {
            "_config_path": str(selected),
            "token_verify_tls": True,
            "llm_chat_verify_tls": True,
            "langsmith_tracing": False,
        }
    with selected.open("r", encoding="utf-8") as file:
        cfg = json.load(file)
    if not isinstance(cfg, dict):
        raise RuntimeError(f"Runtime config must be a JSON object: {selected}")
    cfg["_config_path"] = str(selected)
    _decode_base64_config_secrets(cfg)
    cfg["token_verify_tls"] = _to_bool(cfg.get("token_verify_tls"), default=True)
    cfg["llm_chat_verify_tls"] = _to_bool(cfg.get("llm_chat_verify_tls"), default=True)
    return cfg


def _normalize_proxy_url(proxy_url: str) -> str:
    value = proxy_url.strip()
    if not value:
        return ""
    return value if "://" in value else f"http://{value}"


def _inject_proxy_credentials(proxy_url: str, username: str, password: str) -> str:
    if not proxy_url:
        return ""
    parsed = urllib.parse.urlsplit(_normalize_proxy_url(proxy_url))
    host_part = parsed.netloc.rsplit("@", 1)[-1]
    if not username and not password:
        return urllib.parse.urlunsplit(parsed)
    user_enc = urllib.parse.quote(username, safe="")
    pass_enc = urllib.parse.quote(password, safe="")
    return urllib.parse.urlunsplit(
        (parsed.scheme, f"{user_enc}:{pass_enc}@{host_part}", parsed.path, parsed.query, parsed.fragment)
    )


def _set_env_if_configured(name: str, value: Any, *, overwrite: bool = True) -> None:
    text = str(value or "").strip()
    if not text:
        return
    if overwrite or not os.environ.get(name):
        os.environ[name] = text


def configure_langsmith_from_runtime_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Configure LangSmith tracing/proxy/TLS from the shared runtime config.

    The legacy runtime file is optional; if it does not exist we simply skip the
    local-auth setup and let the OpenAI environment variables drive the backend.
    """

    selected = Path(config_path).expanduser()
    if not selected.exists():
        return {"_config_path": str(selected), "langsmith_tracing": False}

    cfg = load_runtime_config(config_path)

    if not _to_bool(cfg.get("langsmith_tracing"), default=False):
        return cfg

    _set_env_if_configured("LANGSMITH_TRACING", "true")
    _set_env_if_configured("LANGSMITH_ENDPOINT", cfg.get("langsmith_endpoint"))
    _set_env_if_configured("LANGSMITH_API_KEY", cfg.get("langsmith_api_key"))
    _set_env_if_configured("LANGSMITH_PROJECT", cfg.get("langsmith_project"))
    _set_env_if_configured("LANGSMITH_WORKSPACE_ID", cfg.get("langsmith_workspace_id"))
    _set_env_if_configured("LANGSMITH_DISABLE_RUN_COMPRESSION", cfg.get("langsmith_disable_run_compression"))

    no_proxy = str(
        cfg.get("langsmith_no_proxy")
        or "localhost,127.0.0.1,.intranet.commerzbank.com,.intranet.commerzbank.de"
    )
    _set_env_if_configured("NO_PROXY", no_proxy)
    _set_env_if_configured("no_proxy", no_proxy)

    if _to_bool(cfg.get("langsmith_bypass_proxy"), default=False):
        endpoint_host = urllib.parse.urlparse(
            str(cfg.get("langsmith_endpoint") or "https://api.smith.langchain.com")
        ).hostname
        if endpoint_host and endpoint_host not in os.environ.get("NO_PROXY", ""):
            os.environ["NO_PROXY"] = f"{os.environ.get('NO_PROXY', '')},{endpoint_host}".strip(",")
            os.environ["no_proxy"] = os.environ["NO_PROXY"]
    else:
        proxy_url = str(cfg.get("langsmith_proxy_url") or cfg.get("proxy_url") or "")
        proxy_username = str(cfg.get("langsmith_proxy_username") or cfg.get("proxy_username") or "")
        proxy_password = str(cfg.get("langsmith_proxy_password") or cfg.get("proxy_password") or "")
        resolved_proxy = _inject_proxy_credentials(proxy_url, proxy_username, proxy_password)
        if resolved_proxy:
            _set_env_if_configured("HTTP_PROXY", resolved_proxy)
            _set_env_if_configured("HTTPS_PROXY", resolved_proxy)
            _set_env_if_configured("http_proxy", resolved_proxy)
            _set_env_if_configured("https_proxy", resolved_proxy)

    ca_bundle = str(cfg.get("langsmith_ca_bundle") or "").strip()
    if ca_bundle:
        _set_env_if_configured("SSL_CERT_FILE", ca_bundle)
        _set_env_if_configured("REQUESTS_CA_BUNDLE", ca_bundle)

    if not _to_bool(cfg.get("langsmith_verify_tls"), default=True):
        _patch_langsmith_tls_verification(
            str(cfg.get("langsmith_endpoint") or "https://api.smith.langchain.com")
        )

    return cfg


def _read_openai_secret_from_streamlit() -> str:
    """Read OpenAI credentials from Streamlit secrets when available."""

    try:
        import streamlit as st
    except Exception:
        return ""

    try:
        value = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        return ""
    return str(value or "").strip()


def _read_openai_model_from_streamlit() -> str:
    """Read the model name from Streamlit secrets when available."""

    try:
        import streamlit as st
    except Exception:
        return ""

    try:
        value = st.secrets.get("OPENAI_MODEL", "")
    except Exception:
        return ""
    return str(value or "").strip()


def _resolve_openai_credentials() -> tuple[str, str]:
    """Return the effective OpenAI key and model, covering env and Streamlit secrets."""

    api_key = (os.getenv("OPENAI_API_KEY") or _read_openai_secret_from_streamlit() or "").strip()
    model_name = (os.getenv("OPENAI_MODEL") or _read_openai_model_from_streamlit() or "gpt-4o-mini").strip()
    return api_key, model_name


def bootstrap_openai(
    *,
    temperature: float = 0.0,
    max_completion_tokens: int = 800,
    model_name: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
):
    """Create an OpenAI-backed LangChain chat model.

    This is the preferred backend for the workshop, while still keeping the
    same ``bootstrap_local_genai`` surface used by the graph.
    """

    resolved_api_key, resolved_model = _resolve_openai_credentials()
    if api_key:
        resolved_api_key = api_key.strip() or resolved_api_key
    if model_name:
        resolved_model = model_name.strip() or resolved_model
    if not resolved_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to Streamlit secrets or export it in your environment before "
            "using the OpenAI backend."
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=resolved_model,
        temperature=temperature,
        max_tokens=max_completion_tokens,
        api_key=resolved_api_key,
        base_url=base_url or os.getenv("OPENAI_BASE_URL"),
    )


def bootstrap_local_genai(
    *,
    temperature: float = 0.0,
    max_completion_tokens: int = 800,
    model_name: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
):
    """Return the configured chat model for the workshop.

    The app keeps calling ``bootstrap_local_genai`` exactly as before. The
    implementation internally swaps between the legacy local adapter and the
    OpenAI backend based on environment configuration.
    """

    backend = (os.getenv("LLM_BACKEND") or "").strip().lower()
    resolved_api_key, _ = _resolve_openai_credentials()
    if backend == "openai" or api_key is not None or resolved_api_key:
        return bootstrap_openai(
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
        )
    if backend == "local":
        return LocalGenAIChatModel(
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
        )
    raise RuntimeError(
        "OPENAI_API_KEY is not set. Add it to Streamlit secrets or export it in your environment before "
        "using the OpenAI backend."
    )


def _patch_langsmith_tls_verification(endpoint: str) -> None:
    """Disable TLS verification only for the configured LangSmith host."""

    host = (urllib.parse.urlparse(endpoint).hostname or "api.smith.langchain.com").lower()

    try:
        import requests
        import urllib3
    except Exception:
        return

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if getattr(requests.sessions.Session.request, "_local_genai_langsmith_tls_patch", False):
        return

    original_request = requests.sessions.Session.request

    def request_without_langsmith_tls_verify(self, method, url, **kwargs):
        target_host = (urllib.parse.urlparse(str(url)).hostname or "").lower()
        if target_host == host:
            kwargs["verify"] = False
        return original_request(self, method, url, **kwargs)

    request_without_langsmith_tls_verify._local_genai_langsmith_tls_patch = True
    requests.sessions.Session.request = request_without_langsmith_tls_verify


@dataclass
class TokenConfig:
    token_endpoint: str
    client_id: str
    client_secret: str
    username: str
    password: str
    proxy_url: str = ""
    proxy_username: str = ""
    proxy_password: str = ""
    verify_tls: bool = True
    ca_certificate_pem: str = ""
    timeout_seconds: int = 30


class TokenManager:
    def __init__(self, cfg: TokenConfig):
        self.cfg = cfg
        self._cached: Optional[dict[str, Any]] = None

    @classmethod
    def from_runtime_config(cls, cfg: dict[str, Any]) -> "TokenManager":
        missing = [
            key
            for key in ("token_endpoint", "token_client_id", "token_client_secret", "token_username", "token_password")
            if not str(cfg.get(key) or "").strip()
        ]
        if missing:
            raise RuntimeError("Missing token config fields: " + ", ".join(missing))
        return cls(
            TokenConfig(
                token_endpoint=str(cfg["token_endpoint"]),
                client_id=str(cfg["token_client_id"]).strip(),
                client_secret=str(cfg["token_client_secret"]),
                username=str(cfg["token_username"]).strip(),
                password=str(cfg["token_password"]),
                proxy_url=str(cfg.get("proxy_url") or ""),
                proxy_username=str(cfg.get("proxy_username") or ""),
                proxy_password=str(cfg.get("proxy_password") or ""),
                verify_tls=_to_bool(cfg.get("token_verify_tls"), default=True),
                ca_certificate_pem=str(cfg.get("token_ca_pem") or ""),
                timeout_seconds=int(cfg.get("token_timeout_seconds") or 30),
            )
        )

    def get_token(self, *, force: bool = False, safety_seconds: int = 120) -> str:
        if (
            not force
            and self._cached
            and time.time() < self._cached.get("create_time", 0) + self._cached.get("expires_in", 0) - safety_seconds
        ):
            return str(self._cached["access_token"])
        token_data = self._exchange_token()
        token_data["create_time"] = time.time()
        self._cached = token_data
        return str(token_data["access_token"])

    def _exchange_token(self) -> dict[str, Any]:
        payload = {
            "grant_type": "password",
            "client_id": self.cfg.client_id,
            "client_secret": self.cfg.client_secret,
            "username": self.cfg.username,
            "password": self.cfg.password,
        }
        req = urllib.request.Request(
            self.cfg.token_endpoint,
            data=urllib.parse.urlencode(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        opener = self._build_opener(self.cfg.token_endpoint)
        try:
            with opener.open(req, timeout=self.cfg.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Token request failed with HTTP {exc.code}: {body[:1200]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Token request connection failed: {exc}") from exc

        data = json.loads(body)
        if "error" in data:
            raise RuntimeError(f"Token request OAuth error: {data.get('error')} ({data.get('error_description')})")
        if not data.get("access_token"):
            raise RuntimeError("Token response does not contain access_token")
        return data

    def _build_opener(self, endpoint: str):
        host = (urllib.parse.urlparse(endpoint).hostname or "").lower()
        proxy_url = _inject_proxy_credentials(
            self.cfg.proxy_url.strip(),
            self.cfg.proxy_username.strip(),
            self.cfg.proxy_password,
        )
        normalized_proxy = _normalize_proxy_url(proxy_url)
        handlers = []
        if normalized_proxy:
            handlers.append(urllib.request.ProxyHandler({"http": normalized_proxy, "https": normalized_proxy}))
        elif any(host.endswith(suffix) for suffix in PROXY_BYPASS_SUFFIXES):
            handlers.append(urllib.request.ProxyHandler({}))

        if endpoint.lower().startswith("https://") and (not self.cfg.verify_tls or self.cfg.ca_certificate_pem.strip()):
            context = ssl.create_default_context() if self.cfg.verify_tls else ssl._create_unverified_context()
            if self.cfg.verify_tls and self.cfg.ca_certificate_pem.strip():
                context.load_verify_locations(cadata=self.cfg.ca_certificate_pem)
            handlers.append(urllib.request.HTTPSHandler(context=context))

        return urllib.request.build_opener(*handlers)


class LocalGenAIClient:
    def __init__(self, config_path: str | Path = DEFAULT_CONFIG_PATH):
        self.config = load_runtime_config(config_path)
        self.gateway_client = None
        self.token_manager = None
        self._opener = None

        openai_mode = bool(os.getenv("OPENAI_API_KEY")) or (os.getenv("LLM_BACKEND") or "").strip().lower() == "openai"
        if openai_mode:
            return

        gateway_enabled = _to_bool(
            self.config.get("llm_gateway_enabled")
            if self.config.get("llm_gateway_enabled") is not None
            else os.getenv("LLM_GATEWAY_ENABLED"),
            default=False,
        )
        if gateway_enabled:
            from .llm_gateway import LLMGatewayClient, gateway_config_from_runtime_config

            self.gateway_client = LLMGatewayClient(gateway_config_from_runtime_config(self.config))
            self.token_manager = None
            self._opener = None
        else:
            legacy_fields = [
                "token_endpoint",
                "token_client_id",
                "token_client_secret",
                "token_username",
                "token_password",
            ]
            if any(str(self.config.get(field) or "").strip() for field in legacy_fields):
                self.token_manager = TokenManager.from_runtime_config(self.config)
                self._opener = self._build_llm_opener()
            else:
                self.token_manager = None
                self._opener = None

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_completion_tokens: int = 1000,
    ) -> str:
        response = self.raw_chat(
            messages,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
        )
        choices = response.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(str(part.get("text") or part.get("content") or part) for part in content)
        return str(content or "")

    @log_token_usage
    def raw_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_completion_tokens: int = 1000,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Any = None,
        parallel_tool_calls: Optional[bool] = None,
    ) -> dict[str, Any]:
        if self.gateway_client is not None:
            return self.gateway_client.chat(
                messages,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                tools=tools,
                tool_choice=tool_choice,
                parallel_tool_calls=parallel_tool_calls,
            )

        if self.token_manager is None or self._opener is None:
            raise RuntimeError(
                "Legacy Local GenAI authentication is not configured. Set OPENAI_API_KEY or "
                "LLM_BACKEND=openai to use the OpenAI backend."
            )

        token = self.token_manager.get_token(
            safety_seconds=int(self.config.get("token_refresh_safety_seconds") or 300)
        )
        token_parameter = str(self.config.get("completion_token_parameter") or "max_completion_tokens")
        payload = {
            "messages": messages,
            "temperature": temperature,
            "top_p": float(self.config.get("top_p") or 1.0),
            token_parameter: int(max_completion_tokens),
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = parallel_tool_calls
        req = urllib.request.Request(
            url=str(self.config["llm_chat_endpoint"]),
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "Coba-ActivityID": f"urn:uuid:{uuid.uuid4()}",
            },
        )
        try:
            with self._opener.open(req, timeout=60) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in {401, 403, 500}:
                token = self.token_manager.get_token(force=True)
                req.add_header("Authorization", f"Bearer {token}")
                with self._opener.open(req, timeout=60) as response:
                    return json.loads(response.read().decode("utf-8", errors="replace"))
            raise RuntimeError(f"LLM chat failed with HTTP {exc.code}: {body[:2000]}") from exc

    def _build_llm_opener(self):
        endpoint = str(self.config.get("llm_chat_endpoint") or "")
        parsed = urllib.parse.urlparse(endpoint)
        host = (parsed.hostname or "").lower()
        proxy_url = _inject_proxy_credentials(
            str(self.config.get("proxy_url") or ""),
            str(self.config.get("proxy_username") or ""),
            str(self.config.get("proxy_password") or ""),
        )
        normalized_proxy = _normalize_proxy_url(proxy_url)

        if any(host.endswith(suffix) for suffix in PROXY_BYPASS_SUFFIXES):
            proxy_handler = urllib.request.ProxyHandler({})
        elif normalized_proxy:
            proxy_handler = urllib.request.ProxyHandler({"http": normalized_proxy, "https": normalized_proxy})
        else:
            proxy_handler = urllib.request.ProxyHandler()

        verify_tls = _to_bool(self.config.get("llm_chat_verify_tls"), default=True)
        context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
        ca_pem = str(self.config.get("llm_chat_ca_pem") or "")
        if verify_tls and ca_pem.strip():
            context.load_verify_locations(cadata=ca_pem)
        return urllib.request.build_opener(proxy_handler, urllib.request.HTTPSHandler(context=context))


def _message_to_openai(message: BaseMessage) -> dict[str, Any]:
    if isinstance(message, ToolMessage):
        payload: dict[str, Any] = {
            "role": "tool",
            "content": message.content,
            "tool_call_id": message.tool_call_id,
        }
        if message.name:
            payload["name"] = message.name
        return payload

    if isinstance(message, AIMessage):
        payload = {
            "role": "assistant",
            "content": message.content,
        }
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.get("id") or f"call_{uuid.uuid4().hex}",
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call.get("args", {}), ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        return payload

    role_map = {
        "human": "user",
        "system": "system",
    }
    return {
        "role": role_map.get(message.type, "user"),
        "content": message.content,
    }


class LocalGenAIChatModel(BaseChatModel):
    client: LocalGenAIClient
    temperature: float = 0.0
    max_completion_tokens: int = 1000

    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        *,
        temperature: float = 0.0,
        max_completion_tokens: int = 1000,
        **kwargs: Any,
    ):
        super().__init__(
            client=LocalGenAIClient(config_path),
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            **kwargs,
        )

    @property
    def _llm_type(self) -> str:
        return "local-genai-chat"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "endpoint": self.client.config.get("llm_chat_endpoint"),
            "temperature": self.temperature,
            "max_completion_tokens": self.max_completion_tokens,
        }

    def bind_tools(
        self,
        tools: list[Any],
        **kwargs: Any,
    ):
        formatted_tools = [convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=formatted_tools, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if stop:
            raise ValueError("This minimal local GenAI adapter does not implement stop sequences.")
        tools = kwargs.get("tools")
        response = self.client.raw_chat(
            [_message_to_openai(message) for message in messages],
            temperature=float(kwargs.get("temperature", self.temperature)),
            max_completion_tokens=int(kwargs.get("max_completion_tokens", self.max_completion_tokens)),
            tools=tools,
            tool_choice=kwargs.get("tool_choice"),
            parallel_tool_calls=kwargs.get("parallel_tool_calls"),
        )
        choices = response.get("choices") or []
        if not choices:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=""))])
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            content = ""
        tool_calls = msg.get("tool_calls") or []
        ai_kwargs: dict[str, Any] = {}
        if tool_calls:
            parsed_tool_calls = []
            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                parsed_tool_calls.append(
                    {
                        "id": tool_call.get("id") or f"call_{uuid.uuid4().hex}",
                        "name": function.get("name", ""),
                        "args": arguments,
                    }
                )
            ai_kwargs["tool_calls"] = parsed_tool_calls
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content, **ai_kwargs))])
