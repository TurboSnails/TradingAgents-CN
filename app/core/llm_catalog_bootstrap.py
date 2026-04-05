"""
启动时补充「自定义 OpenAI / MiniMax」与「GOOGLE_API_KEY 下的 Gemini」到 MongoDB，
并在 /api/config/llm 中注入合成条目，使下拉框能选到对应模型（无需手搓数据库）。
"""

import logging
import os
from typing import Any, Dict, List, Set, Tuple

from app.core.database import get_mongo_db
from app.utils.timezone import now_tz
from app.utils.api_key_utils import is_valid_api_key, normalize_secret_from_env

logger = logging.getLogger(__name__)


def env_has_custom_openai_compatible_key() -> bool:
    """环境变量中是否配置了可用的 OpenAI 兼容密钥（含 MiniMax 别名）。"""
    for k in (os.getenv("CUSTOM_OPENAI_API_KEY"), os.getenv("MINIMAX_API_KEY")):
        if is_valid_api_key(k):
            return True
    return False


def env_has_google_api_key() -> bool:
    """环境变量中是否配置了可用的 Google AI Studio / Gemini API Key。"""
    k = normalize_secret_from_env(os.getenv("GOOGLE_API_KEY"))
    return bool(k and is_valid_api_key(k))


_GOOGLE_GEMINI_DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"


_GEMINI_MODELS: List[Dict[str, Any]] = [
    {
        "model_name": "gemini-2.5-pro",
        "model_display_name": "Gemini 2.5 Pro",
        "description": "Google Gemini 旗舰（深度决策推荐）",
        "capability_level": 5,
        "suitable_roles": ["deep_analysis", "both"],
    },
    {
        "model_name": "gemini-2.5-flash",
        "model_display_name": "Gemini 2.5 Flash",
        "description": "Gemini 2.5 快速版",
        "capability_level": 3,
        "suitable_roles": ["quick_analysis", "deep_analysis", "both"],
    },
    {
        "model_name": "gemini-2.0-flash",
        "model_display_name": "Gemini 2.0 Flash",
        "description": "Gemini 2.0 Flash",
        "capability_level": 3,
        "suitable_roles": ["quick_analysis", "deep_analysis", "both"],
    },
    {
        "model_name": "gemini-1.5-pro",
        "model_display_name": "Gemini 1.5 Pro",
        "description": "Gemini 1.5 Pro",
        "capability_level": 4,
        "suitable_roles": ["deep_analysis", "both"],
    },
    {
        "model_name": "gemini-1.5-flash",
        "model_display_name": "Gemini 1.5 Flash",
        "description": "Gemini 1.5 Flash",
        "capability_level": 3,
        "suitable_roles": ["quick_analysis", "deep_analysis", "both"],
    },
]


def build_synthetic_google_llm_configs():
    """Mongo 未写入 Gemini 条目时，供 /api/config/llm 仍返回可选模型（与 MiniMax 合成逻辑一致）。"""
    from app.models.config import LLMConfig

    out: List[LLMConfig] = []
    for m in _GEMINI_MODELS:
        out.append(
            LLMConfig(
                provider="google",
                model_name=m["model_name"],
                model_display_name=m["model_display_name"],
                description=m.get("description") or "Google Gemini",
                api_base=_GOOGLE_GEMINI_DEFAULT_BASE,
                max_tokens=8192,
                temperature=0.7,
                timeout=180,
                retry_times=3,
                enabled=True,
                capability_level=int(m.get("capability_level", 3)),
                suitable_roles=list(m.get("suitable_roles", ["both"])),
                features=["tool_calling", "long_context", "vision"],
            )
        )
    return out


def get_resolved_custom_openai_base_url() -> str:
    b = (os.getenv("CUSTOM_OPENAI_BASE_URL") or os.getenv("MINIMAX_BASE_URL") or "").strip().rstrip("/")
    return b or "https://api.minimax.io/v1"


def build_synthetic_minimax_llm_configs():
    """内存中构造 MiniMax 模型条目（供 /api/config/llm 在 Mongo 未种子时仍能返回选项）。"""
    from app.models.config import LLMConfig

    base = get_resolved_custom_openai_base_url()
    out: List[LLMConfig] = []
    for m in _MINIMAX_MODELS:
        out.append(
            LLMConfig(
                provider="custom_openai",
                model_name=m["model_name"],
                model_display_name=m["model_display_name"],
                description=m.get("description") or "OpenAI 兼容（MiniMax）",
                api_base=base,
                max_tokens=8192,
                temperature=0.7,
                timeout=180,
                retry_times=3,
                enabled=True,
                capability_level=4 if m["model_name"] in ("MiniMax-M2.7", "MiniMax-M2.7-highspeed") else 3,
                suitable_roles=["both"],
                features=(
                    ["tool_calling", "long_context", "reasoning"]
                    if m["model_name"] in ("MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5")
                    else ["tool_calling", "long_context"]
                ),
            )
        )
    return out

_MINIMAX_MODELS: List[Dict[str, str]] = [
    {
        "model_name": "MiniMax-M2.7",
        "model_display_name": "MiniMax M2.7",
        "description": "MiniMax 官方 OpenAI 兼容模型（推荐）",
    },
    {
        "model_name": "MiniMax-M2.7-highspeed",
        "model_display_name": "MiniMax M2.7 高速",
        "description": "同 M2.7，更高输出速度",
    },
    {"model_name": "MiniMax-M2.5", "model_display_name": "MiniMax M2.5", "description": "MiniMax M2.5"},
    {"model_name": "MiniMax-M2", "model_display_name": "MiniMax M2", "description": "MiniMax M2"},
]


