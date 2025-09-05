from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AggregateFunction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SUM: _ClassVar[AggregateFunction]
    COUNT: _ClassVar[AggregateFunction]
    COUNT_STAR: _ClassVar[AggregateFunction]
    COUNT_DISTINCT: _ClassVar[AggregateFunction]

class SortDirection(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ASC: _ClassVar[SortDirection]
    DESC: _ClassVar[SortDirection]
SUM: AggregateFunction
COUNT: AggregateFunction
COUNT_STAR: AggregateFunction
COUNT_DISTINCT: AggregateFunction
ASC: SortDirection
DESC: SortDirection

class AuthenticateRequest(_message.Message):
    __slots__ = ("user", "password", "userNameForImpersonation")
    USER_FIELD_NUMBER: _ClassVar[int]
    PASSWORD_FIELD_NUMBER: _ClassVar[int]
    USERNAMEFORIMPERSONATION_FIELD_NUMBER: _ClassVar[int]
    user: str
    password: str
    userNameForImpersonation: str
    def __init__(self, user: _Optional[str] = ..., password: _Optional[str] = ..., userNameForImpersonation: _Optional[str] = ...) -> None: ...

class AuthenticateResponse(_message.Message):
    __slots__ = ("sessionId", "new_strategy", "engineIP")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    new_strategy: str
    engineIP: str
    def __init__(self, sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ..., engineIP: _Optional[str] = ...) -> None: ...

class IdentifyPlannerRequest(_message.Message):
    __slots__ = ("sessionId", "firstTimeRequestPayload", "existingQuery")
    class FirstTimeRequestPayload(_message.Message):
        __slots__ = ("schema", "catalog", "queryString")
        SCHEMA_FIELD_NUMBER: _ClassVar[int]
        CATALOG_FIELD_NUMBER: _ClassVar[int]
        QUERYSTRING_FIELD_NUMBER: _ClassVar[int]
        schema: str
        catalog: str
        queryString: str
        def __init__(self, schema: _Optional[str] = ..., catalog: _Optional[str] = ..., queryString: _Optional[str] = ...) -> None: ...
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    FIRSTTIMEREQUESTPAYLOAD_FIELD_NUMBER: _ClassVar[int]
    EXISTINGQUERY_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    firstTimeRequestPayload: IdentifyPlannerRequest.FirstTimeRequestPayload
    existingQuery: ExistingQuery
    def __init__(self, sessionId: _Optional[str] = ..., firstTimeRequestPayload: _Optional[_Union[IdentifyPlannerRequest.FirstTimeRequestPayload, _Mapping]] = ..., existingQuery: _Optional[_Union[ExistingQuery, _Mapping]] = ...) -> None: ...

class IdentifyPlannerResponse(_message.Message):
    __slots__ = ("existingQuery", "plannerIp", "queueMessage", "sessionId")
    class QueueMessage(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        GO_AHEAD: _ClassVar[IdentifyPlannerResponse.QueueMessage]
        WAITING_ON_PLANNER_SCALEUP: _ClassVar[IdentifyPlannerResponse.QueueMessage]
        RATE_LIMIT: _ClassVar[IdentifyPlannerResponse.QueueMessage]
    GO_AHEAD: IdentifyPlannerResponse.QueueMessage
    WAITING_ON_PLANNER_SCALEUP: IdentifyPlannerResponse.QueueMessage
    RATE_LIMIT: IdentifyPlannerResponse.QueueMessage
    EXISTINGQUERY_FIELD_NUMBER: _ClassVar[int]
    PLANNERIP_FIELD_NUMBER: _ClassVar[int]
    QUEUEMESSAGE_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    existingQuery: ExistingQuery
    plannerIp: str
    queueMessage: IdentifyPlannerResponse.QueueMessage
    sessionId: str
    def __init__(self, existingQuery: _Optional[_Union[ExistingQuery, _Mapping]] = ..., plannerIp: _Optional[str] = ..., queueMessage: _Optional[_Union[IdentifyPlannerResponse.QueueMessage, str]] = ..., sessionId: _Optional[str] = ...) -> None: ...

class PrepareStatementRequest(_message.Message):
    __slots__ = ("sessionId", "schema", "queryString", "quoting", "plannerIp", "existingQuery")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    QUERYSTRING_FIELD_NUMBER: _ClassVar[int]
    QUOTING_FIELD_NUMBER: _ClassVar[int]
    PLANNERIP_FIELD_NUMBER: _ClassVar[int]
    EXISTINGQUERY_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    schema: str
    queryString: str
    quoting: str
    plannerIp: str
    existingQuery: ExistingQuery
    def __init__(self, sessionId: _Optional[str] = ..., schema: _Optional[str] = ..., queryString: _Optional[str] = ..., quoting: _Optional[str] = ..., plannerIp: _Optional[str] = ..., existingQuery: _Optional[_Union[ExistingQuery, _Mapping]] = ...) -> None: ...

class PrepareStatementV2Request(_message.Message):
    __slots__ = ("sessionId", "schema", "catalog", "queryString", "quoting", "plannerIp", "existingQuery")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    CATALOG_FIELD_NUMBER: _ClassVar[int]
    QUERYSTRING_FIELD_NUMBER: _ClassVar[int]
    QUOTING_FIELD_NUMBER: _ClassVar[int]
    PLANNERIP_FIELD_NUMBER: _ClassVar[int]
    EXISTINGQUERY_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    schema: str
    catalog: str
    queryString: str
    quoting: str
    plannerIp: str
    existingQuery: ExistingQuery
    def __init__(self, sessionId: _Optional[str] = ..., schema: _Optional[str] = ..., catalog: _Optional[str] = ..., queryString: _Optional[str] = ..., quoting: _Optional[str] = ..., plannerIp: _Optional[str] = ..., existingQuery: _Optional[_Union[ExistingQuery, _Mapping]] = ...) -> None: ...

class PrepareStatementResponse(_message.Message):
    __slots__ = ("engineIP", "queryId", "sessionId", "new_strategy")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    queryId: str
    sessionId: str
    new_strategy: str
    def __init__(self, engineIP: _Optional[str] = ..., queryId: _Optional[str] = ..., sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class ExecuteStatementRequest(_message.Message):
    __slots__ = ("engineIP", "sessionId", "queryId", "shouldNotCache")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    SHOULDNOTCACHE_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    queryId: str
    shouldNotCache: bool
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., queryId: _Optional[str] = ..., shouldNotCache: bool = ...) -> None: ...

class ExecuteStatementV2Request(_message.Message):
    __slots__ = ("engineIP", "sessionId", "queryId", "shouldNotCache", "params")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    SHOULDNOTCACHE_FIELD_NUMBER: _ClassVar[int]
    PARAMS_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    queryId: str
    shouldNotCache: bool
    params: _containers.RepeatedCompositeFieldContainer[ParameterValue]
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., queryId: _Optional[str] = ..., shouldNotCache: bool = ..., params: _Optional[_Iterable[_Union[ParameterValue, _Mapping]]] = ...) -> None: ...

class ExecuteStatementResponse(_message.Message):
    __slots__ = ("sessionId", "new_strategy")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    new_strategy: str
    def __init__(self, sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class GetResultMetadataRequest(_message.Message):
    __slots__ = ("engineIP", "sessionId", "queryId")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    queryId: str
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., queryId: _Optional[str] = ...) -> None: ...

class GetResultMetadataResponse(_message.Message):
    __slots__ = ("resultMetaData", "sessionId", "new_strategy")
    RESULTMETADATA_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    resultMetaData: bytes
    sessionId: str
    new_strategy: str
    def __init__(self, resultMetaData: _Optional[bytes] = ..., sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class GetNextResultBatchRequest(_message.Message):
    __slots__ = ("engineIP", "sessionId", "queryId")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    queryId: str
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., queryId: _Optional[str] = ...) -> None: ...

class GetNextResultBatchResponse(_message.Message):
    __slots__ = ("resultBatch", "sessionId", "new_strategy")
    RESULTBATCH_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    resultBatch: bytes
    sessionId: str
    new_strategy: str
    def __init__(self, resultBatch: _Optional[bytes] = ..., sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class ExplainAnalyzeRequest(_message.Message):
    __slots__ = ("engineIP", "sessionId", "queryId")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    queryId: str
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., queryId: _Optional[str] = ...) -> None: ...

class ExplainAnalyzeResponse(_message.Message):
    __slots__ = ("explainAnalyze", "isCached", "parsingTime", "queueingTime", "sessionId", "new_strategy")
    EXPLAINANALYZE_FIELD_NUMBER: _ClassVar[int]
    ISCACHED_FIELD_NUMBER: _ClassVar[int]
    PARSINGTIME_FIELD_NUMBER: _ClassVar[int]
    QUEUEINGTIME_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    explainAnalyze: str
    isCached: bool
    parsingTime: int
    queueingTime: int
    sessionId: str
    new_strategy: str
    def __init__(self, explainAnalyze: _Optional[str] = ..., isCached: bool = ..., parsingTime: _Optional[int] = ..., queueingTime: _Optional[int] = ..., sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class ClearRequest(_message.Message):
    __slots__ = ("engineIP", "sessionId", "queryId")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    queryId: str
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., queryId: _Optional[str] = ...) -> None: ...

class ClearResponse(_message.Message):
    __slots__ = ("sessionId", "new_strategy")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    new_strategy: str
    def __init__(self, sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class CancelQueryRequest(_message.Message):
    __slots__ = ("engineIP", "sessionId", "queryId")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    queryId: str
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., queryId: _Optional[str] = ...) -> None: ...

class CancelQueryResponse(_message.Message):
    __slots__ = ("sessionId", "new_strategy")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    new_strategy: str
    def __init__(self, sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class ClearOrCancelQueryRequest(_message.Message):
    __slots__ = ("engineIP", "sessionId", "queryId", "isDone")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    ISDONE_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    queryId: str
    isDone: bool
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., queryId: _Optional[str] = ..., isDone: bool = ...) -> None: ...

class ClearOrCancelQueryResponse(_message.Message):
    __slots__ = ("sessionId", "new_strategy")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    new_strategy: str
    def __init__(self, sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class ExplainRequest(_message.Message):
    __slots__ = ("engineIP", "sessionId", "queryId")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    queryId: str
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., queryId: _Optional[str] = ...) -> None: ...

class ExplainResponse(_message.Message):
    __slots__ = ("explain", "sessionId", "new_strategy")
    EXPLAIN_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    explain: str
    sessionId: str
    new_strategy: str
    def __init__(self, explain: _Optional[str] = ..., sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class AnalyzeQueryRequest(_message.Message):
    __slots__ = ("query", "catalog", "schema")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    CATALOG_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    query: str
    catalog: str
    schema: str
    def __init__(self, query: _Optional[str] = ..., catalog: _Optional[str] = ..., schema: _Optional[str] = ...) -> None: ...

class AnalyzeQueryResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StatusRequest(_message.Message):
    __slots__ = ("engineIP", "sessionId", "queryId")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    queryId: str
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., queryId: _Optional[str] = ...) -> None: ...

class StatusResponse(_message.Message):
    __slots__ = ("status", "rowCount", "sessionId", "new_strategy")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ROWCOUNT_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    status: bool
    rowCount: int
    sessionId: str
    new_strategy: str
    def __init__(self, status: bool = ..., rowCount: _Optional[int] = ..., sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class AddCatalogsRequest(_message.Message):
    __slots__ = ("sessionId", "json")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    JSON_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    json: str
    def __init__(self, sessionId: _Optional[str] = ..., json: _Optional[str] = ...) -> None: ...

class AddCatalogsResponse(_message.Message):
    __slots__ = ("sessionId",)
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    def __init__(self, sessionId: _Optional[str] = ...) -> None: ...

class RefreshCatalogsRequest(_message.Message):
    __slots__ = ("sessionId",)
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    def __init__(self, sessionId: _Optional[str] = ...) -> None: ...

class RefreshCatalogsResponse(_message.Message):
    __slots__ = ("sessionId",)
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    def __init__(self, sessionId: _Optional[str] = ...) -> None: ...

class GetAddCatalogsRequest(_message.Message):
    __slots__ = ("sessionId",)
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    def __init__(self, sessionId: _Optional[str] = ...) -> None: ...

class GetAddCatalogsResponse(_message.Message):
    __slots__ = ("status", "failures", "sessionId")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    FAILURES_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    status: str
    failures: _containers.RepeatedCompositeFieldContainer[FailedSchemaElement]
    sessionId: str
    def __init__(self, status: _Optional[str] = ..., failures: _Optional[_Iterable[_Union[FailedSchemaElement, _Mapping]]] = ..., sessionId: _Optional[str] = ...) -> None: ...

class GetCatalogesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetCatalogesResponse(_message.Message):
    __slots__ = ("catalogResponses",)
    CATALOGRESPONSES_FIELD_NUMBER: _ClassVar[int]
    catalogResponses: _containers.RepeatedCompositeFieldContainer[CatalogResponse]
    def __init__(self, catalogResponses: _Optional[_Iterable[_Union[CatalogResponse, _Mapping]]] = ...) -> None: ...

class GetSchemaNamesRequest(_message.Message):
    __slots__ = ("sessionId",)
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    def __init__(self, sessionId: _Optional[str] = ...) -> None: ...

class GetSchemaNamesV2Request(_message.Message):
    __slots__ = ("sessionId", "catalog")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    CATALOG_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    catalog: str
    def __init__(self, sessionId: _Optional[str] = ..., catalog: _Optional[str] = ...) -> None: ...

class GetSchemaNamesResponse(_message.Message):
    __slots__ = ("schemas", "sessionId", "new_strategy")
    SCHEMAS_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    schemas: _containers.RepeatedScalarFieldContainer[str]
    sessionId: str
    new_strategy: str
    def __init__(self, schemas: _Optional[_Iterable[str]] = ..., sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class GetTablesRequest(_message.Message):
    __slots__ = ("sessionId", "schema")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    schema: str
    def __init__(self, sessionId: _Optional[str] = ..., schema: _Optional[str] = ...) -> None: ...

class GetTablesV2Request(_message.Message):
    __slots__ = ("sessionId", "schema", "catalog")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    CATALOG_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    schema: str
    catalog: str
    def __init__(self, sessionId: _Optional[str] = ..., schema: _Optional[str] = ..., catalog: _Optional[str] = ...) -> None: ...

class GetTablesResponse(_message.Message):
    __slots__ = ("tables", "sessionId", "new_strategy")
    TABLES_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    tables: _containers.RepeatedScalarFieldContainer[str]
    sessionId: str
    new_strategy: str
    def __init__(self, tables: _Optional[_Iterable[str]] = ..., sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class GetColumnsRequest(_message.Message):
    __slots__ = ("sessionId", "schema", "table")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    TABLE_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    schema: str
    table: str
    def __init__(self, sessionId: _Optional[str] = ..., schema: _Optional[str] = ..., table: _Optional[str] = ...) -> None: ...

class GetColumnsV2Request(_message.Message):
    __slots__ = ("sessionId", "schema", "table", "catalog")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    TABLE_FIELD_NUMBER: _ClassVar[int]
    CATALOG_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    schema: str
    table: str
    catalog: str
    def __init__(self, sessionId: _Optional[str] = ..., schema: _Optional[str] = ..., table: _Optional[str] = ..., catalog: _Optional[str] = ...) -> None: ...

class GetColumnsResponse(_message.Message):
    __slots__ = ("fieldInfo", "sessionId", "new_strategy")
    FIELDINFO_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    NEW_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    fieldInfo: _containers.RepeatedCompositeFieldContainer[GFieldInfo]
    sessionId: str
    new_strategy: str
    def __init__(self, fieldInfo: _Optional[_Iterable[_Union[GFieldInfo, _Mapping]]] = ..., sessionId: _Optional[str] = ..., new_strategy: _Optional[str] = ...) -> None: ...

class UpdateUsersRequest(_message.Message):
    __slots__ = ("users",)
    USERS_FIELD_NUMBER: _ClassVar[int]
    users: bytes
    def __init__(self, users: _Optional[bytes] = ...) -> None: ...

class UpdateUsersResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SetPropsRequest(_message.Message):
    __slots__ = ("sessionId", "props")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    PROPS_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    props: str
    def __init__(self, sessionId: _Optional[str] = ..., props: _Optional[str] = ...) -> None: ...

class SetPropsResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DryRunRequest(_message.Message):
    __slots__ = ("engineIP", "sessionId", "schema", "queryString")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    QUERYSTRING_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    schema: str
    queryString: str
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., schema: _Optional[str] = ..., queryString: _Optional[str] = ...) -> None: ...

class DryRunRequestV2(_message.Message):
    __slots__ = ("engineIP", "sessionId", "schema", "queryString", "catalog")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    QUERYSTRING_FIELD_NUMBER: _ClassVar[int]
    CATALOG_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    schema: str
    queryString: str
    catalog: str
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., schema: _Optional[str] = ..., queryString: _Optional[str] = ..., catalog: _Optional[str] = ...) -> None: ...

class DryRunResponse(_message.Message):
    __slots__ = ("dryrunValue",)
    DRYRUNVALUE_FIELD_NUMBER: _ClassVar[int]
    dryrunValue: str
    def __init__(self, dryrunValue: _Optional[str] = ...) -> None: ...

class RemoteChunkRequest(_message.Message):
    __slots__ = ("originalQueryId", "remoteQueryId", "sQueryHash")
    ORIGINALQUERYID_FIELD_NUMBER: _ClassVar[int]
    REMOTEQUERYID_FIELD_NUMBER: _ClassVar[int]
    SQUERYHASH_FIELD_NUMBER: _ClassVar[int]
    originalQueryId: str
    remoteQueryId: str
    sQueryHash: str
    def __init__(self, originalQueryId: _Optional[str] = ..., remoteQueryId: _Optional[str] = ..., sQueryHash: _Optional[str] = ...) -> None: ...

class RemoteChunkResponse(_message.Message):
    __slots__ = ("error", "chunk")
    ERROR_FIELD_NUMBER: _ClassVar[int]
    CHUNK_FIELD_NUMBER: _ClassVar[int]
    error: str
    chunk: bytes
    def __init__(self, error: _Optional[str] = ..., chunk: _Optional[bytes] = ...) -> None: ...

class GetDynamicParamsRequest(_message.Message):
    __slots__ = ("engineIP", "sessionId", "queryId")
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    engineIP: str
    sessionId: str
    queryId: str
    def __init__(self, engineIP: _Optional[str] = ..., sessionId: _Optional[str] = ..., queryId: _Optional[str] = ...) -> None: ...

class GetDynamicParamsResponse(_message.Message):
    __slots__ = ("params", "sessionId")
    PARAMS_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    params: _containers.RepeatedCompositeFieldContainer[ParameterValue]
    sessionId: str
    def __init__(self, params: _Optional[_Iterable[_Union[ParameterValue, _Mapping]]] = ..., sessionId: _Optional[str] = ...) -> None: ...

class GFieldInfo(_message.Message):
    __slots__ = ("fieldName", "fieldType")
    FIELDNAME_FIELD_NUMBER: _ClassVar[int]
    FIELDTYPE_FIELD_NUMBER: _ClassVar[int]
    fieldName: str
    fieldType: str
    def __init__(self, fieldName: _Optional[str] = ..., fieldType: _Optional[str] = ...) -> None: ...

class FailedSchemaElement(_message.Message):
    __slots__ = ("name", "type", "reason")
    NAME_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    name: str
    type: str
    reason: str
    def __init__(self, name: _Optional[str] = ..., type: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...

class CatalogResponse(_message.Message):
    __slots__ = ("name", "isDefault")
    NAME_FIELD_NUMBER: _ClassVar[int]
    ISDEFAULT_FIELD_NUMBER: _ClassVar[int]
    name: str
    isDefault: bool
    def __init__(self, name: _Optional[str] = ..., isDefault: bool = ...) -> None: ...

class ParameterValue(_message.Message):
    __slots__ = ("index", "type", "value")
    INDEX_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    index: int
    type: str
    value: str
    def __init__(self, index: _Optional[int] = ..., type: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

class UserAccessInfo(_message.Message):
    __slots__ = ("uuid", "userName", "tokens")
    UUID_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    TOKENS_FIELD_NUMBER: _ClassVar[int]
    uuid: str
    userName: str
    tokens: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, uuid: _Optional[str] = ..., userName: _Optional[str] = ..., tokens: _Optional[_Iterable[str]] = ...) -> None: ...

class ExistingQuery(_message.Message):
    __slots__ = ("queryId", "elapsedTimeMillis")
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    ELAPSEDTIMEMILLIS_FIELD_NUMBER: _ClassVar[int]
    queryId: str
    elapsedTimeMillis: int
    def __init__(self, queryId: _Optional[str] = ..., elapsedTimeMillis: _Optional[int] = ...) -> None: ...

class SyncSchemaRequest(_message.Message):
    __slots__ = ("catalog", "database", "queryId", "isReplace")
    CATALOG_FIELD_NUMBER: _ClassVar[int]
    DATABASE_FIELD_NUMBER: _ClassVar[int]
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    ISREPLACE_FIELD_NUMBER: _ClassVar[int]
    catalog: str
    database: str
    queryId: str
    isReplace: bool
    def __init__(self, catalog: _Optional[str] = ..., database: _Optional[str] = ..., queryId: _Optional[str] = ..., isReplace: bool = ...) -> None: ...

class SyncSchemaResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class HealthCheckRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class HealthCheckResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CreateDataFrameRequest(_message.Message):
    __slots__ = ("parquetFilePath", "catalog", "schema", "table", "sessionId", "engineIP", "dataframeNumber", "createFromParquet")
    PARQUETFILEPATH_FIELD_NUMBER: _ClassVar[int]
    CATALOG_FIELD_NUMBER: _ClassVar[int]
    SCHEMA_FIELD_NUMBER: _ClassVar[int]
    TABLE_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    DATAFRAMENUMBER_FIELD_NUMBER: _ClassVar[int]
    CREATEFROMPARQUET_FIELD_NUMBER: _ClassVar[int]
    parquetFilePath: str
    catalog: str
    schema: str
    table: str
    sessionId: str
    engineIP: str
    dataframeNumber: int
    createFromParquet: bool
    def __init__(self, parquetFilePath: _Optional[str] = ..., catalog: _Optional[str] = ..., schema: _Optional[str] = ..., table: _Optional[str] = ..., sessionId: _Optional[str] = ..., engineIP: _Optional[str] = ..., dataframeNumber: _Optional[int] = ..., createFromParquet: bool = ...) -> None: ...

class CreateDataFrameResponse(_message.Message):
    __slots__ = ("queryId",)
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    queryId: str
    def __init__(self, queryId: _Optional[str] = ...) -> None: ...

class ProjectionOnDataFrameRequest(_message.Message):
    __slots__ = ("queryId", "dataframeNumber", "sessionId", "engineIP", "field")
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    DATAFRAMENUMBER_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    FIELD_FIELD_NUMBER: _ClassVar[int]
    queryId: str
    dataframeNumber: int
    sessionId: str
    engineIP: str
    field: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, queryId: _Optional[str] = ..., dataframeNumber: _Optional[int] = ..., sessionId: _Optional[str] = ..., engineIP: _Optional[str] = ..., field: _Optional[_Iterable[str]] = ...) -> None: ...

class ProjectionOnDataFrameResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AggregateOnDataFrameRequest(_message.Message):
    __slots__ = ("queryId", "dataframeNumber", "sessionId", "engineIP", "aggregateFunctionMap", "groupBy")
    class AggregateFunctionMapEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: AggregateFunction
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[AggregateFunction, str]] = ...) -> None: ...
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    DATAFRAMENUMBER_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    AGGREGATEFUNCTIONMAP_FIELD_NUMBER: _ClassVar[int]
    GROUPBY_FIELD_NUMBER: _ClassVar[int]
    queryId: str
    dataframeNumber: int
    sessionId: str
    engineIP: str
    aggregateFunctionMap: _containers.ScalarMap[str, AggregateFunction]
    groupBy: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, queryId: _Optional[str] = ..., dataframeNumber: _Optional[int] = ..., sessionId: _Optional[str] = ..., engineIP: _Optional[str] = ..., aggregateFunctionMap: _Optional[_Mapping[str, AggregateFunction]] = ..., groupBy: _Optional[_Iterable[str]] = ...) -> None: ...

class AggregateOnDataFrameResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class FilterOnDataFrameRequest(_message.Message):
    __slots__ = ("queryId", "dataframeNumber", "sessionId", "engineIP", "whereClause")
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    DATAFRAMENUMBER_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    WHERECLAUSE_FIELD_NUMBER: _ClassVar[int]
    queryId: str
    dataframeNumber: int
    sessionId: str
    engineIP: str
    whereClause: str
    def __init__(self, queryId: _Optional[str] = ..., dataframeNumber: _Optional[int] = ..., sessionId: _Optional[str] = ..., engineIP: _Optional[str] = ..., whereClause: _Optional[str] = ...) -> None: ...

class FilterOnDataFrameResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class OrderByOnDataFrameRequest(_message.Message):
    __slots__ = ("queryId", "dataframeNumber", "sessionId", "engineIP", "orderByFieldMap")
    class OrderByFieldMapEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: SortDirection
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[SortDirection, str]] = ...) -> None: ...
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    DATAFRAMENUMBER_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    ORDERBYFIELDMAP_FIELD_NUMBER: _ClassVar[int]
    queryId: str
    dataframeNumber: int
    sessionId: str
    engineIP: str
    orderByFieldMap: _containers.ScalarMap[str, SortDirection]
    def __init__(self, queryId: _Optional[str] = ..., dataframeNumber: _Optional[int] = ..., sessionId: _Optional[str] = ..., engineIP: _Optional[str] = ..., orderByFieldMap: _Optional[_Mapping[str, SortDirection]] = ...) -> None: ...

class OrderByOnDataFrameResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class LimitOnDataFrameRequest(_message.Message):
    __slots__ = ("queryId", "dataframeNumber", "sessionId", "engineIP", "fetchLimit")
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    DATAFRAMENUMBER_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    FETCHLIMIT_FIELD_NUMBER: _ClassVar[int]
    queryId: str
    dataframeNumber: int
    sessionId: str
    engineIP: str
    fetchLimit: int
    def __init__(self, queryId: _Optional[str] = ..., dataframeNumber: _Optional[int] = ..., sessionId: _Optional[str] = ..., engineIP: _Optional[str] = ..., fetchLimit: _Optional[int] = ...) -> None: ...

class LimitOnDataFrameResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ExecuteDataFrameRequest(_message.Message):
    __slots__ = ("queryId", "dataframeNumber", "sessionId", "engineIP")
    QUERYID_FIELD_NUMBER: _ClassVar[int]
    DATAFRAMENUMBER_FIELD_NUMBER: _ClassVar[int]
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    queryId: str
    dataframeNumber: int
    sessionId: str
    engineIP: str
    def __init__(self, queryId: _Optional[str] = ..., dataframeNumber: _Optional[int] = ..., sessionId: _Optional[str] = ..., engineIP: _Optional[str] = ...) -> None: ...

class ExecuteDataFrameResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DropUserContextRequest(_message.Message):
    __slots__ = ("sessionId", "engineIP")
    SESSIONID_FIELD_NUMBER: _ClassVar[int]
    ENGINEIP_FIELD_NUMBER: _ClassVar[int]
    sessionId: str
    engineIP: str
    def __init__(self, sessionId: _Optional[str] = ..., engineIP: _Optional[str] = ...) -> None: ...

class DropUserContextResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
