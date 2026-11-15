"""Synchronous MFDS adapters with a shared caller-supplied request budget.

No requests occur on construction. Callers supply max_requests because the
provider's daily limit is unmeasured. Partial results always carry a stop code.
"""

from collections.abc import Callable, Mapping
from math import isfinite
from time import monotonic, sleep
from typing import Any, NamedTuple
from urllib.parse import quote, quote_plus
from xml.etree import ElementTree

import httpx
from pydantic import ValidationError

from beautyads import settings
from beautyads.domain.mfds import FunctionalReport, IngredientStandard

_BASE_URL = "https://apis.data.go.kr"
_INGREDIENT = "1471000/CsmtcsIngdCpntInfoService01/getCsmtcsIngdCpntInfoService01"
_REPORT = "1471000/FtnltCosmRptPrdlstInfoService01/getRptPrdlstInq01"
_SCREENING = "1471057/FtnltCosmSrngPrdlstInfoService05/getSrngPrdlstInq05"
_TIMEOUT_S = 30.0
_MAX_ATTEMPTS = 3


class MFDSHttpResponse(NamedTuple):
    status: int
    body: Any | None


MFDSGet = Callable[[str, Mapping[str, str], float], MFDSHttpResponse]


class MFDSError(Exception):
    """Stable exception text, with credential-redacted provider diagnostics."""

    def __init__(
        self,
        code: str,
        *,
        provider_code: str | None = None,
        provider_message: str | None = None,
        http_status: int | None = None,
    ):
        self.code = code
        self.provider_code = provider_code
        self.provider_message = provider_message
        self.http_status = http_status
        super().__init__(code)


class MFDSResult[T](NamedTuple):
    items: list[T]
    stopped: str | None = None
    error: MFDSError | None = None