async def ensure_custom_openai_minimax_catalog() -> None:
    """若缺失则 upsert 厂家 custom_openai，并向当前激活的 system_configs 追加 MiniMax 模型项。"""
    try:
        db = get_mongo_db()
        providers = db.llm_providers
        now = now_tz()

        await providers.update_one(
            {"name": "custom_openai"},
            {
                "$set": {
                    "name": "custom_openai",
                    "display_name": "自定义 OpenAI（MiniMax 等）",
                    "description": "OpenAI 兼容接口。密钥请配置环境变量 CUSTOM_OPENAI_API_KEY 与 CUSTOM_OPENAI_BASE_URL（MiniMax 示例：https://api.minimax.io/v1）。",
                    "website": "https://platform.minimax.io/",
                    "api_doc_url": "https://platform.minimax.io/docs/api-reference/text-openai-api",
                    "default_base_url": "https://api.minimax.io/v1",
                    "is_active": True,
                    "supported_features": ["chat", "completion", "function_calling", "streaming"],
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        logger.info("✅ 已确保 llm_providers 存在 custom_openai（自定义 OpenAI / MiniMax）")

        cursor = db.system_configs.find({"is_active": True})
        configs = await cursor.to_list(20)
        if not configs:
            logger.debug("无激活的 system_configs，跳过 MiniMax 模型条目补充")
            return

        for doc in configs:
            llm_configs: List[Dict[str, Any]] = list(doc.get("llm_configs") or [])
            existing: Set[Tuple[str, str]] = set()
            for c in llm_configs:
                p = c.get("provider")
                if hasattr(p, "value"):
                    p = p.value
                existing.add((str(p), str(c.get("model_name", ""))))

            to_add: List[Dict[str, Any]] = []
            for m in _MINIMAX_MODELS:
                key = ("custom_openai", m["model_name"])
                if key in existing:
                    continue
                to_add.append(
                    {
                        "provider": "custom_openai",
                        "model_name": m["model_name"],
                        "model_display_name": m["model_display_name"],
                        "description": m.get("description") or "OpenAI 兼容（MiniMax）",
                        "api_key": None,
                        "api_base": "https://api.minimax.io/v1",
                        "max_tokens": 8192,
                        "temperature": 0.7,
                        "timeout": 180,
                        "retry_times": 3,
                        "enabled": True,
                        "capability_level": 3,
                        "suitable_roles": ["both"],
                        "features": ["tool_calling", "long_context"],
                    }
                )

            if not to_add:
                continue

            await db.system_configs.update_one(
                {"_id": doc["_id"]},
                {"$push": {"llm_configs": {"$each": to_add}}, "$set": {"updated_at": now}},
            )
            logger.info(
                "✅ 已向 system_configs 补充 %s 条 MiniMax（custom_openai）模型配置",
                len(to_add),
            )

    except Exception as e:
        logger.warning("补充 MiniMax 模型目录失败（可稍后在「大模型配置」中手动添加）: %s", e, exc_info=True)


async def ensure_google_gemini_catalog() -> None:
    """若环境变量已配 GOOGLE_API_KEY，则确保 llm_providers 存在 google，并向 system_configs 追加 Gemini 模型项。"""
    if not env_has_google_api_key():
        return
    try:
        db = get_mongo_db()
        providers = db.llm_providers
        now = now_tz()

        await providers.update_one(
            {"name": "google"},
            {
                "$set": {
                    "name": "google",
                    "display_name": "Google AI",
                    "description": "Google Gemini。密钥可配置环境变量 GOOGLE_API_KEY（AI Studio）。",
                    "website": "https://ai.google.dev",
                    "api_doc_url": "https://ai.google.dev/docs",
                    "default_base_url": _GOOGLE_GEMINI_DEFAULT_BASE,
                    "is_active": True,
                    "supported_features": ["chat", "completion", "embedding", "vision", "function_calling", "streaming"],
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        logger.info("✅ 已确保 llm_providers 存在 google（Gemini）")

        cursor = db.system_configs.find({"is_active": True})
        configs = await cursor.to_list(20)
        if not configs:
            logger.debug("无激活的 system_configs，跳过 Gemini 模型条目补充")
            return

        for doc in configs:
            llm_configs: List[Dict[str, Any]] = list(doc.get("llm_configs") or [])
            existing: Set[Tuple[str, str]] = set()
            for c in llm_configs:
                p = c.get("provider")
                if hasattr(p, "value"):
                    p = p.value
                existing.add((str(p), str(c.get("model_name", ""))))

            to_add: List[Dict[str, Any]] = []
            for m in _GEMINI_MODELS:
                key = ("google", m["model_name"])
                if key in existing:
                    continue
                to_add.append(
                    {
                        "provider": "google",
                        "model_name": m["model_name"],
                        "model_display_name": m["model_display_name"],
                        "description": m.get("description") or "Google Gemini",
                        "api_key": None,
                        "api_base": _GOOGLE_GEMINI_DEFAULT_BASE,
                        "max_tokens": 8192,
                        "temperature": 0.7,
                        "timeout": 180,
                        "retry_times": 3,
                        "enabled": True,
                        "capability_level": int(m.get("capability_level", 3)),
                        "suitable_roles": list(m.get("suitable_roles", ["both"])),
                        "features": ["tool_calling", "long_context", "vision"],
                    }
                )

            if not to_add:
                continue

            await db.system_configs.update_one(
                {"_id": doc["_id"]},
                {"$push": {"llm_configs": {"$each": to_add}}, "$set": {"updated_at": now}},
            )
            logger.info("✅ 已向 system_configs 补充 %s 条 Google Gemini 模型配置", len(to_add))

    except Exception as e:
        logger.warning("补充 Gemini 模型目录失败（可在「大模型配置」中手动添加）: %s", e, exc_info=True)
