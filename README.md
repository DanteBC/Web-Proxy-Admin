# Web Proxy Admin

Веб-панель администратора для управления локальными пользователями 3proxy, ipset/ipтаблицами и policy-routing через интерфейс AmneziaWG. Приложение написано на FastAPI, использует SQLite по умолчанию и Jinja2-интерфейс.

Логика маршрутизации:

```text
трафик 3proxy OUTPUT
        |
        v
 цепочка WEBPROXY_AWG
        |
        +-- dst в awg-force -> MARK 1 -> таблица 100 -> awg1
        +-- dst в ru-direct  -> RETURN (обычная маршрутизация хоста)
        +-- всё остальное    -> MARK 1 -> таблица 100 -> awg1
```

## Состав

- `app/` — FastAPI, API, пользователи, правила, статистика и шаблон аутентификации;
- `scripts/route_awg.py` — создание ipset-наборов, iptables-цепочки и маршрута таблицы `100`;
- `app/templates/3proxy.cfg.j2` — пример конфигурации 3proxy;
- `deploy/webproxy.service` — пример systemd-unit;
- `deploy/route-helper.sudoers` — пример ограниченного sudo-доступа;
- `tests/` — тесты парсера логов и генерации пользователей.

## Требования

Linux-хост с:

- Python 3.11+;
- systemd;
- 3proxy;
- AmneziaWG или совместимый WireGuard-интерфейс с именем `awg1`;
- утилитами `ip`, `ipset`, `iptables`, `systemctl`;
- правами на применение netfilter-routing либо systemd capability;
- доступом к `/etc/3proxy/`, `/var/log/3proxy/` и базе приложения.

Проверка:

```bash
python3 --version
systemctl --version
command -v ip ipset iptables systemctl 3proxy
```

Debian/Ubuntu установка системных утилит:

```bash
sudo apt update
sudo apt install -y python3 python3-venv iproute2 ipset iptables
```

Пакет 3proxy лучше устанавливать из репозитория вашей ОС или из проверенного пакета для вашей системы. Сервис должен называться `3proxy.service`; если пакет использует другой unit, измените `WEBPROXY_PROXY_SERVICE`.

## Быстрый запуск для разработки

```bash
cd /path/to/web-proxy
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Установка через `.[dev]` необязательна для production: используйте `pip install -e .` или пакетный способ развёртывания.

Приложение доступно по адресу `http://127.0.0.1:8000/login`.

Основные переменные окружения:

```dotenv
WEBPROXY_DATABASE_URL=sqlite:///./webproxy.db
WEBPROXY_SESSION_SECRET=случайная-длинная-строка
WEBPROXY_ADMIN_LOGIN=admin
WEBPROXY_ADMIN_PASSWORD=strong-password

WEBPROXY_PROXY_CONFIG=/etc/3proxy/3proxy.cfg
WEBPROXY_PROXY_USERS_FILE=/etc/3proxy/users
WEBPROXY_PROXY_LOG_FILE=/var/log/3proxy/3proxy.log
WEBPROXY_PROXY_SERVICE=3proxy.service
WEBPROXY_PROXY_USER=3proxy

WEBPROXY_ROUTING_SCRIPT=/usr/local/sbin/webproxy-routing
WEBPROXY_RU_URL=https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone
```

Сгенерируйте случайный ключ сессии:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Не используйте значение `change-me` за пределами тестового окружения.

## Настройка 3proxy

### 1. Создайте файлы

```bash
sudo install -d -m 0755 /etc/3proxy /var/log/3proxy
sudo install -d -m 0755 /run/3proxy
sudo touch /etc/3proxy/users
sudo touch /var/log/3proxy/3proxy.log
sudo chmod 0640 /etc/3proxy/users /var/log/3proxy/3proxy.log
sudo chown root:root /etc/3proxy/users
sudo chown 3proxy:3proxy /var/log/3proxy/3proxy.log
```

