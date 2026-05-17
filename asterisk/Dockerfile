FROM andrius/asterisk

COPY asterisk/extensions.conf /etc/asterisk/extensions.conf
COPY asterisk/pjsip.conf /etc/asterisk/pjsip.conf
COPY asterisk/manager.conf /etc/asterisk/manager.conf
COPY asterisk/ari.conf /etc/asterisk/ari.conf
COPY asterisk/realtime.conf /etc/asterisk/realtime.conf
COPY asterisk/sorcery.conf /etc/asterisk/sorcery.conf
COPY asterisk/extconfig.conf /etc/asterisk/extconfig.conf
COPY asterisk/res_pgsql.conf /etc/asterisk/res_pgsql.conf
COPY asterisk/res_odbc.conf /etc/asterisk/res_odbc.conf
COPY asterisk/cdr_adaptive_odbc.conf /etc/asterisk/cdr_adaptive_odbc.conf
COPY asterisk/odbc.ini /etc/odbc.ini

# Install unixODBC + PostgreSQL ODBC driver so cdr_adaptive_odbc can write to Postgres.
RUN set -eux; \
    if command -v apt-get >/dev/null 2>&1; then \
      apt-get update; \
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends unixodbc odbc-postgresql; \
      rm -rf /var/lib/apt/lists/*; \
      command -v odbcinst; \
      command -v isql; \
      dpkg -L odbc-postgresql | grep -E 'psqlodbc.*\.so|libodbcpsqlS\.so' >/dev/null; \
    elif command -v apk >/dev/null 2>&1; then \
      apk add --no-cache unixodbc psqlodbc; \
      command -v odbcinst; \
      command -v isql; \
    else \
      echo "Unsupported base image package manager; install unixODBC + PostgreSQL ODBC driver manually."; \
      exit 1; \
    fi

RUN mkdir -p /var/lib/asterisk/sounds/custom /var/spool/asterisk/monitor
