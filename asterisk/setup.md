# Asterisk CDR to Postgres Setup

This guide configures Asterisk to write CDR records into Postgres using `res_odbc` + `cdr_adaptive_odbc`.

## 1) Required Config Files

Ensure these files exist in `asterisk/`:

- `res_odbc.conf`
- `cdr_adaptive_odbc.conf`
- `odbc.ini`
- `odbcinst.ini`
- `extensions.conf` (contains `CDR(userfield)` mapping for `CALL_ACTION_ID`)

## 2) Docker Mounts

`asterisk/docker-compose.yml` must mount:

- `../asterisk/res_odbc.conf:/etc/asterisk/res_odbc.conf`
- `../asterisk/cdr_adaptive_odbc.conf:/etc/asterisk/cdr_adaptive_odbc.conf`
- `../asterisk/odbc.ini:/etc/odbc.ini`
- `../asterisk/odbcinst.ini:/etc/odbcinst.ini`

## 3) Build / Recreate Asterisk Container

```bash
docker compose -f asterisk/docker-compose.yml up -d --build --force-recreate dialyra_asterisk
```

## 4) Install ODBC Packages (inside container)

Run both commands inside the container:

```bash
docker exec -it dialyra-asterisk sh -lc 'apt-get update && apt-get install -y unixodbc odbc-postgresql'
```

## 5) Validate ODBC Driver + DSN

```bash
docker exec -it dialyra-asterisk cat /etc/odbcinst.ini
docker exec -it dialyra-asterisk cat /etc/odbc.ini
docker exec -it dialyra-asterisk odbcinst -q -d
docker exec -it dialyra-asterisk odbcinst -q -s
docker exec -it dialyra-asterisk isql -v dialyra_pg dialyra_user dialyra_pass
```

If `isql` connects, DSN is valid.

## 6) Reload Asterisk ODBC/CDR Modules

```bash
docker exec -it dialyra-asterisk asterisk -rvvv
```

Inside Asterisk CLI:

```asterisk
module reload res_odbc.so
module reload cdr_adaptive_odbc.so
odbc show all
cdr show status
```

Expected:

- `Registered ODBC class 'pgcdr'`
- `Found adaptive CDR table cdr@pgcdr`
- `odbc show all` shows active connections

Note:

- `asterisk/docker-compose.yml` now waits for Postgres health (`service_healthy`) before starting Asterisk.
- After `up -d --build --force-recreate`, manual reloads are usually not required unless you changed config files at runtime.

## 7) Ensure CALL_ACTION_ID Is Stored in CDR

In `asterisk/extensions.conf` outbound dialplan:

```asterisk
same => n,Set(CDR(userfield)=call_action_id=${CALL_ACTION_ID})
```

Reload dialplan if changed:

```asterisk
dialplan reload
```

## 8) Verify CDR Rows in Postgres

After placing a test call:

```sql
SELECT start, answer, "end", disposition, duration, billsec, userfield
FROM cdr
ORDER BY start DESC
LIMIT 10;
```

Filter by call action id:

```sql
SELECT *
FROM cdr
WHERE userfield LIKE '%call_action_id=<ACTION_ID>%';
```

## 10) Automated CDR Table Creation

This repo includes an init SQL:

- `server/db/init/010_cdr_table.sql`

Compose mounts it into Postgres at `/docker-entrypoint-initdb.d`, so `cdr` is created automatically on **fresh** DB initialization.

Important:

- Postgres entrypoint scripts run only when the data directory is empty.
- If your DB volume already exists, run the `CREATE TABLE IF NOT EXISTS cdr (...)` SQL once manually.

## 9) Common Errors

- `Data source name not found`: DSN/driver mismatch in `odbc.ini` or `odbcinst.ini`.
- `Can't open lib ... psqlodbcw.so`: wrong driver path in `odbcinst.ini`.
- `No such connection 'pgcdr'`: `res_odbc` failed, then `cdr_adaptive_odbc` has no usable connection.