Если в системе пользователь 3proxy называется иначе, замените имя во всех командах и в `WEBPROXY_PROXY_USER`.

### 2. Базовый `3proxy.cfg`

Пример из проекта можно адаптировать как `/etc/3proxy/3proxy.cfg`:

```text
daemon
pidfile /run/3proxy/3proxy.pid
log /var/log/3proxy/3proxy.log D
logformat "- %t\t%U\t%C\t%R\t%I\t%O\t%E\t%p\t%T"
rotate 30

nserver 1.1.1.1
nserver 8.8.8.8
nscache 65536
timeouts 1 5 30 60 180 1800 15 60

internal 0.0.0.0
external 0.0.0.0

auth strong
users $/etc/3proxy/users

allow *
socks -p1080
proxy -p3128
```

Важно: у разных сборок 3proxy разные ключи/формат счетчиков и логов. Перед production-переходом проверьте бинарник:

```bash
sudo 3proxy --help
sudo 3proxy -v 2>&1 || true
sudo strings "$(command -v 3proxy)" | grep -E 'logformat|countin|countout|countall|counter' | sort -u
```

Не копируйте неизвестные директивы из различных сборок: сначала проверьте командой запуска и журналом конкретного сервиса.

### 3. Файл пользователей

Панель пишет строки в формате:

```text
alice:CL:пароль
bob:CL:пароль
```

Кавычки, двоеточия, переводы строк и пробелы в логине панель запрещает. Пароли в файле должны соответствовать требованиям конкретной сборки 3proxy. Если сборка использует хэшированный формат, в панели должно храниться и передаваться именно поддерживаемое сборкой значение.

Создать вручную пример:

```bash
sudo tee /etc/3proxy/users >/dev/null <<'EOF'
alice:CL:strong-password
bob:CL:strong-password
EOF
sudo chmod 0640 /etc/3proxy/users
sudo chown root:3proxy /etc/3proxy/users
```

### 4. Unit и перезагрузка

Проверьте существующий unit:

```bash
systemctl cat 3proxy
systemctl status 3proxy --no-pager
```

Для перезагрузки systemd должен поддерживать `ExecReload` или вызывать `SIGHUP`:

```ini
[Service]
ExecReload=/bin/kill -HUP $MAINPID
```

Если сборка не поддерживает reload без потери работы, добавьте отдельный unit-шаг с `ExecReload` и предварительно проверьте его на стенде.

После изменения конфигурации:

```bash
sudo 3proxy /etc/3proxy/3proxy.cfg
sudo systemctl restart 3proxy.service
sudo systemctl is-active 3proxy.service
sudo journalctl -u 3proxy.service -n 100 --no-pager
```

Вместо `restart` для штатного обновления используйте:

```bash
sudo systemctl reload 3proxy.service
```

Приложение также проверяет активное состояние через `systemctl is-active`.

## Настройка AmneziaWG

Основные требования:

1. ядро содержит AmneziaWG-модуль или пакеты AmneziaWG установлены;
2. интерфейс поднят под именем `awg1`;
3. туннель получает peer, ключи и адрес интерфейса из конфигурации;
4. маршрут default для таблицы `100` указывает именно на `awg1`;
5. при изменении состояния/переподключении туннеля route восстанавливается.

Проверьте интерфейс:

```bash
sudo ip link show awg1
sudo ip address show dev awg1
sudo wg show  awg1
sudo ip route show dev awg1
```

Установить default-route для отдельной таблицы вручную:

```bash
sudo ip route replace default dev awg1 table 100
sudo ip rule replace priority 100 fwmark 1 lookup 100
sudo ip route flush cache
```

Проверка policy-routing:

```bash
sudo ip rule show
sudo ip route show table 100
sudo ip route get 1.1.1.1
sudo ip route get 1.1.1.1 mark 1
```

