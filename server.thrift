namespace java io.e6x.engine.thrift

exception QueryProcessingException
{
    1: string reason,
}

exception AccessDeniedException
{
    1: string reason,
}

struct TFieldInfo
{
    1: string fieldName,
    2: string fieldType,
}

struct UserAccessInfo
{
    1: string uuid,
    2: string userName,
    3: list<string> tokens,
}


struct Status
{
    1: bool status
    2: i64 rowCount
}


service QueryEngineService
{
   void clear(1: string sessionId, 2: string queryId) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

   void cancelQuery(1: string sessionId, 2: string queryId) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

   string explain(1: string sessionId, 2: string queryId) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2), // Executor, Engine

   string dryRun(1: string sessionId, 2: string sSchema, 3: string sQueryString) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2), // Executor, Engine

   string explainAnalyze(1: string sessionId, 2: string queryId) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2), // Executor, Engine

   string prepareStatement(1: string sessionId, 2: string sSchemaName, 3: string query) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

   void executeStatement(1: string sessionId, 2: string queryId) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

   binary getNextResultRow(1: string sessionId, 2: string queryId) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

   binary getNextResultBatch(1: string sessionId, 2: string queryId) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

   binary getResultMetadata(1: string sessionId, 2: string queryId) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

   string authenticate(1: string user, 2: string password) throws (1: AccessDeniedException error),

   list<string> getTables(1: string sessionId, 2: string schema) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

   list<string> getSchemaNames(1: string sessionId) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

   list<TFieldInfo> getColumns(1: string sessionId, 2: string schema, 3: string table) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

   void updateUsers(1: binary userInfo) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

   void setProps(1: string sessionId, 2: string propMap) throws (1: AccessDeniedException error2),

   Status status(1: string sessionId, 2: string queryId) throws (1: QueryProcessingException error1, 2: AccessDeniedException error2),

}
