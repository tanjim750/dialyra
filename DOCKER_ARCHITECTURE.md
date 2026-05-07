# Dialyra Docker Layout

## Service folders

- `server/` → Flask API container files
- `fastagi/` → FastAGI TCP server container files
- `asterisk/` → Asterisk container files and telephony config
- `storage/` → shared runtime data
  - `storage/audio/` shared sounds
  - `storage/recordings/` call recordings

## Shared volume mapping

- Host `./storage/audio`:
  - Flask mount: `/data/audio`
  - Asterisk mount: `/var/lib/asterisk/sounds/custom`
- Host `./storage/recordings`:
  - Flask mount: `/data/recordings`
  - Asterisk mount: `/var/spool/asterisk/monitor`

## Network and exposure policy

- Private bridge network: `dialyra-net`
- Publicly exposed for telephony/media:
  - `5060/udp`, `5060/tcp`, `10000-10100/udp`
- Localhost-only admin/data ports:
  - AMI `127.0.0.1:5038`
  - FastAGI `127.0.0.1:4573`
  - PostgreSQL `127.0.0.1:5432`
  - Redis `127.0.0.1:6379`