Команда `ip route get ... mark 1` доступна только если утилита/ядро поддерживают опцию `mark`. Запустите альтернативу через `ip rule` и таблицу при необходимости.

Команды AWG отличаются в зависимости от способа установки. Как правило, конфигурация загружается утилитами/скриптом провайдера или Amnezia клиента с последующим созданием интерфейса `awg1`. Не используйте общий `wg-quick` для конфигураций с AWG-параметрами, если установленная сборка не поддерживает их синтаксис.

Для автоматического восстановления интерфейса используйте NetworkManager/dispatcher или systemd unit вашего AWG-инсталлятора. Unit приложения должен запускаться после AWG:

```ini
[Unit]
After=network-online.target awg.service
Wants=network-online.target
```

## Установка и настройка ipset/iptables

Установите утилиты:

```bash
sudo apt install -y ipset iptables
sudo modprobe ip_set
sudo modprobe ip_set_hash_net
```

Наборы создаются автоматически скриптом `scripts/route_awg.py`:

```text
ru-direct  — прямые IPv4-сети России и ручные исключения;
awg-force  — адреса и сети, принудительно направляемые через AWG.
```

Можно проверить и создать вручную:

```bash
sudo ipset create ru-direct hash:net family inet hashsize 4096 maxelem 1048576
sudo ipset create awg-force hash:net family inet hashsize 4096 maxelem 1048576
```

Загрузка российского списка из URL:

```bash
sudo python3 scripts/route_awg.py \
  --ru-url https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone
```

Из локального файла:

```bash
sudo python3 scripts/route_awg.py --ru-file /opt/ipdeny/ru.zone
```

Добавить прямое исключение:

```bash
sudo ipset add ru-direct 192.0.2.10 -exist
sudo ipset add ru-direct 198.51.100.0/24 -exist
```

Через приложение или скрипт:

```bash
sudo python3 scripts/route_awg.py --direct 192.0.2.10 198.51.100.0/24
```

Принудительно через AWG:

```bash
sudo ipset add awg-force 8.8.8.8 -exist
sudo ipset add awg-force 1.1.1.0/24 -exist
sudo python3 scripts/route_awg.py --force-awg 8.8.8.8 1.1.1.0/24
```

Удаление элементов:

```bash
sudo ipset del ru-direct 198.51.100.0/24
sudo ipset del awg-force 8.8.8.8
sudo python3 scripts/route_awg.py \
  --remove-direct 198.51.100.0/24 \
  --remove-force-awg 8.8.8.8
```

Просмотр:

```bash
sudo ipset list ru-direct
sudo ipset list awg-force
sudo iptables -t mangle -n -v -L WEBPROXY_AWG
sudo iptables -t mangle -n -v -L OUTPUT
sudo ip rule show
sudo ip route show table 100
```

Скрипт создаёт цепочку `WEBPROXY_AWG` приблизительно в таком виде:

```text
-j MARK --set-mark 1    для awg-force
-j RETURN               для ru-direct
-j MARK --set-mark 1    для всего остального
```

Затем цепочка вызывается из `OUTPUT` для UID пользователя 3proxy:

```bash
sudo iptables -t mangle -C OUTPUT -m owner --uid-owner 3proxy -j WEBPROXY_AWG
sudo iptables -t mangle -A OUTPUT -m owner --uid-owner 3proxy -j WEBPROXY_AWG
```

Команды UID-owner требуют запуска 3proxy от отдельного пользователя и могут не охватывать traffic дочерних процессов. Скрипт определяет UID пользователя `--proxy-user` или `3proxy` автоматически.

Если 3proxy форвардит существующий traffic хоста вместо создания исходящего traffic как конкретного UID, маркируйте нужный входящий интерфейс/сетевой интерфейс отдельно и не используйте broad-JUMP на весь `OUTPUT`.

## Команды ручного iptables-шаблона

Сначала создайте наборы и цепочку:

