# e6data Python Connector

![version](https://img.shields.io/badge/version-1.0.0-blue.svg)

## Introduction

The e6data Connector for Python provides an interface for writing Python applications that can connect to e6data and perform operations.

To install the Python package, use the command below:
```shell
pip install e6data-python-connector
```
### Prerequisites

* Open Inbound Port 9000 in the Engine Cluster.
* Limit access to Port 9000 according to your organizational security policy. Public access is not encouraged.
* Generated Access Token in the e6data console.

### Creating connection

Use your e6data email id as a username and access token as a password.

```python
import e6xdb.e6x as edb

username = '<username>'  # Your e6data email id.
password = '<password>'  # Generated Access Token from e6data console.

host = '<host>'  # Host name or IP address of you cluster.
database = '<database>'  # Database name where you want to perform query.

port = 9000  # Engine port.

conn = edb.connect(
    host=host,
    port=port,
    username=username,
    database=database,
    password=password
)
```

### Performing query
Performing query

```python

query = 'SELECT * FROM <TABLE_NAME>'  # Replace with the actual query.

cursor = conn.cursor()
query_id = cursor.execute(query)  # execute function returns query id, can be use for aborting the query.
all_records = cursor.fetchall()
for row in all_records:
   print(row)
```

To fetch all the records.
```python
records = cursor.fetchall()
```

To fetch one record.
```python
record = cursor.fetchone()
```

To fetch limited records.
```python
limit = 500
records = cursor.fetchmany(limit)
```

To get execution plan after query execution.
```python
import json

query_planner = json.loads(cursor.explain_analyse())
```

To abort running query.
```python
query_id = '<query_id>'  # query id from execute function response.
cursor.cancel(query_id)
```

Switch database in existing connection.
```python
database = '<new_database_name>'  # Replace with the new database.
cursor = conn.cursor(database)
```

### Get Query Time Metrics
```python
import json
query = 'SELECT * FROM <TABLE_NAME>'

cursor = conn.cursor()
query_id = cursor.execute(query)  # execute function returns query id, can be use for aborting th query.
all_records = cursor.fetchall()

query_planner = json.loads(cursor.explain_analyse())

execution_time = query_planner.get("total_query_time")  # In milliseconds
queue_time = query_planner.get("executionQueueingTime")  # In milliseconds
parsing_time = query_planner.get("parsingTime")  # In milliseconds
row_count = query_planner.get('row_count_out')
```

### Get list of databases, tables or columns
The following code returns a dictionary of all databases, all tables and all columns connected to the cluster currently in use.
This function can be used without passing database name to get list of all databases.

```python
databases = conn.get_schema_names()  # To get list of databases.
print(databases)

database = '<database_name>'  # Replace with actual database name.
tables = conn.get_tables(database=database)  # To get list of tables from a database.
print(tables)

table_name = '<table_name>'  # Replace with actual table name.
columns = conn.get_tables(database=database, table=table_name)  # To get the list of columns from a table.
columns_with_type = list()
"""
Getting the column name and type.
"""
for column in columns:
   columns_with_type.append(dict(column_name=column.fieldName, column_type=column.fieldType))
print(columns_with_type)
```

### Code Hygiene
It is recommended to clear the cursor, close the cursor and close the connection after running a function as a best practice. 
This enhances performance by clearing old data from memory.

```python
cursor.clear() # Not needed when aborting a query
cursor.close()
conn.close()
```

### Code Example
The following code is an example.
```python
import e6xdb.e6x as edb
import json

username = '<username>'  # Your e6data email id.
password = '<password>'  # Generated Access Token from e6data console.

host = '<host>'  # Host name or IP address of you cluster.
database = '<database>'  # Database name where you want to perform query.

port = 9000  # Engine port.

sql_query = 'SELECT * FROM <TABLE_NAME>'  # Replace with the actual query.

conn = edb.connect(
    host=host,
    port=port,
    username=username,
    database=database,
    password=password
)

cursor = conn.cursor(db_name=database)
query_id = cursor.execute(sql_query)
all_records = cursor.fetchall()
planner_result = json.loads(cursor.explain_analyse())
execution_time = planner_result.get("total_query_time") / 1000  # Converting into seconds.
row_count = planner_result.get('row_count_out')
columns = [col[0] for col in cursor.description]  # Get the column names and merge with the records.
results = []
for row in all_records:
   row = dict(zip(columns, row))
   results.append(row)
   print(row)
print('Total row count {}, Execution Time (seconds): {}'.format(row_count, execution_time))
cursor.clear()
cursor.close()
conn.close()
```
