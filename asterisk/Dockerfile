FROM andrius/asterisk

COPY asterisk/extensions.conf /etc/asterisk/extensions.conf
COPY asterisk/pjsip.conf /etc/asterisk/pjsip.conf
COPY asterisk/manager.conf /etc/asterisk/manager.conf
COPY asterisk/ari.conf /etc/asterisk/ari.conf
COPY asterisk/realtime.conf /etc/asterisk/realtime.conf

RUN mkdir -p /var/lib/asterisk/sounds/custom /var/spool/asterisk/monitor
