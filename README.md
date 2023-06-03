# e6data Python Connector

![version](https://img.shields.io/badge/version-1.0.8-blue.svg)

## Introduction

The e6data Connector for Python provides an interface for writing Python applications that can connect to e6data and perform operations.

To install the Python package, use the command below:
```shell
pip install e6data-python-connector
```
### Prerequisites

* Open Inbound Port 9000 in the Engine Cluster.
* Limit access to Port 9000 according to your organizational security policy. Public access is not encouraged.
* Access Token generated in the e6data console.

### Create a Connection

Use your e6data Email ID as the username and your access token as the password.

```python
import e6xdb.e6x as edb

username = '<username>'  # Your e6data Email ID.
password = '<password>'  # Access Token generated in the e6data console.

host = '<host>'  # IP address or hostname of the cluster to be used.
database = '<database>'  # # Database to perform the query on.
port = 9000  # Port of the e6data engine.

conn = edb.connect(
    host=host,
    port=port,
    username=username,
    database=database,
    password=password
)
```

### Perform a Queries & Get Results

```python

query = 'SELECT * FROM <TABLE_NAME>'  # Replace with the query.

cursor = conn.cursor()
query_id = cursor.execute(query)  # The execute function returns a unique query ID, which can be use to abort the query.
all_records = cursor.fetchall()
for row in all_records:
   print(row)
```

To fetch all the records:
```python
records = cursor.fetchall()
```

To fetch one record:
```python
record = cursor.fetchone()
```

To fetch limited records:
```python
limit = 500
records = cursor.fetchmany(limit)
```

To get the execution plan after query execution:
```python
import json

query_planner = json.loads(cursor.explain_analyse())
```

To abort a running query:
```python
query_id = '<query_id>'  # query id from execute function response.
cursor.cancel(query_id)
```

Switch database in an existing connection:
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

### Get Schema - a list of Databases, Tables or Columns
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
The following code is an example which combines a few functions described above.
```python
import e6xdb.e6x as edb
import json

username = '<username>'  # Your e6data Email ID.
password = '<password>'  # Access Token generated in the e6data console.

host = '<host>'  # IP address or hostname of the cluster to be used.
database = '<database>'  # # Database to perform the query on.
port = 9000  # Port of the e6data engine.

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
columns = [col[0] for col in cursor.description]  # Get the column names and merge them with the results.
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