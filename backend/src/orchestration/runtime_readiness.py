"""Kiểm tra readiness runtime theo dependency thực tế của từng tool."""

from __future__ import annotations

import importlib
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from config import Settings, get_settings
from agents.financial_agent.config import FinancialReportsToolSettings, get_financial_reports_settings
from agents.news_agent.config import NewsToolSettings, get_news_tool_settings
from .contracts import ToolName


READINESS_SUCCESS = "success"
READINESS_DEPENDENCY_MISSING = "dependency_missing"
READINESS_CONFIG_INVALID = "config_invalid"
READINESS_SERVICE_UNREACHABLE = "service_unreachable"
READINESS_COLLECTION_MISSING = "collection_missing"
READINESS_NO_DATA = "no_data"

READINESS_BLOCKING_CATEGORIES = {
    READINESS_DEPENDENCY_MISSING,
    READINESS_CONFIG_INVALID,
    READINESS_SERVICE_UNREACHABLE,
    READINESS_COLLECTION_MISSING,
}

MARKET_TABLES_AND_VIEWS = (
    "symbols",
    "daily_stock_raw",
    "daily_stock_features",
    "intraday_prices",
    "vw_daily_stock_llm",
    "vw_intraday_latest_llm",
)


@dataclass(slots=True)
class ReadinessCheck:
    """Mô tả một phép kiểm runtime nhỏ.

    Args:
        name: Tên phép kiểm.
        category: Nhóm kết quả chuẩn hóa.
        detail: Diễn giải ngắn gọn.
        is_blocking: Có nên chặn tool trước khi chạy hay không.
        metadata: Thông tin phụ để debug.
    """

    name: str
    category: str
    detail: str
    is_blocking: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Cho biết phép kiểm đã pass hoàn toàn hay chưa."""

        return self.category == READINESS_SUCCESS


@dataclass(slots=True)
class ToolRuntimeReadiness:
    """Trạng thái readiness tổng hợp của một tool.

    Args:
        tool_name: Tên tool tương ứng.
        runtime_ready: Tool có thể chạy runtime path hay chưa.
        end_to_end_ready: Tool vừa chạy được vừa có dữ liệu đủ để verify end-to-end.
        checks: Danh sách phép kiểm chi tiết.
        notes: Ghi chú vận hành bổ sung.
    """

    tool_name: ToolName
    runtime_ready: bool
    end_to_end_ready: bool
    checks: list[ReadinessCheck] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def primary_failure_category(self) -> str:
        """Lấy category lỗi chính đang làm tool chưa sẵn sàng."""

        for check in self.checks:
            if check.is_blocking and not check.ok:
                return check.category
        for check in self.checks:
            if not check.ok:
                return check.category
        return READINESS_SUCCESS

    @property
    def blocking_failures(self) -> list[ReadinessCheck]:
        """Lấy các phép kiểm đang chặn tool trước khi chạy."""

        return [check for check in self.checks if check.is_blocking and not check.ok]

    @property
    def data_gaps(self) -> list[ReadinessCheck]:
        """Lấy các phép kiểm không chặn nhưng cho thấy dữ liệu còn thiếu."""

        return [check for check in self.checks if not check.is_blocking and not check.ok]


def dependency_names_for_tools(tool_names: list[ToolName]) -> list[str]:
    """Suy ra dependency chính cho danh sách tool được chọn.

    Args:
        tool_names: Danh sách tool chuẩn hóa từ router.

    Returns:
        Danh sách dependency đã dedupe để hiển thị trong smoke report.
    """

    dependencies: list[str] = []
    for tool_name in tool_names:
        if tool_name == ToolName.MARKET:
            dependencies.extend(["postgres", "gemini"])
        elif tool_name == ToolName.NEWS:
            dependencies.extend(["postgres", "ddgs", "crawl4ai", "groq_or_gemini"])
        elif tool_name == ToolName.FINANCIAL_REPORTS:
            dependencies.extend(["qdrant", "sentence_transformers", "groq"])

    deduped: list[str] = []
    for dependency in dependencies:
        if dependency not in deduped:
            deduped.append(dependency)
    return deduped


def build_runtime_readiness_map(
    tool_names: list[ToolName] | None = None,
) -> dict[ToolName, ToolRuntimeReadiness]:
    """Đánh giá readiness cho các tool được yêu cầu.

    Args:
        tool_names: Danh sách tool cần check. Nếu bỏ trống sẽ check cả 3 tool.

    Returns:
        Map từ ToolName sang ToolRuntimeReadiness.
    """

    requested_tools = tool_names if tool_names is not None else [ToolName.MARKET, ToolName.NEWS, ToolName.FINANCIAL_REPORTS]
    readiness_map: dict[ToolName, ToolRuntimeReadiness] = {}

    base_settings = get_settings()
    market_readiness: ToolRuntimeReadiness | None = None
    if ToolName.MARKET in requested_tools or ToolName.NEWS in requested_tools:
        market_readiness = build_market_readiness(base_settings)
        if ToolName.MARKET in requested_tools:
            readiness_map[ToolName.MARKET] = market_readiness

    if ToolName.NEWS in requested_tools:
        readiness_map[ToolName.NEWS] = build_news_readiness(base_settings, market_readiness)

    if ToolName.FINANCIAL_REPORTS in requested_tools:
        readiness_map[ToolName.FINANCIAL_REPORTS] = build_reports_readiness(base_settings)

    return readiness_map


def build_market_readiness(settings: Settings | None = None) -> ToolRuntimeReadiness:
    """Đánh giá readiness runtime của tool market."""

    active_settings = settings or get_settings()
    checks: list[ReadinessCheck] = [
        _build_key_check(
            name="market:generation_keys",
            has_value=bool(active_settings.google_api_keys),
            success_detail="Có Gemini key cho NL2SQL runtime.",
            failure_detail="Thiếu Gemini key cho market NL2SQL runtime.",
        )
    ]

    parsed = urlparse(active_settings.sqlalchemy_url)
    db_host = parsed.hostname or active_settings.postgres_host
    db_port = parsed.port or active_settings.postgres_port
    socket_check = _check_socket(db_host, int(db_port), name=f"tcp:{db_host}:{db_port}")
    checks.append(socket_check)
    if socket_check.ok:
        checks.append(_check_database_views(active_settings.sqlalchemy_url))

    return ToolRuntimeReadiness(
        tool_name=ToolName.MARKET,
        runtime_ready=_is_runtime_ready(checks),
        end_to_end_ready=_is_end_to_end_ready(checks),
        checks=checks,
        notes=[
            "Tool market cần PostgreSQL thật với schema/view đã restore từ dump hoặc ETL trước đó.",
        ],
    )


def build_news_readiness(
    settings: Settings | None = None,
    market_readiness: ToolRuntimeReadiness | None = None,
) -> ToolRuntimeReadiness:
    """Đánh giá readiness runtime của tool news."""

    base_settings = settings or get_settings()
    active_settings = get_news_tool_settings(base_settings)
    checks: list[ReadinessCheck] = [
        _check_module("ddgs"),
        _check_module("crawl4ai"),
    ]
    checks.append(_build_news_provider_check(active_settings))
    checks.append(_check_artifact_root(active_settings))

    market_dependencies = market_readiness or build_market_readiness(base_settings)
    for market_check in market_dependencies.checks:
        if not market_check.name.startswith("tcp:") and market_check.name != "database:views":
            continue
        checks.append(
            ReadinessCheck(
                name=f"news:depends_on:{market_check.name}",
                category=market_check.category,
                detail=market_check.detail,
                is_blocking=market_check.is_blocking,
                metadata=dict(market_check.metadata),
            )
        )

    return ToolRuntimeReadiness(
        tool_name=ToolName.NEWS,
        runtime_ready=_is_runtime_ready(checks),
        end_to_end_ready=_is_end_to_end_ready(checks),
        checks=checks,
        notes=[
            "Tool news hiện vẫn cần PostgreSQL metadata ngoài search, crawl, summarize và filesystem artifacts.",
        ],
    )


def build_reports_readiness(settings: Settings | None = None) -> ToolRuntimeReadiness:
    """Đánh giá readiness runtime của tool financial_reports."""

    base_settings = settings or get_settings()
    active_settings = get_financial_reports_settings(base_settings)
    checks: list[ReadinessCheck] = [
        _check_module("qdrant_client"),
        _check_module("sentence_transformers"),
        _build_key_check(
            name="reports:groq_keys",
            has_value=bool(active_settings.groq_api_keys),
            success_detail="Có Groq key cho rewrite/synthesis của financial reports.",
            failure_detail="Thiếu Groq key cho financial reports runtime.",
        ),
        _build_string_config_check(
            name="reports:embedding_model_config",
            value=active_settings.embedding_model,
            success_detail=f"Embedding model: {active_settings.embedding_model}",
            failure_detail="Thiếu FINANCIAL_REPORTS_EMBEDDING_MODEL.",
        ),
    ]

    parsed = urlparse(active_settings.qdrant_url)
    qdrant_host = parsed.hostname
    if not qdrant_host:
        checks.append(
            ReadinessCheck(
                name="reports:qdrant_url",
                category=READINESS_CONFIG_INVALID,
                detail="FINANCIAL_REPORTS_QDRANT_URL không hợp lệ hoặc thiếu hostname.",
                is_blocking=True,
                metadata={"qdrant_url": active_settings.qdrant_url},
            )
        )
    else:
        qdrant_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        socket_check = _check_socket(qdrant_host, int(qdrant_port), name=f"tcp:{qdrant_host}:{qdrant_port}")
        checks.append(socket_check)
        if socket_check.ok:
            checks.append(
                _check_qdrant_collection(
                    qdrant_url=active_settings.qdrant_url,
                    collection_name=active_settings.qdrant_collection,
                    api_key=active_settings.qdrant_api_key,
                )
            )

    return ToolRuntimeReadiness(
        tool_name=ToolName.FINANCIAL_REPORTS,
        runtime_ready=_is_runtime_ready(checks),
        end_to_end_ready=_is_end_to_end_ready(checks),
        checks=checks,
        notes=[
            "Tool financial_reports không cần PostgreSQL ở runtime query path, nhưng cần Qdrant thật và collection đã có chunks.",
        ],
    )


def summarize_preflight_blocker(readiness: ToolRuntimeReadiness) -> str:
    """Tạo diễn giải ngắn gọn cho blocker runtime của một tool.

    Args:
        readiness: Readiness đã tính cho tool.

    Returns:
        Chuỗi diễn giải lỗi gọn để đưa vào API response hoặc smoke report.
    """

    blocking_checks = readiness.blocking_failures
    if blocking_checks:
        return " | ".join(check.detail for check in blocking_checks)
    if readiness.data_gaps:
        return " | ".join(check.detail for check in readiness.data_gaps)
    return f"Tool `{readiness.tool_name.value}` đã sẵn sàng."


def _check_module(module_name: str) -> ReadinessCheck:
    """Kiểm tra dependency Python có import được hay không."""

    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            raise ModuleNotFoundError(module_name)
        return ReadinessCheck(
            name=f"python:{module_name}",
            category=READINESS_SUCCESS,
            detail="Import thành công.",
            is_blocking=True,
        )
    except Exception as exc:  # noqa: BLE001
        return ReadinessCheck(
            name=f"python:{module_name}",
            category=READINESS_DEPENDENCY_MISSING,
            detail=f"Import lỗi: {type(exc).__name__}: {exc}",
            is_blocking=True,
        )


def _check_socket(host: str, port: int, *, name: str) -> ReadinessCheck:
    """Kiểm tra một TCP endpoint có mở hay không."""

    try:
        resolved_ip = socket.gethostbyname(host)
    except Exception as exc:  # noqa: BLE001
        return ReadinessCheck(
            name=name,
            category=READINESS_SERVICE_UNREACHABLE,
            detail=f"Không resolve được host `{host}`: {exc}",
            is_blocking=True,
        )

    try:
        with socket.create_connection((host, port), timeout=2.5):
            return ReadinessCheck(
                name=name,
                category=READINESS_SUCCESS,
                detail="Kết nối TCP thành công.",
                is_blocking=True,
                metadata={"resolved_ip": resolved_ip},
            )
    except OSError as exc:
        return ReadinessCheck(
            name=name,
            category=READINESS_SERVICE_UNREACHABLE,
            detail=f"Kết nối TCP tới `{host}:{port}` thất bại: {exc}",
            is_blocking=True,
            metadata={"resolved_ip": resolved_ip},
        )


def _check_database_views(sqlalchemy_url: str) -> ReadinessCheck:
    """Kiểm tra DB có connect được và có dữ liệu market chính hay không."""

    try:
        engine = create_engine(sqlalchemy_url, pool_pre_ping=True, future=True)
        with engine.connect() as connection:
            counts = {
                table_name: int(connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0)
                for table_name in MARKET_TABLES_AND_VIEWS
            }
        if any(count > 0 for count in counts.values()):
            return ReadinessCheck(
                name="database:views",
                category=READINESS_SUCCESS,
                detail="Connect DB và đọc được các bảng/view market chính.",
                is_blocking=True,
                metadata=counts,
            )
        return ReadinessCheck(
            name="database:views",
            category=READINESS_NO_DATA,
            detail="DB đã kết nối được nhưng các bảng/view market chính chưa có dữ liệu để query thật.",
            is_blocking=False,
            metadata=counts,
        )
    except SQLAlchemyError as exc:
        return ReadinessCheck(
            name="database:views",
            category=_classify_database_error(str(exc)),
            detail=f"DB check lỗi: {exc}",
            is_blocking=True,
        )


def _check_qdrant_collection(
    *,
    qdrant_url: str,
    collection_name: str,
    api_key: str | None,
) -> ReadinessCheck:
    """Kiểm tra Qdrant endpoint và collection cho financial reports."""

    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=qdrant_url, api_key=api_key)
        collections = client.get_collections()
        collection_names = [item.name for item in collections.collections]
        if collection_name not in collection_names:
            return ReadinessCheck(
                name="qdrant:collection",
                category=READINESS_COLLECTION_MISSING,
                detail=f"Qdrant đang lên nhưng chưa có collection `{collection_name}`.",
                is_blocking=True,
                metadata={"collections": collection_names},
            )

        collection_info = client.get_collection(collection_name)
        points_count = getattr(collection_info, "points_count", None)
        if not points_count:
            return ReadinessCheck(
                name="qdrant:collection",
                category=READINESS_NO_DATA,
                detail=f"Collection `{collection_name}` tồn tại nhưng chưa có point để query thật.",
                is_blocking=False,
                metadata={
                    "points_count": points_count,
                    "status": str(getattr(collection_info, "status", "")),
                },
            )
        return ReadinessCheck(
            name="qdrant:collection",
            category=READINESS_SUCCESS,
            detail=f"Collection `{collection_name}` tồn tại và đã có point.",
            is_blocking=True,
            metadata={
                "points_count": points_count,
                "status": str(getattr(collection_info, "status", "")),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return ReadinessCheck(
            name="qdrant:collection",
            category=_classify_qdrant_error(str(exc)),
            detail=f"Không kiểm tra được Qdrant collection: {exc}",
            is_blocking=True,
        )


def _check_artifact_root(settings: NewsToolSettings) -> ReadinessCheck:
    """Kiểm tra filesystem artifact root của news có ghi được hay không."""

    try:
        settings.artifact_root.mkdir(parents=True, exist_ok=True)
        return ReadinessCheck(
            name="news:artifact_root",
            category=READINESS_SUCCESS,
            detail="Artifact root dùng được.",
            is_blocking=True,
            metadata={"path": str(settings.artifact_root)},
        )
    except Exception as exc:  # noqa: BLE001
        return ReadinessCheck(
            name="news:artifact_root",
            category=READINESS_CONFIG_INVALID,
            detail=f"Không tạo được artifact root: {exc}",
            is_blocking=True,
            metadata={"path": str(settings.artifact_root)},
        )


def _build_key_check(
    *,
    name: str,
    has_value: bool,
    success_detail: str,
    failure_detail: str,
) -> ReadinessCheck:
    """Tạo readiness check cho các biến key/token quan trọng."""

    return ReadinessCheck(
        name=name,
        category=READINESS_SUCCESS if has_value else READINESS_CONFIG_INVALID,
        detail=success_detail if has_value else failure_detail,
        is_blocking=True,
    )


def _build_news_provider_check(settings: NewsToolSettings) -> ReadinessCheck:
    """Đánh giá cấu hình model provider của news summarizer."""

    if settings.summary_provider == "fallback":
        return ReadinessCheck(
            name="news:summarizer_provider",
            category=READINESS_SUCCESS,
            detail="News đang dùng fallback provider nên không cần model key.",
            is_blocking=True,
        )
    if settings.summary_provider == "groq":
        return _build_key_check(
            name="news:summarizer_provider",
            has_value=bool(settings.groq_api_keys),
            success_detail="Provider groq đã có key khả dụng.",
            failure_detail="Provider groq chưa có key khả dụng.",
        )
    return _build_key_check(
        name="news:summarizer_provider",
        has_value=bool(settings.google_api_keys),
        success_detail="Provider gemini đã có key khả dụng.",
        failure_detail="Provider gemini chưa có key khả dụng.",
    )


def _build_string_config_check(
    *,
    name: str,
    value: str,
    success_detail: str,
    failure_detail: str,
) -> ReadinessCheck:
    """Tạo readiness check cho một giá trị cấu hình dạng chuỗi."""

    return ReadinessCheck(
        name=name,
        category=READINESS_SUCCESS if value.strip() else READINESS_CONFIG_INVALID,
        detail=success_detail if value.strip() else failure_detail,
        is_blocking=True,
    )


def _classify_database_error(error_message: str) -> str:
    """Phân loại lỗi DB theo nhóm chẩn đoán hữu ích hơn."""

    lowered = error_message.lower()
    if "authentication failed" in lowered or "role " in lowered or "database " in lowered:
        return READINESS_CONFIG_INVALID
    return READINESS_SERVICE_UNREACHABLE


def _classify_qdrant_error(error_message: str) -> str:
    """Phân loại lỗi Qdrant theo nhóm chẩn đoán hữu ích hơn."""

    lowered = error_message.lower()
    if "collection" in lowered and "not found" in lowered:
        return READINESS_COLLECTION_MISSING
    if "connection refused" in lowered or "failed to establish a new connection" in lowered:
        return READINESS_SERVICE_UNREACHABLE
    return READINESS_SERVICE_UNREACHABLE


def _is_runtime_ready(checks: list[ReadinessCheck]) -> bool:
    """Cho biết tool có thể chạy runtime path hay chưa."""

    return not any(check.is_blocking and not check.ok for check in checks)


def _is_end_to_end_ready(checks: list[ReadinessCheck]) -> bool:
    """Cho biết tool đã đủ điều kiện verify end-to-end hay chưa."""

    return _is_runtime_ready(checks) and not any(check.category == READINESS_NO_DATA for check in checks)
