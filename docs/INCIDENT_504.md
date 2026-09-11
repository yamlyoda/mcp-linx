# Инцидент: 504 Gateway Timeout (nginx → Go → PostgreSQL)

Дата: 2026-09-11. VM Ubuntu 24.04, host PG_VM_HOST (см. Vault/env). Статус: ✅ решено.
Краткий журнал — в `diagnosis_state.md`, здесь — полный разбор.

## Архитектура

клиент → nginx (:80, www-data) → Go (:8080, app) → PostgreSQL (:5432).
`proxy_connect_timeout 3s` в nginx.

## Симптом

- `curl 127.0.0.1:8080/` → 200 + токен (backend OK)
- `curl localhost/` → 504 за ровно 3.0 с (= proxy_connect_timeout)

Ровно 3.0 с = подпись проблемы L3/L4 (SYN дропаются), а не медленного кода.

## Блокировка №1: backend → PostgreSQL (eBPF-фильтр systemd)

Лог app: `dial tcp 10.130.0.15:5432: i/o timeout`.
Но `sudo -u app psql -h 10.130.0.15 ...` — OK, и сырой TCP от app — OK.
Не мог подключиться именно процесс Go.

Подозрение — `IPAddressAllow/Deny` (eBPF cgroup_skb, дропают молча).
Но `systemctl show app | grep IPAddress` — пусто, в unit-файлах — ничего.

Правду показал bpftool:
- prog 106 `cgroup_skb sd_fw_egress` на app.service;
- map 11 `lpm_trie 4_app.service`, dump: один ключ `127.0.0.0/8`.
Whitelist только loopback → SYN к 10.130.0.15 дропался ядром до интерфейса.

Подтверждения: tcpdump на lo и eth0 во время запроса — 0 пакетов
к 10.130.0.15:5432; strace: `connect(10.130.0.15:5432) = EINPROGRESS`
и тишина. Поле IPAddressAllow в `systemctl show` появилось только
после явного drop-in — фильтр был навязан внешней системой, а не
описан в unit-файлах. eBPF — ground truth, unit-файлы — нет.

Фикс №1 — создан `/etc/systemd/system/app.service.d/allow-db.conf`:
[Service]
IPAddressAllow=127.0.0.0/8
IPAddressAllow=10.130.0.15/32
+ `daemon-reload && restart app`. Новая map: 2 элемента, direct — 200.

## Блокировка №2: nginx → backend (nftables + blackhole)

После фикса №1 backend — 200, через nginx — 504 за 3.0 с.
`error.log`: `upstream timed out ... upstream 127.0.0.1:8080`.
Проба `sudo -u www-data bash -c '>/dev/tcp/127.0.0.1/8080'` — висела.
netns одинаковый, фильтров на nginx нет, PrivateNetwork=no.

Находка:
nft list ruleset → table inet netpolicy:
  meta skuid 33 tcp dport 8080 meta mark set 0x64
skuid 33 = www-data. Каждый пакет nginx → :8080 маркируется 0x64.
ip rule: `fwmark 0x64 lookup 100`; `ip route show table 100`
= `blackhole default`. SYN уничтожался → 504 через 3 с.

Источник: юнит netpolicy.service → /usr/local/sbin/netpolicy-apply
(table 100, fwmark-правило, заливка /etc/netpolicy.nft).
Замысел — запрет наружу на 8080, но без исключения loopback под
правило попал и локальный трафик. Хук `type route priority mangle`
срабатывает до routing-решения, pref 100 бьёт раньше table local.
Обычный `iptables -L` этого не показывает.

Фикс №2 — в /etc/netpolicy.nft одна строка ДО маркировки
(бэкап /etc/netpolicy.nft.bak, затем `nft -f /etc/netpolicy.nft`):
  ip daddr 127.0.0.0/8 accept
Локальный nginx → 127.0.0.1:8080 идёт мимо маркировки, внешний
→ *:8080 по-прежнему в blackhole. Политика сохранена.

## Верификация

- curl 127.0.0.1:8080/ → 200, token из secrets за ~6 мс
- curl localhost/ → 200, token из secrets за ~6 мс
- curl -I 127.0.0.1/ → HTTP/1.1 200 OK
- psql SELECT token FROM secrets → тот же токен (end-to-end OK)

Не трогалось: DB_HOST=10.130.0.15 в /etc/default/app — корректно.
Postgres слушает только 10.130.0.15, на 127.0.0.1:5432 тишина,
в pg_hba.conf для app разрешён только 10.130.0.15/32.

## Изменённые файлы на сервере

- /etc/systemd/system/app.service.d/allow-db.conf (создан)
- /etc/netpolicy.nft (+1 строка, бэкап .bak)

## Выводы

1. Таймаут = proxy_connect_timeout → firewall/nft/routing, не код.
2. `systemctl show` может скрывать фильтр → проверять bpftool напрямую.
3. tcpdump с 0 пакетов при активном connect() = дроп ниже интерфейса.
4. skuid + fwmark + blackhole не видны в iptables -L; нужны nft,
   ip rule, ip route show table N.
5. В nftables accept для loopback ставить ДО маркировки.

## Runbook: 504 через MCP-Linx

Тот же путь диагностики, но через MCP tools (read-only, в `docs/skills/workflows.md`):

1. `nginx_upstream` → читает `proxy_connect_timeout_s` из конфига + `connect_ms` на сервер.
   Если `matches_proxy_connect_timeout: true` (или время ≈ таймауту) → SYN-дроп, не код.
2. `tcp_connect_as(user=www-data, host=127.0.0.1, port=8080)` → сработает, только если
   `plugins.netdiag.privileged_tools: true`; без него — вернёт готовую ручную команду.
3. `linux_firewall` → `marks: [{skuid, dport, mark}]` + `policy_routes`; наличие blackhole
   в таблице = та же связка fwmark → blackhole из фикса №2.
4. `service_ip_filter(unit=app.service)` → `declared` (unit-файлы, может быть пусто)
   vs `effective_allow` из LPM-trie (eBPF) → вердикт `hidden_filter` = фикс №1.
5. `tcpdump_probe` (privileged) → `packets_seen: 0` подтверждает дроп ниже интерфейса.

Корреляции (авто): `timeout==proxy_connect_timeout`, `per-uid`, `DB_HOST mismatch` —
`context_aggregator.py`, см. `docs/skills/correlations.md`.