```bash
sudo ipset create ru-direct hash:net family inet hashsize 4096 maxelem 1048576
sudo ipset create awg-force hash:net family inet hashsize 4096 maxelem 1048576

sudo iptables -t mangle -N WEBPROXY_AWG 2>/dev/null || true
sudo iptables -t mangle -F WEBPROXY_AWG

sudo iptables -t mangle -A WEBPROXY_AWG \
  -m set --match-set awg-force dst \
  -j MARK --set-mark 1 \
  -m comment --comment webproxy-awg-force

sudo iptables -t mangle -A WEBPROXY_AWG \
  -m set --match-set ru-direct dst \
  -j RETURN \
  -m comment --comment webproxy-direct

sudo iptables -t mangle -A WEBPROXY_AWG \
  -j MARK --set-mark 1 \
  -m comment --comment webproxy-awg-default

sudo iptables -t mangle -A OUTPUT \
  -m owner --uid-owner 3proxy \
  -j WEBPROXY_AWG \
  -m comment --comment webproxy-owned-output

sudo ip route replace default dev awg1 table 100
sudo ip rule replace priority 100 fwmark 1 lookup 100
```

Не используйте `iptables -F` целиком. Скрипт панели не удаляет чужие цепочки и только очищает собственную цепочку `WEBPROXY_AWG`.

## Сохранение правил

`ipset`, `iptables`, `ip rule` и `ip route` обычно не сохраняются после reboot. Установите netfilter-persistent либо создайте systemd unit.

### iptables/netfilter-persistent

```bash
sudo apt install -y netfilter-persistent iptables-persistent
sudo netfilter-persistent save
```

Сохранить ipset:

```bash
sudo ipset save ru-direct > /tmp/ru-direct.ipset
sudo ipset save awg-force > /tmp/awg-force.ipset
sudo mkdir -p /etc/ipset
sudo ipset save > /etc/ipset/ipset.conf
```

После reboot:

```bash
sudo ipset restore -! -f /etc/ipset/ipset.conf
sudo iptables-restore -n < /etc/iptables/rules.v4
```

Уточните имена файлов и пакет netfilter-persistent для вашей версии ОС.

### Пример systemd для правил панели

```ini
[Unit]
Description=Restore 3proxy routing policy
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/webproxy-routing --ru-url https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Для полной persistence установите скрипт в `/usr/local/sbin/webproxy-routing`:

```bash
sudo install -m 0750 scripts/route_awg.py /usr/local/sbin/webproxy-routing
sudo systemctl daemon-reload
sudo systemctl enable --now webproxy-routing.service
```

После reboot также должна восстановиться конфигурация AWG-интерфейса `awg1`. Скрипт проверяет наличие интерфейса и падает до изменения route, если интерфейс отсутствует.

## Частичная установка production-приложения

Создайте системного пользователя:

```bash
sudo useradd --system --home /opt/web-proxy --shell /usr/sbin/nologin webproxy
sudo install -d -m 0750 -o webproxy -g webproxy /var/lib/web-proxy
sudo install -d -m 0755 /opt/web-proxy
```

Скопируйте проект в `/opt/web-proxy`, создайте виртуальное окружение и установите зависимости:

```bash
cd /opt/web-proxy
sudo -u webproxy python3 -m venv .venv
sudo -u webproxy .venv/bin/pip install -e .
```

Установите sudoers-файл только после проверки абсолютного пути Python и скрипта:

```bash
sudo install -m 0440 deploy/route-helper.sudoers /etc/sudoers.d/webproxy-routing
sudo visudo -c
```

Пример sudoers позволяет запускать только конкретный скрипт с любыми аргументами. Для более строгой production-политики используйте разрешённый фиксированный набор аргументов и отдельный привилегированный daemon.

Установите systemd unit:

```bash
sudo install -m 0644 deploy/webproxy.service /etc/systemd/system/webproxy.service
sudo systemctl daemon-reload
sudo systemctl enable --now webproxy.service
```

Рекомендуется использовать reverse proxy с TLS:

```text
Internet -> nginx/caddy -> 127.0.0.1:8000
```

Не публикуйте FastAPI прямо в интернет без reverse proxy и firewall.

## Статистика 3proxy

По умолчанию приложение читает `/var/log/3proxy/3proxy.log` построчно и агрегирует данные по имени пользователя и дате.

Шаблон проекта ожидает tab-separated формат:

```text
timestamp<TAB>username<TAB>client_ip<TAB>remote_host<TAB>bytes_in<TAB>bytes_out<TAB>...
```

Пример развёртывания шаблона логов в 3proxy:

```text
logformat "- %t\t%U\t%C\t%R\t%I\t%O\t%E\t%p\t%T"
```

Запись новых записей:

```bash
sudo tail -n 100 -F /var/log/3proxy/3proxy.log
```

Полный пересчёт через API:

```bash
curl -b 'session=<cookie>' \
  -X POST http://127.0.0.1:8000/api/statistics/collect