def mfds_httpx_get(
    url: str, params: Mapping[str, str], timeout_s: float
) -> MFDSHttpResponse:
    """The only real HTTP boundary; never emit a credential-bearing URL.

    Use the public transport interface directly: httpx.Client's INFO request
    log includes the query string, which necessarily carries this API's key.
    Transport exceptions become stable codes without retaining diagnostic text.
    """
    try:
        request = httpx.Request("GET", url, params=params)
        request.extensions["timeout"] = dict.fromkeys(
            ("connect", "read", "write", "pool"), timeout_s
        )
        with httpx.HTTPTransport() as transport:
            response = transport.handle_request(request)
            try:
                response.read()
                try:
                    body = response.json()
                except ValueError:
                    body = None
                return MFDSHttpResponse(response.status_code, body)
            finally:
                response.close()
    except (httpx.ConnectError, httpx.TimeoutException):
        raise MFDSError("MFDS_TRANSIENT_REQUEST_FAILED") from None
    except httpx.RequestError:
        raise MFDSError("MFDS_REQUEST_FAILED") from None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _redact(value: Any, secret: str) -> Any:
    """Response echoes cannot leak the raw or URL-encoded key into any result."""
    if isinstance(value, str):
        for token in {secret, quote(secret, safe=""), quote_plus(secret)}:
            value = value.replace(token, "[REDACTED]")
        return value
    if isinstance(value, Mapping):
        return {
            _redact(key, secret): _redact(item, secret) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value


def _response_body(response: MFDSHttpResponse, secret: str) -> Mapping[str, Any]:
    # HTTP failure is never treated as a successful page, regardless of its body.
    payload = _mapping(_redact(response.body, secret))
    if response.status != 200:
        gateway = _mapping(
            _mapping(payload.get("OpenAPI_ServiceResponse")).get("cmmMsgHeader")
        )
        message = _text(gateway.get("errMsg"))
        if response.status == 403 and message == "SERVICE_KEY_IS_NOT_REGISTERED_ERROR":
            code = "MFDS_KEY_NOT_REGISTERED"
        elif response.status == 400 and message == "NO_OPENAPI_SERVICE_ERROR":
            code = "MFDS_OPERATION_UNKNOWN"
        else:
            code = f"MFDS_HTTP_{response.status}"
        raise MFDSError(
            code,
            provider_code=_text(gateway.get("returnReasonCode")),
            provider_message="; ".join(
                text
                for key in ("errMsg", "returnAuthMsg")
                if (text := _text(gateway.get(key))) is not None
            )
            or None,
            http_status=response.status,
        )
    header = _mapping(payload.get("header"))
    code = header.get("resultCode")
    if code != "00":
        raise MFDSError(
            "MFDS_API_ERROR" if code is not None else "MFDS_INVALID_RESPONSE",
            provider_code=_text(code),
            provider_message=_text(header.get("resultMsg")),
            http_status=200,
        )
    content = payload.get("body")
    if not isinstance(content, Mapping):
        raise MFDSError("MFDS_INVALID_RESPONSE")
    return content


def _effect_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MFDSError("MFDS_XML_REJECTED")
    if any(marker in value.upper() for marker in ("<!DOCTYPE", "<!ENTITY")):
        raise MFDSError("MFDS_XML_REJECTED")
    try:
        root = ElementTree.fromstring(value)
    except ElementTree.ParseError:
        raise MFDSError("MFDS_XML_REJECTED") from None
    return (
        "\n".join(
            text
            for paragraph in root.iter("PARAGRAPH")
            if (text := "".join(paragraph.itertext()).strip())
        )
        or None
    )


def _ingredient(row: Mapping[str, Any]) -> IngredientStandard:
    return IngredientStandard(
        name_ko=row.get("INGR_KOR_NAME"),
        name_en=row.get("INGR_ENG_NAME"),
        cas_no=row.get("CAS_NO"),
    )


def _report(row: Mapping[str, Any], *, screening: bool) -> FunctionalReport | None:
    raw = None if screening else row.get("CANCEL_APPROVAL_YN")
    if raw == "Y":
        return None
    return FunctionalReport(
        item_name=row.get("ITEM_NAME"),
        entp_name=row.get("ENTP_NAME"),
        report_date=None if screening else row.get("REPORT_DATE"),
        effect_text=_effect_text(row.get("EE_DOC_DATA"))
        if screening
        else row.get("EE_NAME"),
        spf=None if screening else row.get("SPF"),
        pa=None if screening else row.get("PA"),
        cancelled=False if raw == "N" else None,
        cancelled_raw=raw,
        source="screening" if screening else "report",
    )


class MFDSClient:
    """Share budget and pacing across all three operations and their retries.

    A result with stopped=None is complete. A stopped result may contain facts
    already received but cannot establish that an unmatched item is absent.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        get: MFDSGet = mfds_httpx_get,
        clock: Callable[[], float] = monotonic,
        sleep: Callable[[float], None] = sleep,
        min_interval_s: float = 0.5,
    ):
        if type(max_requests) is not int or max_requests < 0:
            raise ValueError("MFDS_INVALID_REQUEST_CAP")
        if not isfinite(min_interval_s) or min_interval_s < 0:
            raise ValueError("MFDS_INVALID_INTERVAL")
        self._max_requests = max_requests
        self._requests = 0
        self._get = get
        self._clock = clock
        self._sleep = sleep
        self._min_interval_s = min_interval_s
        self._last_request: float | None = None

    def _request(self, endpoint: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        for attempt in range(_MAX_ATTEMPTS):
            if self._requests >= self._max_requests:
                raise MFDSError("MFDS_REQUEST_CAP")
            try:
                secret = settings.require_setting("DATA_GO_KR_SERVICE_KEY")
            except settings.MissingSetting:
                raise MFDSError("ENV_MISSING:DATA_GO_KR_SERVICE_KEY") from None
            if self._last_request is not None:
                delay = self._min_interval_s - (self._clock() - self._last_request)
                if delay > 0:
                    self._sleep(delay)
            self._last_request = self._clock()
            self._requests += 1
            try:
                response = self._get(
                    f"{_BASE_URL}/{endpoint}",
                    {**params, "serviceKey": secret},
                    _TIMEOUT_S,
                )
            except (
                ConnectionError,
                TimeoutError,
                httpx.ConnectError,
                httpx.TimeoutException,
            ):
                if attempt + 1 < _MAX_ATTEMPTS:
                    continue
                raise MFDSError("MFDS_REQUEST_FAILED") from None
            except MFDSError as error:
                if error.code == "MFDS_TRANSIENT_REQUEST_FAILED":
                    if attempt + 1 < _MAX_ATTEMPTS:
                        continue
                    raise MFDSError("MFDS_REQUEST_FAILED") from None
                raise
            except (httpx.RequestError, OSError, RuntimeError, ValueError):
                # Transport diagnostics may include a full credential-bearing URL.
                raise MFDSError("MFDS_REQUEST_FAILED") from None
            if response.status == 503 and attempt + 1 < _MAX_ATTEMPTS:
                continue
            return _response_body(response, secret)
        raise MFDSError("MFDS_REQUEST_FAILED")  # defensive, attempts are nonzero

    def _search[T](
        self,
        query: str,
        *,
        endpoint: str,
        parameter: str,
        convert: Callable[[Mapping[str, Any]], T | None],
        max_pages: int,
        num_of_rows: int,
        exact: bool = False,
    ) -> MFDSResult[T]:
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError("MFDS_INVALID_PAGE_CAP")
        if type(num_of_rows) is not int or num_of_rows < 1:
            raise ValueError("MFDS_INVALID_PAGE_SIZE")
        query = "".join(query.split())
        if not query:
            raise ValueError("MFDS_EMPTY_QUERY")
        items: list[T] = []
        received = 0
        try:
            for page_no in range(1, max_pages + 1):
                content = self._request(
                    endpoint,
                    {
                        parameter: query,
                        "type": "json",
                        "pageNo": str(page_no),
                        "numOfRows": str(num_of_rows),
                    },
                )
                total = content.get("totalCount")
                if total == 0 or "items" not in content:
                    return MFDSResult(items)
                rows = content.get("items")
                if not isinstance(rows, list) or any(
                    not isinstance(row, Mapping) for row in rows
                ):
                    raise MFDSError("MFDS_INVALID_RESPONSE")
                if type(total) is not int or total < 0 or not rows:
                    raise MFDSError("MFDS_INVALID_RESPONSE")
                received += len(rows)
                for row in rows:
                    if exact and row.get("INGR_KOR_NAME") != query:
                        continue
                    item = convert(row)
                    if item is not None:
                        items.append(item)
                if received >= total:
                    return MFDSResult(items)
        except ValidationError:
            error = MFDSError("MFDS_INVALID_RESPONSE")
            return MFDSResult(items, error.code, error)
        except MFDSError as error:
            # Return diagnostics, not traceback frames retaining request secrets.
            diagnostic = MFDSError(
                error.code,
                provider_code=error.provider_code,
                provider_message=error.provider_message,
                http_status=error.http_status,
            )
            return MFDSResult(items, diagnostic.code, diagnostic)
        return MFDSResult(items, "MFDS_PAGE_CAP")

    def search_ingredients(
        self, name_ko: str, *, max_pages: int = 10, num_of_rows: int = 100
    ) -> MFDSResult[IngredientStandard]:
        return self._search(
            name_ko,
            endpoint=_INGREDIENT,
            parameter="INGR_KOR_NAME",
            convert=_ingredient,
            max_pages=max_pages,
            num_of_rows=num_of_rows,
            exact=True,
        )

    def search_reports(
        self, item_name: str, *, max_pages: int = 10, num_of_rows: int = 100
    ) -> MFDSResult[FunctionalReport]:
        return self._search(
            item_name,
            endpoint=_REPORT,
            parameter="item_name",
            convert=lambda row: _report(row, screening=False),
            max_pages=max_pages,
            num_of_rows=num_of_rows,
        )

    def search_screenings(
        self, item_name: str, *, max_pages: int = 10, num_of_rows: int = 100
    ) -> MFDSResult[FunctionalReport]:
        return self._search(
            item_name,
            endpoint=_SCREENING,
            parameter="item_name",
            convert=lambda row: _report(row, screening=True),
            max_pages=max_pages,
            num_of_rows=num_of_rows,
        )
