# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: e6x_engine.proto
# Protobuf Python Version: 5.26.1
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x10\x65\x36x_engine.proto\"y\n\x13\x41uthenticateRequest\x12\x0c\n\x04user\x18\x01 \x01(\t\x12\x10\n\x08password\x18\x02 \x01(\t\x12%\n\x18userNameForImpersonation\x18\x03 \x01(\tH\x00\x88\x01\x01\x42\x1b\n\x19_userNameForImpersonation\")\n\x14\x41uthenticateResponse\x12\x11\n\tsessionId\x18\x01 \x01(\t\"\xad\x02\n\x16IdentifyPlannerRequest\x12\x11\n\tsessionId\x18\x01 \x01(\t\x12U\n\x17\x66irstTimeRequestPayload\x18\x02 \x01(\x0b\x32/.IdentifyPlannerRequest.FirstTimeRequestPayloadH\x00\x88\x01\x01\x12*\n\rexistingQuery\x18\x03 \x01(\x0b\x32\x0e.ExistingQueryH\x01\x88\x01\x01\x1aO\n\x17\x46irstTimeRequestPayload\x12\x0e\n\x06schema\x18\x01 \x01(\t\x12\x0f\n\x07\x63\x61talog\x18\x02 \x01(\t\x12\x13\n\x0bqueryString\x18\x03 \x01(\tB\x1a\n\x18_firstTimeRequestPayloadB\x10\n\x0e_existingQuery\"\x84\x02\n\x17IdentifyPlannerResponse\x12%\n\rexistingQuery\x18\x01 \x01(\x0b\x32\x0e.ExistingQuery\x12\x16\n\tplannerIp\x18\x02 \x01(\tH\x00\x88\x01\x01\x12;\n\x0cqueueMessage\x18\x03 \x01(\x0e\x32%.IdentifyPlannerResponse.QueueMessage\x12\x11\n\tsessionId\x18\x04 \x01(\t\"L\n\x0cQueueMessage\x12\x0c\n\x08GO_AHEAD\x10\x00\x12\x1e\n\x1aWAITING_ON_PLANNER_SCALEUP\x10\x01\x12\x0e\n\nRATE_LIMIT\x10\x02\x42\x0c\n\n_plannerIp\"\xc6\x01\n\x17PrepareStatementRequest\x12\x11\n\tsessionId\x18\x01 \x01(\t\x12\x0e\n\x06schema\x18\x02 \x01(\t\x12\x13\n\x0bqueryString\x18\x03 \x01(\t\x12\x0f\n\x07quoting\x18\x04 \x01(\t\x12\x16\n\tplannerIp\x18\x05 \x01(\tH\x00\x88\x01\x01\x12*\n\rexistingQuery\x18\x06 \x01(\x0b\x32\x0e.ExistingQueryH\x01\x88\x01\x01\x42\x0c\n\n_plannerIpB\x10\n\x0e_existingQuery\"\xd9\x01\n\x19PrepareStatementV2Request\x12\x11\n\tsessionId\x18\x01 \x01(\t\x12\x0e\n\x06schema\x18\x02 \x01(\t\x12\x0f\n\x07\x63\x61talog\x18\x03 \x01(\t\x12\x13\n\x0bqueryString\x18\x04 \x01(\t\x12\x0f\n\x07quoting\x18\x05 \x01(\t\x12\x16\n\tplannerIp\x18\x06 \x01(\tH\x00\x88\x01\x01\x12*\n\rexistingQuery\x18\x07 \x01(\x0b\x32\x0e.ExistingQueryH\x01\x88\x01\x01\x42\x0c\n\n_plannerIpB\x10\n\x0e_existingQuery\"P\n\x18PrepareStatementResponse\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x0f\n\x07queryId\x18\x02 \x01(\t\x12\x11\n\tsessionId\x18\x03 \x01(\t\"g\n\x17\x45xecuteStatementRequest\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\x12\x16\n\x0eshouldNotCache\x18\x04 \x01(\x08\"\x8a\x01\n\x19\x45xecuteStatementV2Request\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\x12\x16\n\x0eshouldNotCache\x18\x04 \x01(\x08\x12\x1f\n\x06params\x18\x05 \x03(\x0b\x32\x0f.ParameterValue\"-\n\x18\x45xecuteStatementResponse\x12\x11\n\tsessionId\x18\x01 \x01(\t\"P\n\x18GetResultMetadataRequest\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\"F\n\x19GetResultMetadataResponse\x12\x16\n\x0eresultMetaData\x18\x01 \x01(\x0c\x12\x11\n\tsessionId\x18\x02 \x01(\t\"Q\n\x19GetNextResultBatchRequest\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\"D\n\x1aGetNextResultBatchResponse\x12\x13\n\x0bresultBatch\x18\x02 \x01(\x0c\x12\x11\n\tsessionId\x18\x03 \x01(\t\"M\n\x15\x45xplainAnalyzeRequest\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\"\x80\x01\n\x16\x45xplainAnalyzeResponse\x12\x16\n\x0e\x65xplainAnalyze\x18\x01 \x01(\t\x12\x10\n\x08isCached\x18\x02 \x01(\x08\x12\x13\n\x0bparsingTime\x18\x03 \x01(\x12\x12\x14\n\x0cqueueingTime\x18\x04 \x01(\x12\x12\x11\n\tsessionId\x18\x05 \x01(\t\"D\n\x0c\x43learRequest\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\"\"\n\rClearResponse\x12\x11\n\tsessionId\x18\x01 \x01(\t\"J\n\x12\x43\x61ncelQueryRequest\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\"(\n\x13\x43\x61ncelQueryResponse\x12\x11\n\tsessionId\x18\x01 \x01(\t\"Q\n\x19\x43learOrCancelQueryRequest\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\"/\n\x1a\x43learOrCancelQueryResponse\x12\x11\n\tsessionId\x18\x01 \x01(\t\"F\n\x0e\x45xplainRequest\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\"5\n\x0f\x45xplainResponse\x12\x0f\n\x07\x65xplain\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\"E\n\x13\x41nalyzeQueryRequest\x12\r\n\x05query\x18\x01 \x01(\t\x12\x0f\n\x07\x63\x61talog\x18\x02 \x01(\t\x12\x0e\n\x06schema\x18\x03 \x01(\t\"\x16\n\x14\x41nalyzeQueryResponse\"E\n\rStatusRequest\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\"E\n\x0eStatusResponse\x12\x0e\n\x06status\x18\x02 \x01(\x08\x12\x10\n\x08rowCount\x18\x03 \x01(\x12\x12\x11\n\tsessionId\x18\x04 \x01(\t\"5\n\x12\x41\x64\x64\x43\x61talogsRequest\x12\x11\n\tsessionId\x18\x01 \x01(\t\x12\x0c\n\x04json\x18\x02 \x01(\t\"(\n\x13\x41\x64\x64\x43\x61talogsResponse\x12\x11\n\tsessionId\x18\x01 \x01(\t\"+\n\x16RefreshCatalogsRequest\x12\x11\n\tsessionId\x18\x01 \x01(\t\",\n\x17RefreshCatalogsResponse\x12\x11\n\tsessionId\x18\x01 \x01(\t\"*\n\x15GetAddCatalogsRequest\x12\x11\n\tsessionId\x18\x01 \x01(\t\"c\n\x16GetAddCatalogsResponse\x12\x0e\n\x06status\x18\x01 \x01(\t\x12&\n\x08\x66\x61ilures\x18\x02 \x03(\x0b\x32\x14.FailedSchemaElement\x12\x11\n\tsessionId\x18\x03 \x01(\t\"\x15\n\x13GetCatalogesRequest\"B\n\x14GetCatalogesResponse\x12*\n\x10\x63\x61talogResponses\x18\x01 \x03(\x0b\x32\x10.CatalogResponse\"*\n\x15GetSchemaNamesRequest\x12\x11\n\tsessionId\x18\x01 \x01(\t\"=\n\x17GetSchemaNamesV2Request\x12\x11\n\tsessionId\x18\x01 \x01(\t\x12\x0f\n\x07\x63\x61talog\x18\x02 \x01(\t\"<\n\x16GetSchemaNamesResponse\x12\x0f\n\x07schemas\x18\x01 \x03(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\"5\n\x10GetTablesRequest\x12\x11\n\tsessionId\x18\x01 \x01(\t\x12\x0e\n\x06schema\x18\x02 \x01(\t\"H\n\x12GetTablesV2Request\x12\x11\n\tsessionId\x18\x01 \x01(\t\x12\x0e\n\x06schema\x18\x02 \x01(\t\x12\x0f\n\x07\x63\x61talog\x18\x03 \x01(\t\"6\n\x11GetTablesResponse\x12\x0e\n\x06tables\x18\x01 \x03(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\"E\n\x11GetColumnsRequest\x12\x11\n\tsessionId\x18\x01 \x01(\t\x12\x0e\n\x06schema\x18\x02 \x01(\t\x12\r\n\x05table\x18\x03 \x01(\t\"X\n\x13GetColumnsV2Request\x12\x11\n\tsessionId\x18\x01 \x01(\t\x12\x0e\n\x06schema\x18\x02 \x01(\t\x12\r\n\x05table\x18\x03 \x01(\t\x12\x0f\n\x07\x63\x61talog\x18\x04 \x01(\t\"G\n\x12GetColumnsResponse\x12\x1e\n\tfieldInfo\x18\x01 \x03(\x0b\x32\x0b.GFieldInfo\x12\x11\n\tsessionId\x18\x02 \x01(\t\"#\n\x12UpdateUsersRequest\x12\r\n\x05users\x18\x01 \x01(\x0c\"\x15\n\x13UpdateUsersResponse\"3\n\x0fSetPropsRequest\x12\x11\n\tsessionId\x18\x01 \x01(\t\x12\r\n\x05props\x18\x02 \x01(\t\"\x12\n\x10SetPropsResponse\"Y\n\rDryRunRequest\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0e\n\x06schema\x18\x03 \x01(\t\x12\x13\n\x0bqueryString\x18\x04 \x01(\t\"l\n\x0f\x44ryRunRequestV2\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0e\n\x06schema\x18\x03 \x01(\t\x12\x13\n\x0bqueryString\x18\x04 \x01(\t\x12\x0f\n\x07\x63\x61talog\x18\x05 \x01(\t\"%\n\x0e\x44ryRunResponse\x12\x13\n\x0b\x64ryrunValue\x18\x01 \x01(\t\"X\n\x12RemoteChunkRequest\x12\x17\n\x0foriginalQueryId\x18\x01 \x01(\t\x12\x15\n\rremoteQueryId\x18\x02 \x01(\t\x12\x12\n\nsQueryHash\x18\x03 \x01(\t\"3\n\x13RemoteChunkResponse\x12\r\n\x05\x65rror\x18\x01 \x01(\t\x12\r\n\x05\x63hunk\x18\x02 \x01(\x0c\"O\n\x17GetDynamicParamsRequest\x12\x10\n\x08\x65ngineIP\x18\x01 \x01(\t\x12\x11\n\tsessionId\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\"N\n\x18GetDynamicParamsResponse\x12\x1f\n\x06params\x18\x01 \x03(\x0b\x32\x0f.ParameterValue\x12\x11\n\tsessionId\x18\x02 \x01(\t\"2\n\nGFieldInfo\x12\x11\n\tfieldName\x18\x01 \x01(\t\x12\x11\n\tfieldType\x18\x02 \x01(\t\"A\n\x13\x46\x61iledSchemaElement\x12\x0c\n\x04name\x18\x01 \x01(\t\x12\x0c\n\x04type\x18\x02 \x01(\t\x12\x0e\n\x06reason\x18\x03 \x01(\t\"2\n\x0f\x43\x61talogResponse\x12\x0c\n\x04name\x18\x01 \x01(\t\x12\x11\n\tisDefault\x18\x02 \x01(\x08\"<\n\x0eParameterValue\x12\r\n\x05index\x18\x01 \x01(\x11\x12\x0c\n\x04type\x18\x02 \x01(\t\x12\r\n\x05value\x18\x03 \x01(\t\"@\n\x0eUserAccessInfo\x12\x0c\n\x04uuid\x18\x01 \x01(\t\x12\x10\n\x08userName\x18\x02 \x01(\t\x12\x0e\n\x06tokens\x18\x03 \x03(\t\";\n\rExistingQuery\x12\x0f\n\x07queryId\x18\x01 \x01(\t\x12\x19\n\x11\x65lapsedTimeMillis\x18\x02 \x01(\x03\"Z\n\x11SyncSchemaRequest\x12\x0f\n\x07\x63\x61talog\x18\x01 \x01(\t\x12\x10\n\x08\x64\x61tabase\x18\x02 \x01(\t\x12\x0f\n\x07queryId\x18\x03 \x01(\t\x12\x11\n\tisReplace\x18\x04 \x01(\x08\"\x14\n\x12SyncSchemaResponse2\xe5\x0f\n\x12QueryEngineService\x12;\n\x0c\x61uthenticate\x12\x14.AuthenticateRequest\x1a\x15.AuthenticateResponse\x12\x44\n\x0fidentifyPlanner\x12\x17.IdentifyPlannerRequest\x1a\x18.IdentifyPlannerResponse\x12G\n\x10prepareStatement\x12\x18.PrepareStatementRequest\x1a\x19.PrepareStatementResponse\x12K\n\x12prepareStatementV2\x12\x1a.PrepareStatementV2Request\x1a\x19.PrepareStatementResponse\x12G\n\x10\x65xecuteStatement\x12\x18.ExecuteStatementRequest\x1a\x19.ExecuteStatementResponse\x12K\n\x12\x65xecuteStatementV2\x12\x1a.ExecuteStatementV2Request\x1a\x19.ExecuteStatementResponse\x12J\n\x11getResultMetadata\x12\x19.GetResultMetadataRequest\x1a\x1a.GetResultMetadataResponse\x12G\n\x10getDynamicParams\x12\x18.GetDynamicParamsRequest\x1a\x19.GetDynamicParamsResponse\x12M\n\x12getNextResultBatch\x12\x1a.GetNextResultBatchRequest\x1a\x1b.GetNextResultBatchResponse\x12\x41\n\x0e\x65xplainAnalyze\x12\x16.ExplainAnalyzeRequest\x1a\x17.ExplainAnalyzeResponse\x12&\n\x05\x63lear\x12\r.ClearRequest\x1a\x0e.ClearResponse\x12\x38\n\x0b\x63\x61ncelQuery\x12\x13.CancelQueryRequest\x1a\x14.CancelQueryResponse\x12M\n\x12\x63learOrCancelQuery\x12\x1a.ClearOrCancelQueryRequest\x1a\x1b.ClearOrCancelQueryResponse\x12\x36\n\x0bsyncSchemas\x12\x12.SyncSchemaRequest\x1a\x13.SyncSchemaResponse\x12;\n\x0c\x61nalyzeQuery\x12\x14.AnalyzeQueryRequest\x1a\x15.AnalyzeQueryResponse\x12,\n\x07\x65xplain\x12\x0f.ExplainRequest\x1a\x10.ExplainResponse\x12)\n\x06status\x12\x0e.StatusRequest\x1a\x0f.StatusResponse\x12\x38\n\x0b\x61\x64\x64\x43\x61talogs\x12\x13.AddCatalogsRequest\x1a\x14.AddCatalogsResponse\x12\x44\n\x0frefreshCatalogs\x12\x17.RefreshCatalogsRequest\x1a\x18.RefreshCatalogsResponse\x12I\n\x16getAddCatalogsResponse\x12\x16.GetAddCatalogsRequest\x1a\x17.GetAddCatalogsResponse\x12;\n\x0cgetCataloges\x12\x14.GetCatalogesRequest\x1a\x15.GetCatalogesResponse\x12\x41\n\x0egetSchemaNames\x12\x16.GetSchemaNamesRequest\x1a\x17.GetSchemaNamesResponse\x12\x45\n\x10getSchemaNamesV2\x12\x18.GetSchemaNamesV2Request\x1a\x17.GetSchemaNamesResponse\x12\x32\n\tgetTables\x12\x11.GetTablesRequest\x1a\x12.GetTablesResponse\x12\x36\n\x0bgetTablesV2\x12\x13.GetTablesV2Request\x1a\x12.GetTablesResponse\x12\x35\n\ngetColumns\x12\x12.GetColumnsRequest\x1a\x13.GetColumnsResponse\x12\x39\n\x0cgetColumnsV2\x12\x14.GetColumnsV2Request\x1a\x13.GetColumnsResponse\x12\x38\n\x0bupdateUsers\x12\x13.UpdateUsersRequest\x1a\x14.UpdateUsersResponse\x12/\n\x08setProps\x12\x10.SetPropsRequest\x1a\x11.SetPropsResponse\x12)\n\x06\x64ryRun\x12\x0e.DryRunRequest\x1a\x0f.DryRunResponse\x12-\n\x08\x64ryRunV2\x12\x10.DryRunRequestV2\x1a\x0f.DryRunResponse\x12\x45\n\x18getNextRemoteCachedChunk\x12\x13.RemoteChunkRequest\x1a\x14.RemoteChunkResponseB\x16\n\x12io.e6x.engine.grpcP\x01\x62\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'e6x_engine_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
  _globals['DESCRIPTOR']._loaded_options = None
  _globals['DESCRIPTOR']._serialized_options = b'\n\022io.e6x.engine.grpcP\001'
  _globals['_AUTHENTICATEREQUEST']._serialized_start=20
  _globals['_AUTHENTICATEREQUEST']._serialized_end=141
  _globals['_AUTHENTICATERESPONSE']._serialized_start=143
  _globals['_AUTHENTICATERESPONSE']._serialized_end=184
  _globals['_IDENTIFYPLANNERREQUEST']._serialized_start=187
  _globals['_IDENTIFYPLANNERREQUEST']._serialized_end=488
  _globals['_IDENTIFYPLANNERREQUEST_FIRSTTIMEREQUESTPAYLOAD']._serialized_start=363
  _globals['_IDENTIFYPLANNERREQUEST_FIRSTTIMEREQUESTPAYLOAD']._serialized_end=442
  _globals['_IDENTIFYPLANNERRESPONSE']._serialized_start=491
  _globals['_IDENTIFYPLANNERRESPONSE']._serialized_end=751
  _globals['_IDENTIFYPLANNERRESPONSE_QUEUEMESSAGE']._serialized_start=661
  _globals['_IDENTIFYPLANNERRESPONSE_QUEUEMESSAGE']._serialized_end=737
  _globals['_PREPARESTATEMENTREQUEST']._serialized_start=754
  _globals['_PREPARESTATEMENTREQUEST']._serialized_end=952
  _globals['_PREPARESTATEMENTV2REQUEST']._serialized_start=955
  _globals['_PREPARESTATEMENTV2REQUEST']._serialized_end=1172
  _globals['_PREPARESTATEMENTRESPONSE']._serialized_start=1174
  _globals['_PREPARESTATEMENTRESPONSE']._serialized_end=1254
  _globals['_EXECUTESTATEMENTREQUEST']._serialized_start=1256
  _globals['_EXECUTESTATEMENTREQUEST']._serialized_end=1359
  _globals['_EXECUTESTATEMENTV2REQUEST']._serialized_start=1362
  _globals['_EXECUTESTATEMENTV2REQUEST']._serialized_end=1500
  _globals['_EXECUTESTATEMENTRESPONSE']._serialized_start=1502
  _globals['_EXECUTESTATEMENTRESPONSE']._serialized_end=1547
  _globals['_GETRESULTMETADATAREQUEST']._serialized_start=1549
  _globals['_GETRESULTMETADATAREQUEST']._serialized_end=1629
  _globals['_GETRESULTMETADATARESPONSE']._serialized_start=1631
  _globals['_GETRESULTMETADATARESPONSE']._serialized_end=1701
  _globals['_GETNEXTRESULTBATCHREQUEST']._serialized_start=1703
  _globals['_GETNEXTRESULTBATCHREQUEST']._serialized_end=1784
  _globals['_GETNEXTRESULTBATCHRESPONSE']._serialized_start=1786
  _globals['_GETNEXTRESULTBATCHRESPONSE']._serialized_end=1854
  _globals['_EXPLAINANALYZEREQUEST']._serialized_start=1856
  _globals['_EXPLAINANALYZEREQUEST']._serialized_end=1933
  _globals['_EXPLAINANALYZERESPONSE']._serialized_start=1936
  _globals['_EXPLAINANALYZERESPONSE']._serialized_end=2064
  _globals['_CLEARREQUEST']._serialized_start=2066
  _globals['_CLEARREQUEST']._serialized_end=2134
  _globals['_CLEARRESPONSE']._serialized_start=2136
  _globals['_CLEARRESPONSE']._serialized_end=2170
  _globals['_CANCELQUERYREQUEST']._serialized_start=2172
  _globals['_CANCELQUERYREQUEST']._serialized_end=2246
  _globals['_CANCELQUERYRESPONSE']._serialized_start=2248
  _globals['_CANCELQUERYRESPONSE']._serialized_end=2288
  _globals['_CLEARORCANCELQUERYREQUEST']._serialized_start=2290
  _globals['_CLEARORCANCELQUERYREQUEST']._serialized_end=2371
  _globals['_CLEARORCANCELQUERYRESPONSE']._serialized_start=2373
  _globals['_CLEARORCANCELQUERYRESPONSE']._serialized_end=2420
  _globals['_EXPLAINREQUEST']._serialized_start=2422
  _globals['_EXPLAINREQUEST']._serialized_end=2492
  _globals['_EXPLAINRESPONSE']._serialized_start=2494
  _globals['_EXPLAINRESPONSE']._serialized_end=2547
  _globals['_ANALYZEQUERYREQUEST']._serialized_start=2549
  _globals['_ANALYZEQUERYREQUEST']._serialized_end=2618
  _globals['_ANALYZEQUERYRESPONSE']._serialized_start=2620
  _globals['_ANALYZEQUERYRESPONSE']._serialized_end=2642
  _globals['_STATUSREQUEST']._serialized_start=2644
  _globals['_STATUSREQUEST']._serialized_end=2713
  _globals['_STATUSRESPONSE']._serialized_start=2715
  _globals['_STATUSRESPONSE']._serialized_end=2784
  _globals['_ADDCATALOGSREQUEST']._serialized_start=2786
  _globals['_ADDCATALOGSREQUEST']._serialized_end=2839
  _globals['_ADDCATALOGSRESPONSE']._serialized_start=2841
  _globals['_ADDCATALOGSRESPONSE']._serialized_end=2881
  _globals['_REFRESHCATALOGSREQUEST']._serialized_start=2883
  _globals['_REFRESHCATALOGSREQUEST']._serialized_end=2926
  _globals['_REFRESHCATALOGSRESPONSE']._serialized_start=2928
  _globals['_REFRESHCATALOGSRESPONSE']._serialized_end=2972
  _globals['_GETADDCATALOGSREQUEST']._serialized_start=2974
  _globals['_GETADDCATALOGSREQUEST']._serialized_end=3016
  _globals['_GETADDCATALOGSRESPONSE']._serialized_start=3018
  _globals['_GETADDCATALOGSRESPONSE']._serialized_end=3117
  _globals['_GETCATALOGESREQUEST']._serialized_start=3119
  _globals['_GETCATALOGESREQUEST']._serialized_end=3140
  _globals['_GETCATALOGESRESPONSE']._serialized_start=3142
  _globals['_GETCATALOGESRESPONSE']._serialized_end=3208
  _globals['_GETSCHEMANAMESREQUEST']._serialized_start=3210
  _globals['_GETSCHEMANAMESREQUEST']._serialized_end=3252
  _globals['_GETSCHEMANAMESV2REQUEST']._serialized_start=3254
  _globals['_GETSCHEMANAMESV2REQUEST']._serialized_end=3315
  _globals['_GETSCHEMANAMESRESPONSE']._serialized_start=3317
  _globals['_GETSCHEMANAMESRESPONSE']._serialized_end=3377
  _globals['_GETTABLESREQUEST']._serialized_start=3379
  _globals['_GETTABLESREQUEST']._serialized_end=3432
  _globals['_GETTABLESV2REQUEST']._serialized_start=3434
  _globals['_GETTABLESV2REQUEST']._serialized_end=3506
  _globals['_GETTABLESRESPONSE']._serialized_start=3508
  _globals['_GETTABLESRESPONSE']._serialized_end=3562
  _globals['_GETCOLUMNSREQUEST']._serialized_start=3564
  _globals['_GETCOLUMNSREQUEST']._serialized_end=3633
  _globals['_GETCOLUMNSV2REQUEST']._serialized_start=3635
  _globals['_GETCOLUMNSV2REQUEST']._serialized_end=3723
  _globals['_GETCOLUMNSRESPONSE']._serialized_start=3725
  _globals['_GETCOLUMNSRESPONSE']._serialized_end=3796
  _globals['_UPDATEUSERSREQUEST']._serialized_start=3798
  _globals['_UPDATEUSERSREQUEST']._serialized_end=3833
  _globals['_UPDATEUSERSRESPONSE']._serialized_start=3835
  _globals['_UPDATEUSERSRESPONSE']._serialized_end=3856
  _globals['_SETPROPSREQUEST']._serialized_start=3858
  _globals['_SETPROPSREQUEST']._serialized_end=3909
  _globals['_SETPROPSRESPONSE']._serialized_start=3911
  _globals['_SETPROPSRESPONSE']._serialized_end=3929
  _globals['_DRYRUNREQUEST']._serialized_start=3931
  _globals['_DRYRUNREQUEST']._serialized_end=4020
  _globals['_DRYRUNREQUESTV2']._serialized_start=4022
  _globals['_DRYRUNREQUESTV2']._serialized_end=4130
  _globals['_DRYRUNRESPONSE']._serialized_start=4132
  _globals['_DRYRUNRESPONSE']._serialized_end=4169
  _globals['_REMOTECHUNKREQUEST']._serialized_start=4171
  _globals['_REMOTECHUNKREQUEST']._serialized_end=4259
  _globals['_REMOTECHUNKRESPONSE']._serialized_start=4261
  _globals['_REMOTECHUNKRESPONSE']._serialized_end=4312
  _globals['_GETDYNAMICPARAMSREQUEST']._serialized_start=4314
  _globals['_GETDYNAMICPARAMSREQUEST']._serialized_end=4393
  _globals['_GETDYNAMICPARAMSRESPONSE']._serialized_start=4395
  _globals['_GETDYNAMICPARAMSRESPONSE']._serialized_end=4473
  _globals['_GFIELDINFO']._serialized_start=4475
  _globals['_GFIELDINFO']._serialized_end=4525
  _globals['_FAILEDSCHEMAELEMENT']._serialized_start=4527
  _globals['_FAILEDSCHEMAELEMENT']._serialized_end=4592
  _globals['_CATALOGRESPONSE']._serialized_start=4594
  _globals['_CATALOGRESPONSE']._serialized_end=4644
  _globals['_PARAMETERVALUE']._serialized_start=4646
  _globals['_PARAMETERVALUE']._serialized_end=4706
  _globals['_USERACCESSINFO']._serialized_start=4708
  _globals['_USERACCESSINFO']._serialized_end=4772
  _globals['_EXISTINGQUERY']._serialized_start=4774
  _globals['_EXISTINGQUERY']._serialized_end=4833
  _globals['_SYNCSCHEMAREQUEST']._serialized_start=4835
  _globals['_SYNCSCHEMAREQUEST']._serialized_end=4925
  _globals['_SYNCSCHEMARESPONSE']._serialized_start=4927
  _globals['_SYNCSCHEMARESPONSE']._serialized_end=4947
  _globals['_QUERYENGINESERVICE']._serialized_start=4950
  _globals['_QUERYENGINESERVICE']._serialized_end=6971
# @@protoc_insertion_point(module_scope)
