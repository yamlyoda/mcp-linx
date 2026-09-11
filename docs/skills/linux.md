# Linux + Systemd — хост-уровень

Часть Skills (см. `docs/SKILLS.md`). Связки: `workflows.md`, корреляции — `correlations.md`.

## Linux Diagnostics (8 tools)

| Tool | Description |
|------|-------------|
| `linux_host_stats` | Host statistics (CPU, memory, load) |
| `linux_processes` | Running processes |
| `linux_logs` | System logs |
| `linux_network` | Network interfaces |
| `linux_firewall` | Firewall snapshot: nftables + iptables + policy routing (read-only) |
| `linux_disk` | Disk usage |
| `linux_memory` | Memory details |
| `linux_execute_command` | Execute read-only commands |

`linux_firewall` закрывает слепую зону INCIDENT_504: `iptables -L` не показывает nft-правила (skuid → fwmark) и blackhole-таблицы. Собирает `nft list ruleset`, `ip rule`, все таблицы маршрутов, `ufw status`.

## Systemd Services (5 tools)

| Tool | Description |
|------|-------------|
| `service_status` | Unit status (systemctl status/is-active) |
| `failed_units` | Failed units list |
| `service_logs` | Service logs via journalctl -u |
| `boot_analysis` | Boot time analysis (systemd-analyze blame) |
| `service_ip_filter` | Эффективный IP-фильтр юнита: unit-файлы + eBPF/bpftool (ground truth) |

`service_ip_filter` — главный урок INCIDENT_504: `systemctl show` может скрывать фильтр, навязанный внешней системой. eBPF map (`bpftool map dump`, LPM-trie whitelist) — ground truth, unit-файлы — нет.
