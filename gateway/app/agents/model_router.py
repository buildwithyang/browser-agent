"""分层模型路由:按 prompt 字符长度把请求路由到不同的 {url, key, model}。

配置是一个 map {阈值 -> modelInfo} 外加必填的 `default` 兜底层。阈值是该层能
容纳的最大 prompt 字符数;对长度为 L 的 prompt,选「阈值 >= L 的最小那层」,
L 超过所有阈值(或只配了 default)时用 `default`。每层有独立的 url/key/model,
可指向不同厂商。
"""

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelTier:
    """一个路由层:一个 OpenAI 兼容 endpoint + model id。

    max_chars 是该层能容纳的最大 prompt 字符数;None 表示 `default` 兜底层(无上限)。
    url / key 可为空字符串——为空时不传给 OpenAI client,回退 SDK 默认(如本地 Ollama)。
    """

    model: str
    url: str = ""
    key: str = ""
    max_chars: int | None = None  # None => default/兜底层


class ModelRouter:
    """按 prompt 长度在若干 ModelTier 间路由。"""

    def __init__(self, default: ModelTier, tiers: list[ModelTier] | None = None) -> None:
        if default.max_chars is not None:
            raise ValueError("default tier must not carry a threshold (max_chars)")
        # 升序,便于线性匹配「容得下的最小层」。
        self._tiers = sorted(tiers or [], key=lambda t: t.max_chars or 0)
        self._default = default

    @property
    def default_model(self) -> str:
        """兜底层 model id(用于记录指标/日志)。"""
        return self._default.model

    def pick(self, prompt_len: int) -> ModelTier:
        for tier in self._tiers:
            # max_chars can be None (though tiers should normally have numeric thresholds).
            # Skip tiers without a numeric threshold to avoid comparing int with None.
            if tier.max_chars is None:
                continue
            if prompt_len <= tier.max_chars:
                return tier
        return self._default

    @classmethod
    def from_json(cls, raw: str) -> "ModelRouter":
        """解析 AGENT_BRIDGE_MODELS 的 JSON。非法配置抛 ValueError(信息清晰)。"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"AGENT_BRIDGE_MODELS is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("AGENT_BRIDGE_MODELS must be a JSON object {threshold: {url,key,model}}")
        if "default" not in data:
            raise ValueError('AGENT_BRIDGE_MODELS must include a "default" tier (the fallback model)')

        default: ModelTier | None = None
        tiers: list[ModelTier] = []
        for key, info in data.items():
            if not isinstance(info, dict):
                raise ValueError(f'AGENT_BRIDGE_MODELS["{key}"] must be an object with url/key/model')
            model = str(info.get("model", "")).strip()
            if not model:
                raise ValueError(f'AGENT_BRIDGE_MODELS["{key}"] is missing a non-empty "model"')
            url = str(info.get("url", "") or "").strip()
            api_key = str(info.get("key", "") or "").strip()

            if key == "default":
                default = ModelTier(model=model, url=url, key=api_key, max_chars=None)
                continue
            try:
                threshold = int(key)
            except (TypeError, ValueError):
                raise ValueError(
                    f'AGENT_BRIDGE_MODELS threshold "{key}" must be a positive integer or "default"'
                ) from None
            if threshold <= 0:
                raise ValueError(f'AGENT_BRIDGE_MODELS threshold "{key}" must be a positive integer')
            tiers.append(ModelTier(model=model, url=url, key=api_key, max_chars=threshold))

        assert default is not None  # guaranteed by the "default" membership check above
        return cls(default=default, tiers=tiers)