```

Через curl session-cookie создаётся только после входа в браузере или локального reverse proxy. Не передавайте сессию в публичные скрипты или shell-history.

Для production добавьте параллельный collector с:

- отслеживанием offset/inode при ротации;
- защитой от повторного чтения логов;
- ограничением пути и правами чтения;
- периодическим full reindex;
- поддержкой конкретного формата `counterin/countout/countall` или `3proxy-fup/JSON`, если используется эта сборка.

Проверьте активные соединения/счётчики вашей сборкой:

```bash
sudo ss -ntp | grep -E '1080|3128'
sudo journalctl -u 3proxy.service -n 100 --no-pager
sudo ls -la /var/lib/3proxy /var/log/3proxy
```

Не существует единого формата счётчиков для всех сборок 3proxy. Формат логов и counters нужно закрепить параметрами вашей конкретной сборки.

## Проверка и тесты

```bash
.venv/bin/python -m pytest
.venv/bin/python -m compileall -q app scripts
```

Проверка Docker нет: приложение запускается непосредственно на Linux-хосте, где доступно управление ipset/iptables, AWG и systemd. Запуск в контейнере возможен только с корректными capability/host network и теми же systemd/service dependency.

Проверка установленного окружения:

```bash
curl -sSf http://127.0.0.1:8000/login >/dev/null
curl -sSf http://127.0.0.1:8000/openapi.json >/dev/null
systemctl is-active 3proxy.service
sudo ipset list ru-direct
sudo iptables -t mangle -n -L WEBPROXY_AWG
sudo ip rule show
sudo ip route show table 100
```

## Подводные камни

- Не используйте `iptables -F` целиком: скрипт должен очищать только собственную цепочку.
- Не удаляйте чужие `fwmark`, `ip rule`, routing table или ipset по общему имени.
- Для concurrent изменений используйте flock, который уже предусмотрен в routing helper.
- Атомарная замена ipset выполняется через temporary set + `swap`.
- При падении AWG удалите stale default route или восстановите route с новой интерфейсной конфигурацией.
- Изменение `awg1` требует повторного создания default route в table `100`.
- `rp_filter=1` может ломать asymmetric routing; проверяйте значения:

```bash
sudo sysctl net.ipv4.conf.all.rp_filter
sudo sysctl net.ipv4.conf.default.rp_filter
```

- Не запускайте панель от root и не доверяйте неограниченному shell доступу;
- ограничьте sudoers конкретным Python executable и конкретным скриптом;
- сохраняйте `iptables-save`, `ipset save`, `ip rule`, маршруты и 3proxy.cfg до применения;
- реализуйте rollback при ошибке reload или применения route;
- храните пароли БД, users-файла и session secret вне репозитория;
- всегда тестируйте на staging-хосте перед production, особенно изменение UID-owner, DNS, локальных подсетей и существующих правил policy routing.
